"""P4 内部 AXI 采集和 PL 推理驱动。CPU 演示模式不会冒充硬件加速。"""
import asyncio
import gc
import json
import threading
import time
import struct
from pathlib import Path

import numpy as np
from output_settings import CLOCK_HZ, DEFAULTS, LEVEL_DEFAULTS, REFERENCE_DEFAULT, INTERFACE_VERSION, TIMING_SCHEMA, actual_settings, parse_settings, parse_levels, window_summary
from threshold_settings import parse_thresholds
from model_algorithms import algorithm_info, algorithm_key
from dense_models import FORMAT as DENSE_FORMAT, pack_dense, softmax
from cnn_models import FORMAT as CNN_FORMAT, pack_cnn
from feature_contract import FEATURE_VERSION, feature_count

MAX_CLASSES, MAX_TREES, MAX_NODES, MAX_DEPTH = 64, 128, 16384, 32


def pack_model(path):
    """校验便携森林，生成 HLS 使用的 double 节点表，不反序列化外来 pickle。"""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("format") not in ("tdc_random_forest_v1", DENSE_FORMAT, CNN_FORMAT):
        raise ValueError("PL模型参数格式不匹配")
    inputs=feature_count(data)
    if not np.isfinite(float(data.get('timing_reference_bin',0))):raise ValueError('时移基线不是有限值')
    expected = dict(smooth_bins=41, reference_search_start=512, reference_search_end=30000,
                    return_min_offset=2000, return_max_offset=20000, exclude_end_bins=1024,
                    min_return_smoothed_height=5.0, smoothing_method="integer_window_sum_nearest")
    if data.get("feature_settings") != expected:
        raise ValueError("模型特征配置与 PL 不一致，禁止加载")
    if data.get("format") in (DENSE_FORMAT,CNN_FORMAT):
        if data.get("settings", [0])[0] != 65536:
            raise ValueError("PL神经网络要求65536bin")
        packed = pack_cnn(data) if data['format']==CNN_FORMAT else pack_dense(data)
        data["model_kind"] = 3 if data['format']==CNN_FORMAT else 2
        return data, packed, 0
    data["model_kind"] = 0
    classes, trees = data["class_names"], data["trees"]
    if not 1 <= len(classes) <= MAX_CLASSES or len(set(classes)) != len(classes):
        raise ValueError("类别必须唯一，数量为 1–64")
    if not 1 <= len(trees) <= MAX_TREES:
        raise ValueError("PL 支持 1–128 棵树、匹配的8/9维特征")
    if data.get("settings", [0])[0] != 65536:
        raise ValueError("当前采集桥要求 65536 个 bin")
    total = sum(len(t["left"]) for t in trees)
    if total > MAX_NODES:
        raise ValueError("节点总数超过 16384；请减少树数或深度")
    roots, rows, offset = [], [], 0
    for tree in trees:
        size = len(tree["left"])
        if size < 1 or any(len(tree[k]) != size for k in ["right", "feature", "threshold", "probabilities"]):
            raise ValueError("树节点数组长度不一致")
        # 遍历检查可达性、子节点索引和深度，防止损坏参数导致 AXI 越界。
        pending, visited = [(0, 0)], set()
        while pending:
            node, depth = pending.pop()
            if node in visited or not 0 <= node < size or depth > MAX_DEPTH:
                raise ValueError("树存在环、无效索引或深度超过32")
            visited.add(node)
            feature = tree["feature"][node]
            if feature == -2:
                if tree["left"][node] != -1 or tree["right"][node] != -1:
                    raise ValueError("叶节点结构不正确")
            elif 0 <= feature < inputs and depth < MAX_DEPTH:
                pending += [(int(tree["left"][node]), depth + 1), (int(tree["right"][node]), depth + 1)]
            else:
                raise ValueError("无效特征索引或树过深")
        if len(visited) != size:
            raise ValueError("树包含不可达节点")
        roots.append(offset)
        for node in range(size):
            probabilities = np.asarray(tree["probabilities"][node], dtype=np.float64)
            if probabilities.shape != (len(classes),) or not np.isfinite(probabilities).all() or (probabilities < 0).any() or not np.isclose(probabilities.sum(), 1.0):
                raise ValueError("节点概率无效或类别数不一致")
            feature, threshold = int(tree["feature"][node]), float(tree["threshold"][node])
            if not np.isfinite(threshold):
                raise ValueError("阈值不是有限数")
            left, right = int(tree["left"][node]), int(tree["right"][node])
            rows.extend([feature, left + offset if left >= 0 else -1,
                         right + offset if right >= 0 else -1, threshold] + probabilities.tolist())
        offset += size
    return data, np.asarray(roots + rows, dtype=np.float64), total


class PlRuntime:
    """一次只执行一帧。快照完成后保持不变，PS/加速器读取完才开始下一帧。"""
    def __init__(self, bitfile):
        self.bitfile = Path(bitfile).resolve()
        self.overlay = None
        self.model_buffer = self.result_buffer = None
        self.model_key = self.metadata = None
        self.lock = threading.RLock()
        # 输出开关不等待整帧采集锁，网页可在采集中直接关闭信号。
        self.output_lock = threading.RLock()
        self.faulted = False
        self.last_capture_timing = {}

    def load(self, reuse_loaded=False):
        """仅在网页明确选择 PL 后调用；下载会重新配置整个 PL。"""
        if self.overlay is not None:
            return
        if not self.bitfile.is_file() or not self.bitfile.with_suffix(".hwh").is_file():
            raise ValueError("缺少同一次构建的 tdc_pynq.bit 和 tdc_pynq.hwh，请先构建 Overlay")
        # Flask请求运行在线程中，Python3.8不会自动给这些线程创建事件循环。
        # PYNQ2.7的XRT设备初始化会取得它；本驱动的采集/推理仍采用寄存器轮询。
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)
        from pynq import Overlay, MMIO, allocate
        self.allocate = allocate
        overlay = Overlay(str(self.bitfile), download=False)
        if not {"capture", "accelerator"}.issubset(overlay.ip_dict):
            raise ValueError("HWH 不是本项目内部采集接口")
        # PYNQ2.7将BRAM控制器归入mem_dict；不能只在ip_dict里查找。
        desc = overlay.mem_dict.get("histogram", overlay.ip_dict.get("histogram"))
        if desc is None or desc["addr_range"] < 65536 * 4:
            raise ValueError("快照地址空间不足")
        expected_offsets = {"hist_1":0x10, "model_1":0x1c, "result_1":0x28,
                            "bin_count":0x34, "class_count":0x3c, "tree_count":0x44, "node_count":0x4c}
        registers = overlay.ip_dict["accelerator"]["registers"]
        if any(registers.get(name,{}).get("address_offset")!=offset for name,offset in expected_offsets.items()):
            raise ValueError("HLS寄存器版本不匹配")
        self.supports_dense = registers.get("model_kind",{}).get("address_offset") == 0x54
        self.supports_shift = (registers.get('feature_count',{}).get('address_offset')==0x5c
                               and registers.get('timing_reference_bin_1',{}).get('address_offset')==0x64
                               and registers.get('timing_reference_bin_2',{}).get('address_offset')==0x68)
        if reuse_loaded:
            from pynq import PL
            if Path(PL.bitfile_name or '').resolve() != self.bitfile or 'capture' not in PL.ip_dict:
                raise ValueError('当前PL并非本项目Overlay，不能无下载接管')
        else:
            overlay.download()
        capture = overlay.capture
        if (capture.read(0) != 0x54444331 or capture.read(4) != INTERFACE_VERSION
                or capture.read(0x88) != CLOCK_HZ or capture.read(0xc4) != 0x4c564453):
            raise ValueError("需要版本5的跨周期/低有效门控Overlay，请配套更新bit、hwh和驱动")
        if not reuse_loaded:
            capture.write(0x40, 0)
            capture.write(0x0c, 1)
        result_buffer = allocate(shape=(88 if self.supports_shift else 80,), dtype=np.float64)
        if result_buffer.physical_address + result_buffer.nbytes > 0x80000000:
            result_buffer.freebuffer()
            raise ValueError("结果缓冲区超出当前AXI映射的2GB DDR范围")
        self.capture = capture
        self.accelerator = overlay.accelerator
        self.hist_address = desc["phys_addr"]
        self.hist = MMIO(desc["phys_addr"], 65536 * 4)
        self.result_buffer = result_buffer
        self.overlay = overlay
        if not reuse_loaded:
            # 配置页面的默认值由软件明确提交；兼容同版bit中的旧复位值。
            # 接管已加载PL时绝不覆盖现有波形参数。
            self.restore_defaults()

    def output_status(self):
        if self.overlay is None:
            return {"available": False, "enabled": False, "running": False}
        # 不等待output_lock：另一请求正在提交参数时，仍可轮询状态或关闭输出。
        ip = self.capture
        flags = ip.read(0x5c)
        cycles = [ip.read(address) for address in (0x60, 0x64, 0x68, 0x6c, 0x70)]
        reference = ip.read(0x7c)
        levels, pending = {}, False
        for number, address in ((1, 0x80), (2, 0x84)):
            requested, actual = ip.read(address), ip.read(address + 0x10)
            levels["dac{}_low".format(number)] = actual & 1023
            levels["dac{}_high".format(number)] = (actual >> 16) & 1023
            pending |= requested != actual
        return {"available": True, "enabled": bool(ip.read(0x40) & 1),
                "running": bool(flags & 1), "busy": bool(flags & 2),
                "error": bool(flags & 4), "actual_enabled": bool(flags & 8),
                "sequence": ip.read(0x74), "cycles": cycles, "actual": actual_settings(cycles),
                "reference_source": "internal" if reference & 1 else "external",
                "reference_pending": bool(reference & 4), "dac_ready": bool(reference & 2),
                "levels": levels, "levels_pending": pending, "clock_hz": CLOCK_HZ, "tick_ns": 8,
                "thresholds": self.threshold_status(), "timing_schema": TIMING_SCHEMA,
                "windows": window_summary(cycles)}

    def threshold_status(self):
        """回读已完成串行发送的设置；没有ADC，不能据此声称实测模拟电压。"""
        if self.overlay is None:
            return {"available": False, "ready": False, "busy": False,
                    "threshold_a_v": 0.300, "threshold_b_v": 0.300}
        flags = self.capture.read(0xac)
        codes = self.capture.read(0xbc)
        return {"available": True, "ready": bool(flags & 2), "busy": bool(flags & 1),
                "error": bool(flags & 4), "threshold_a_v": self.capture.read(0xb0) / 1000.0,
                "threshold_b_v": self.capture.read(0xb4) / 1000.0,
                "code_a": codes & 4095, "code_b": (codes >> 16) & 4095,
                "sequence": self.capture.read(0xb8), "step_v": 0.002, "max_v": 1.0}

    def configure_thresholds(self, options):
        values = parse_thresholds(options)
        with self.lock, self.output_lock:
            if self.overlay is None:
                raise ValueError("请先加载版本5的跨周期/低有效门控Overlay")
            current = self.output_status()
            if self.capture.read(8) & 2 or current["enabled"] or current["actual_enabled"]:
                raise ValueError("请先停止采集并关闭持续输出，再修改比较器阈值")
            if not current["thresholds"]["ready"] or current["thresholds"]["busy"]:
                raise ValueError("阈值DAC尚未就绪或正在写入，请稍后重试")
            old_sequence = current["thresholds"]["sequence"]
            self.capture.write(0xa0, values[0])
            self.capture.write(0xa4, values[1])
            self.capture.write(0xa8, 1)
            deadline = time.monotonic() + 0.5
            while True:
                result = self.threshold_status()
                if result["error"]:
                    raise ValueError("硬件拒绝阈值设置，原已发送值保持不变")
                if result["sequence"] != old_sequence and result["ready"] and not result["busy"]:
                    actual = [round(result[key] * 1000) for key in ("threshold_a_v", "threshold_b_v")]
                    if actual != values:
                        raise ValueError("阈值回读与请求不一致，请保持输出关闭")
                    return self.output_status()
                if time.monotonic() > deadline:
                    raise ValueError("阈值DAC发送确认超时，请保持输出关闭并检查状态")
                time.sleep(0.001)

    def configure_outputs(self, options):
        cycles = parse_settings(options)
        with self.output_lock:
            if self.overlay is None:
                raise ValueError("请先加载版本5的跨周期/低有效门控Overlay")
            ip = self.capture
            current = self.output_status()
            levels = parse_levels(options, current["levels"])
            level_changed = levels != current["levels"]
            if level_changed and (current["enabled"] or ip.read(8) & 2):
                raise ValueError("请先停止采集并关闭持续输出，再修改DAC电平码值")
            if ip.read(0x5c) & 2:
                raise ValueError("上一组输出参数尚未生效，请稍后再试")
            old_sequence = ip.read(0x74)
            # 运行时整组参数在旧周期结束时生效；关闭时立即生效。
            timeout = ip.read(0x60) / float(CLOCK_HZ) + 0.5
            for offset, value in zip((0x48, 0x4c, 0x50, 0x54, 0x58), cycles):
                ip.write(offset, value)
            ip.write(0x44, 1)
            deadline = time.monotonic() + timeout
            while ip.read(0x74) == old_sequence or ip.read(0x5c) & 2:
                if time.monotonic() > deadline:
                    raise ValueError("输出参数提交超时，请查看状态；仍可点击关闭输出")
                time.sleep(0.001)
            status = self.output_status()
            if status["error"] or status["cycles"] != cycles:
                raise ValueError("硬件未接受输出参数，原参数保留")
            if level_changed:
                for number, address in ((1, 0x80), (2, 0x84)):
                    ip.write(address, levels["dac{}_low".format(number)] | levels["dac{}_high".format(number)] << 16)
                deadline = time.monotonic() + 0.2
                while True:
                    status = self.output_status()
                    if not status["levels_pending"] and status["levels"] == levels:
                        break
                    if time.monotonic() > deadline:
                        raise ValueError("DAC码值未收到硬件确认；请保持输出关闭")
                    time.sleep(0.001)
            return status

    def restore_defaults(self):
        """恢复本页全部硬件参数。先关闭输出，任何步骤失败都不重新开启。"""
        with self.lock, self.output_lock:
            if self.overlay is None:
                raise ValueError("请先加载本项目Overlay")
            if self.capture.read(8) & 2:
                raise ValueError("请先停止采集，再恢复默认参数")
            self.enable_outputs(False)
            self.configure_outputs(dict(DEFAULTS, **LEVEL_DEFAULTS))
            self.set_reference(REFERENCE_DEFAULT)
            deadline=time.monotonic()+.5
            while not self.threshold_status()['ready']or self.threshold_status()['busy']:
                if time.monotonic()>deadline:raise ValueError('阈值DAC未就绪，请保持输出关闭后重试恢复默认')
                time.sleep(.001)
            return self.configure_thresholds({"threshold_a_v": "0.300", "threshold_b_v": "0.300"})

    def set_reference(self, source):
        """仅在停止采集且输出关闭时切换，避免切换边沿被误算为一次触发。"""
        if source not in ("external", "internal"):
            raise ValueError("参考源只能是external或internal")
        with self.lock, self.output_lock:
            if self.overlay is None:
                raise ValueError("请先加载版本5的跨周期/低有效门控Overlay")
            status = self.output_status()
            if self.capture.read(8) & 2 or status["enabled"] or status["busy"]:
                raise ValueError("请先停止采集并关闭持续输出，再切换参考源")
            self.capture.write(0x78, int(source == "internal"))
            deadline = time.monotonic() + 0.2
            while True:
                status = self.output_status()
                if status["reference_source"] == source and not status["reference_pending"]:
                    return status
                if time.monotonic() > deadline:
                    raise ValueError("参考源切换未收到硬件确认，请保持输出关闭")
                time.sleep(0.001)

    def enable_outputs(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("enabled必须为布尔值")
        if self.overlay is None:
            raise ValueError("请先加载版本5的跨周期/低有效门控Overlay")
        if enabled:
            with self.output_lock:
                status = self.output_status()
                if (not status["dac_ready"] or status["busy"] or status["levels_pending"]
                        or status["reference_pending"] or not status["thresholds"]["ready"]):
                    raise ValueError("DAC时钟或参数尚未就绪，请稍后开启输出")
                self.capture.write(0x40, 1)
        else:
            # 关闭只有一个AXI写事务，不等待采集锁或参数提交锁。
            self.capture.write(0x40, 0)
        deadline = time.monotonic() + 0.2
        while True:
            status = self.output_status()
            if status["actual_enabled"] == enabled and status["running"] == enabled:
                return status
            if time.monotonic() > deadline:
                raise ValueError("输出开关未收到硬件确认")
            time.sleep(0.001)

    def status(self):
        if self.overlay is None:
            return {"loaded": False, "bitfile": str(self.bitfile), "faulted": self.faulted, "outputs": self.output_status()}
        status = self.capture.read(8)
        return {"loaded": True, "calibrated": bool(status & 1), "busy": bool(status & 2),
                "completed": bool(status & 4), "error": self.capture.read(0x28),
                "model_id": self.metadata["model_id"] if self.metadata else None,
                "faulted": self.faulted, "interface_version": self.capture.read(4),
                "input_standard": "LVDS", "outputs": self.output_status()}

    def release_model(self):
        """只在加速器空闲时归还连续内存；未选模型不保留参数缓冲。"""
        with self.lock:
            if self.model_buffer is not None:
                if self.accelerator is not None and not self.accelerator.read(0) & 4:
                    raise ValueError("PL尚未空闲，不能释放仍可能被硬件读取的模型")
                self.model_buffer.freebuffer()
            self.model_buffer = self.model_key = self.metadata = None
            gc.collect()

    def set_model(self, path):
        path = Path(path)
        stat = path.stat()
        key = str(path.resolve()), stat.st_mtime_ns, stat.st_size
        if key == self.model_key:
            return
        # 先释放上一份模型，避免切换时两份连续内存同时常驻。
        self.release_model()
        metadata, packed, total = pack_model(path)
        new_buffer = self.allocate(shape=packed.shape, dtype=np.float64)
        if new_buffer.physical_address + new_buffer.nbytes > 0x80000000:
            new_buffer.freebuffer()
            raise ValueError("模型缓冲区超出当前AXI映射的2GB DDR范围")
        try:
            new_buffer[:] = packed
            new_buffer.flush()
        except Exception:
            new_buffer.freebuffer()
            raise
        # 完整节点表已放入PL可读缓冲；只保留类别/版本等小型元数据。
        light = {key: value for key, value in metadata.items() if key not in ("trees", "weights", "bias", "parameters")}
        light["tree_count"] = len(metadata.get("trees", []))
        self.model_buffer, self.metadata, self.node_count = new_buffer, light, total
        self.model_key = key

    def _idle(self):
        if self.faulted:
            raise ValueError("加速器曾超时，须重启网页进程并重新加载 Overlay 后再操作")
        if self.capture.read(8) & 2 or not self.accelerator.read(0) & 4:
            raise ValueError("PL 正在执行上一帧，不能覆盖快照或模型")

    def _abort_capture(self):
        if self.capture.read(8) & 2:
            self.capture.write(0x10, 2)
            deadline = time.monotonic() + 1
            while self.capture.read(8) & 2:
                if time.monotonic() > deadline:
                    self.faulted = True
                    raise ValueError("采集取消未确认，接口已锁定")
                time.sleep(0.001)

    def collect(self, config, stop_event):
        from frame_format import Cancelled
        with self.lock:
            started = time.perf_counter()
            self.last_capture_timing = {}
            self.load(); self._idle()
            if int(config["bin_num"]) != 65536:
                raise ValueError("当前 PL 采集固定为65536bin")
            if not self.capture.read(8) & 1:
                raise ValueError("TDC尚未完成双通道校准，请检查DNA授权、时钟及复位")
            outputs = self.output_status()
            if not outputs["thresholds"]["ready"] or outputs["thresholds"]["busy"]:
                raise ValueError("比较器阈值尚未完成发送，请稍后开始采集")
            if outputs["reference_pending"]:
                raise ValueError("参考源仍在切换，请稍后开始采集")
            if outputs["reference_source"] == "internal" and not outputs["running"]:
                raise ValueError("内部参考来自DAC1触发，请先开启持续输出再采集")
            self.capture.write(0x14, int(config["trig_num"]))
            self.capture.write(0x18, 65536)
            self.capture.write(0x1c, int(config["bin_width"]))
            old_sequence = self.capture.read(0x20)
            self.capture.write(0x10, 1)
            deadline = time.monotonic() + float(config.get("timeout_s", 15))
            try:
                while True:
                    if stop_event.is_set(): raise Cancelled()
                    status = self.capture.read(8)
                    if status & 4:
                        error = self.capture.read(0x28)
                        if error: raise ValueError("PL采集错误码 {}".format(error))
                        if self.capture.read(0x20) == old_sequence or self.capture.read(0x24) != 65536:
                            raise ValueError("快照序号/完整性检查失败")
                        read_started = time.perf_counter()
                        counts = self.hist.array[:65536].copy()
                        self.last_capture_timing = {"acquire_ms": round((read_started - started) * 1000, 3),
                            "read_ms": round((time.perf_counter() - read_started) * 1000, 3)}
                        return counts
                    if time.monotonic() > deadline: raise ValueError("PL采集超时，检查参考触发是否进入TDC通道1")
                    time.sleep(0.002)
            finally:
                self._abort_capture()

    @staticmethod
    def _write_address(ip, offset, address):
        ip.write(offset, int(address) & 0xffffffff)
        ip.write(offset + 4, int(address) >> 32)

    def infer(self, counts, model_path, captured=False, acquisition_settings=None):
        """captured=True 直接读取 PL 快照；文件/历史帧则先写入同一快照 BRAM。"""
        with self.lock:
            self.load(); self._idle(); self.set_model(model_path)
            kind = self.metadata.get("model_kind", 0)
            dimensions=feature_count(self.metadata)
            if (dimensions==9 or kind==3) and not getattr(self,'supports_shift',False):
                raise ValueError('当前Overlay不支持9维时移/CNN，请加载本次配套bit与hwh')
            if kind and not getattr(self,"supports_dense",False):
                self.release_model()
                raise ValueError("当前Overlay仅支持树模型，请加载新版SVM/MLP Overlay")
            if acquisition_settings is not None and list(self.metadata["settings"]) != list(acquisition_settings):
                raise ValueError("采集参数与模型训练参数不一致，请重新采集/训练")
            values = np.asarray(counts)
            if values.shape != (65536,) or not np.isfinite(values).all() or (values < 0).any() or (values > 0xffffffff).any() or not np.equal(values, np.floor(values)).all():
                raise ValueError("直方图必须为65536个uint32计数")
            if not captured:
                self.hist.array[:65536] = values.astype(np.uint32)
            self.result_buffer[:] = 0; self.result_buffer.flush()
            ip = self.accelerator
            self._write_address(ip, 0x10, self.hist_address)
            self._write_address(ip, 0x1c, self.model_buffer.physical_address)
            self._write_address(ip, 0x28, self.result_buffer.physical_address)
            ip.write(0x34, 65536); ip.write(0x3c, len(self.metadata["class_names"]))
            ip.write(0x44, self.metadata["tree_count"]); ip.write(0x4c, self.node_count)
            if getattr(self,"supports_dense",False):
                ip.write(0x54, kind)
            if getattr(self,'supports_shift',False):
                ip.write(0x5c,dimensions)
                low,high=struct.unpack('<II',struct.pack('<d',float(self.metadata.get('timing_reference_bin',0))))
                ip.write(0x64,low);ip.write(0x68,high)
            started = time.monotonic(); ip.write(0, 1)
            while not ip.read(0) & 2:
                if time.monotonic() - started > 5:
                    # 未完成时 DDR 仍可能被AXI访问，保留缓冲区，阻止后续覆盖/释放。
                    self.faulted = True
                    raise ValueError("PL推理超时，已锁定本次运行，请检查AXI地址和时钟")
                time.sleep(0.0005)
            elapsed = (time.monotonic() - started) * 1000
            self.result_buffer.invalidate()
            output = np.asarray(self.result_buffer).copy()
            if output[0] != 0:
                raise ValueError("PL特征提取/推理错误码 {}".format(int(output[0])))
            classes = self.metadata["class_names"]
            score_start=24 if getattr(self,'supports_shift',False) else 16
            raw_scores = output[score_start:score_start+len(classes)]
            scores = softmax(raw_scores.reshape(1,-1))[0] if kind else raw_scores
            expected_version = 3 if getattr(self,'supports_shift',False) else 2 if getattr(self,"supports_dense",False) else 1
            if output[4] != expected_version or not np.isfinite(output[:8+dimensions]).all() or not np.isfinite(raw_scores).all() or not np.isfinite(scores).all() or (scores < 0).any() or not np.isclose(scores.sum(), 1.0):
                raise ValueError("PL结果协议/概率校验失败，禁止把空结果识别为第一类")
            if expected_version==3 and (output[5]!=dimensions or output[6]!=float(self.metadata.get('timing_reference_bin',0))):
                raise ValueError('PL时移基线/维数回读与当前模型不一致')
            if output[1] != int(np.argmax(raw_scores)):
                raise ValueError("PL类别索引与各类概率不一致")
            return {"material": classes[int(output[1])], "reference_bin": int(output[2]),
                    "return_bin": int(output[3]), "class_scores": {name:round(float(scores[i]),4) for i,name in enumerate(classes)},
                    "features": output[8:8+dimensions].tolist(), "model_id": self.metadata["model_id"],
                    "peak_shift_bins": float(output[16]) if dimensions==9 else None,
                    "backend": "PL 特征提取 + PL " + algorithm_info(algorithm_key(self.metadata.get("model_type", "RandomForestClassifier")))["name"],
                    "model_type": self.metadata.get("model_type", "RandomForestClassifier"), "elapsed_ms": round(elapsed, 3)}
