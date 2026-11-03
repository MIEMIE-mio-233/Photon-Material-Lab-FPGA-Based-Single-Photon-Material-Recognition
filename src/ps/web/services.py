"""网页业务层：串行任务、数据存储、模型调用；复用现有特征提取函数。"""

import csv
import gc
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, OrderedDict, deque
from datetime import datetime
from pathlib import Path

import numpy as np

from frame_format import Cancelled, decode_frame

PROJECT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("MPLBACKEND", "Agg")
import train_material as training
import predict_material as inference
from pl_runtime import PlRuntime, pack_model
from data_catalog import collection_manifests, has_material_label
from model_registry import ModelRegistry
from model_algorithms import ALGORITHMS
from training_charts import TrainingCharts
from output_settings import TIMING_SCHEMA
from acquisition_metadata import parse_distance, sample_kind, material_row, timing_signature, illumination
from live_ranging import LiveRangeCalibration

MANIFEST_FIELDS = ["run_id", "task_index", "material_id", "specimen_id", "distance_cm", "sample_kind", "illumination", "experiment_round", "schema_version", "frame_index", "attempt", "timestamp", "trig_freq_hz", "trig_num", "bin_num", "bin_width_ps", "received_bytes", "total_counts", "peak_bin_index", "csv_path", "raw_path"]


class BusyError(ValueError):
    pass


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def identifier(value, label):
    if not re.fullmatch(r"[a-z0-9_]{1,48}", str(value)):
        raise ValueError("{}只能使用小写英文、数字和下划线，长度 1–48".format(label))
    return str(value)


def bounded_int(value, low, high, label):
    if isinstance(value, bool) or str(value).strip() != str(int(value)):
        raise ValueError("{}必须为整数".format(label))
    number = int(value)
    if not low <= number <= high:
        raise ValueError("{}应在 {}–{} 之间".format(label, low, high))
    return number


def local_addresses():
    """只读取本机网络地址，网页不会自动改 IP。"""
    try:
        text = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], timeout=3).decode()
        return [{"interface": match.group(1), "ip": match.group(2)} for match in re.finditer(r"\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/", text)]
    except (OSError, subprocess.SubprocessError):
        return []


class DataStore:
    def __init__(self):
        self.index_lock, self.cached_index, self.index_signature = threading.RLock(), None, None
        self.manifest_cache = {}
        self.index_refresh_lock = threading.Lock()
        self.next_index_check, self.index_error = 0.0, None
        for path in (PROJECT / "dataset", WEB / "uploads", WEB / "runtime"):
            path.mkdir(parents=True, exist_ok=True)

    def resolve_frame(self, value):
        path = (PROJECT / str(value)).resolve()
        allowed = [PROJECT / "dataset", WEB / "uploads"]
        for folder in allowed:
            try:
                path.relative_to(folder.resolve())
                break
            except ValueError:
                continue
        else:
            raise ValueError("只能读取项目数据目录中的单帧文件")
        if path.suffix.lower() not in (".csv", ".npy") or not path.is_file():
            raise ValueError("找不到单帧CSV或NPY")
        return path

    def index(self, force=False):
        """仅重建发生变化的批次；缓存中的列表按快照替换，供状态请求直接读取。"""
        with self.index_lock:
            manifests = collection_manifests(PROJECT / "dataset")
            signature = []
            current = {}
            for path in manifests:
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                key = str(path)
                stamp = (stat.st_mtime_ns, stat.st_size)
                signature.append((key,) + stamp)
                cached = self.manifest_cache.get(key)
                if force or cached is None or cached[0] != stamp:
                    cached = (stamp, self._build_index([path]))
                current[key] = cached
            signature = tuple(signature)
            if not force and self.cached_index is not None and signature == self.index_signature:
                return self.cached_index
            frames, runs = [], []
            for _, part in current.values():
                frames.extend(part["frames"])
                runs.extend(part["runs"])
            labeled = [item for item in frames if material_row(item)]
            indexed = {"frames": frames, "runs": runs,
                       "materials": sorted(set(item["material"] for item in frames)),
                       "counts": dict(Counter(item["material"] for item in frames)),
                       "frame_count": len(frames),
                       "specimen_count": len(set((item["material"], item["specimen"]) for item in labeled)),
                       "training_frame_count": len(labeled),
                       "training_materials": sorted(set(item["material"] for item in labeled))}
            self.manifest_cache = current
            self.cached_index, self.index_signature = indexed, signature
            return indexed

    def status_index(self):
        """高频状态读取不等待目录扫描；外部文件变化每两秒在后台核验一次。"""
        now = time.monotonic()
        if now >= self.next_index_check and self.index_refresh_lock.acquire(False):
            self.next_index_check = now + 2.0
            def refresh():
                try:
                    self.index()
                    self.index_error = None
                except (OSError, ValueError) as error:
                    self.index_error = str(error)
                finally:
                    self.index_refresh_lock.release()
            threading.Thread(target=refresh, name="tdc-catalog-refresh", daemon=True).start()
        return self.cached_index if self.cached_index is not None else self._build_index([])

    def _build_index(self, manifests):
        frames, runs = [], []
        for manifest in manifests:
            base = manifest.parent.resolve()
            rows = []
            with manifest.open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    try:
                        frame = (base / row["csv_path"].replace("\\", "/")).resolve()
                        frame.relative_to(base)
                        if not frame.is_file():
                            continue
                        collection = manifest.parent.parent.name
                        item = {"path": frame.relative_to(PROJECT).as_posix(), "run": manifest.parent.name, "run_key": collection + "/" + manifest.parent.name, "material": row["material_id"], "specimen": row["specimen_id"], "frame_index": int(row["frame_index"]), "bin_num": int(row["bin_num"]),
                                "bin_width_ps": float(row["bin_width_ps"]) if row.get("bin_width_ps") else None}
                        rows.append(item)
                        item.update(distance_cm=parse_distance(row.get('distance_cm')), sample_kind=sample_kind(row),illumination=illumination(row.get('illumination')),experiment_round=row.get('experiment_round') or None)
                        frames.append(item)
                    except (ValueError, KeyError):
                        continue
            # 零完整帧的失败批次也允许在网页清理。
            collection = manifest.parent.parent.name
            runs.append({"id": manifest.parent.name, "key": collection + "/" + manifest.parent.name,
                         "collection": collection, "material": rows[0]["material"] if rows else "空批次",
                         "specimen": rows[0]["specimen"] if rows else "—", "frames": len(rows),
                         "distance_cm": rows[0].get('distance_cm') if rows else None,
                         "sample_kind": rows[0].get('sample_kind') if rows else 'material',
                         "illumination":rows[0].get('illumination') if rows else None,
                         "experiment_round":rows[0].get('experiment_round') if rows else None,
                         "labeled_frames": sum(material_row(item) for item in rows),
                         "materials": sorted(set(item["material"] for item in rows if has_material_label(item["material"])) )})
        labeled = [item for item in frames if material_row(item)]
        return {"frames": frames, "runs": runs, "materials": sorted(set(item["material"] for item in frames)), "counts": dict(Counter(item["material"] for item in frames)), "frame_count": len(frames), "specimen_count": len(set((item["material"], item["specimen"]) for item in labeled)),
                "training_frame_count": len(labeled), "training_materials": sorted(set(item["material"] for item in labeled))}

    def browser_index(self):
        """所有采集批次使用同一份索引。"""
        return self.index()

    def delete_run(self, collection, run_id):
        """直接删除选定批次；先核验绝对路径，禁止越界或重定向目录。"""
        if collection != "dataset":
            raise ValueError("批次目录无效")
        if not isinstance(run_id, str) or not re.fullmatch(r"run_[A-Za-z0-9_]{1,100}", run_id):
            raise ValueError("批次编号无效")
        with self.index_lock:
            base = (PROJECT / collection).resolve()
            if base.parent != PROJECT.resolve() or (PROJECT / collection).is_symlink():
                raise ValueError("数据目录超出项目范围")
            source = base / run_id
            if source.is_symlink() or source.resolve() != source or source.resolve().parent != base or not source.is_dir() or not (source / "manifest.csv").is_file():
                raise ValueError("找不到可删除的采集批次")
            record = {"original": collection + "/" + run_id, "deleted_at": datetime.now().isoformat(),
                      "permanent": True}
            # 已确认source是指定数据根目录的直接子目录。rmtree删除整批CSV、
            # DAT和清单；批次内的符号链接只删除链接本身，不递归目标目录。
            try:
                shutil.rmtree(source)
            finally:
                # 即使因文件占用等原因只删掉部分文件，也必须重新索引实际内容。
                self.cached_index = self.index_signature = None
            return record

    def read(self, path):
        if path.suffix.lower() == ".npy":
            indexes, counts = training.read_frame(path)
            return indexes, counts, None
        raw_path = path.with_suffix(".dat")
        if raw_path.is_file():
            raw = raw_path.read_bytes()
            bins = (len(raw) - 28) // 8
            if bins >= 30000:
                indexes, counts = decode_frame(raw, bins)
                return indexes, counts, raw
        indexes, counts = training.read_frame(path)
        return indexes, counts, None


class FrameWriter:
    def __init__(self, material, specimen, config, source, extra):
        self.config = config
        self.material, self.specimen = material, specimen
        self.distance_cm = parse_distance(extra.get('distance_cm'))
        self.sample_kind = sample_kind(dict(extra,material_id=material))
        self.illumination=illumination(extra.get('illumination'))
        self.experiment_round=str(extra.get('experiment_round') or '')
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.run_id = "run_{}_{}".format(stamp, uuid.uuid4().hex[:6])
        self.root = PROJECT / "dataset" / self.run_id
        self.folder = self.root / "01_{}_{}".format(material, specimen)
        self.folder.mkdir(parents=True)
        self.manifest = self.root / "manifest.csv"
        with self.manifest.open("w", encoding="utf-8", newline="") as stream:
            csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS).writeheader()
        metadata = dict(config, frame_format="npy_uint32_v1", run_id=self.run_id, source=source, material_id=material, specimen_id=specimen,
                        schema_version=3, distance_cm=self.distance_cm, sample_kind=self.sample_kind,
                        illumination=self.illumination,experiment_round=self.experiment_round,
                        output_settings=extra.get("output_settings"))
        (self.root / "config.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self, index, bins, counts, raw, attempt=1):
        # 清单csv_path沿用旧列名，实际可以指向NPY；旧批次无需改动。
        csv_path = self.folder / "frame_{:04d}.npy".format(index)
        raw_path = csv_path.with_suffix(".dat")
        if raw is not None:
            raw_path.write_bytes(raw)
        temporary = csv_path.with_name(csv_path.name + ".tmp")
        values = np.asarray(counts)
        if values.ndim != 1 or not np.isfinite(values).all() or (values < 0).any() or (values > 0xffffffff).any() or not np.equal(values, np.floor(values)).all():
            raise ValueError("保存数据必须是一维uint32范围的整数计数")
        if not np.array_equal(bins, np.arange(values.size)):
            raise ValueError("NPY保存要求bin索引从0开始连续排列")
        with temporary.open("wb") as stream:
            np.save(stream, values.astype("<u4"), allow_pickle=False)
        temporary.replace(csv_path)
        row = dict(run_id=self.run_id, task_index=1, material_id=self.material, specimen_id=self.specimen, frame_index=index, attempt=attempt, timestamp=datetime.now().isoformat(), trig_freq_hz=self.config["trig_freq_hz"], trig_num=self.config["trig_num"], bin_num=len(counts), bin_width_ps=2 ** self.config["bin_width"], received_bytes=len(raw) if raw is not None else 0, total_counts=int(counts.sum()), peak_bin_index=int(bins[int(np.argmax(counts))]), csv_path=csv_path.relative_to(self.root).as_posix(), raw_path=raw_path.relative_to(self.root).as_posix() if raw is not None else "")
        with self.manifest.open("a", encoding="utf-8", newline="") as stream:
            row.update(schema_version=3,distance_cm=self.distance_cm,sample_kind=self.sample_kind,
                       illumination=self.illumination,experiment_round=self.experiment_round)
            csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS).writerow(row)
        return csv_path


class Controller:
    def __init__(self, config):
        self.config, self.store = config, DataStore()
        self.lock, self.model_lock = threading.RLock(), threading.RLock()
        self.stop_event = threading.Event()
        self.logs = deque(maxlen=160)
        self.sequence, self.process, self.model_source = 0, None, "board"
        self.job = {"kind": None, "status": "idle", "completed": 0, "target": 0, "message": "准备就绪"}
        self.latest, self.frame_cache, self.model_cache = None, None, None
        # 未勾选保存的真实帧只保留最近4帧内存副本，供绘图/手动下载，绝不落盘。
        self.memory_frames = OrderedDict()
        self.frame_contexts = OrderedDict()
        self.range_calibration = LiveRangeCalibration(WEB/'runtime/ranging')
        # 只缓存轻量结果，不在高频状态轮询中重复传输完整直方图。
        self.capture_records = deque(maxlen=128)
        self.capture_cursor, self.capture_total = 0, 0
        self.capture_job_id, self.capture_last_ready = None, None
        self.demo_displayed_id=None
        # 对比只缓存最多4帧计数。状态轮询只返回摘要，曲线通过独立接口读取。
        self.comparison, self.comparison_frames = None, []
        self.pl = PlRuntime(PROJECT / "overlays" / "tdc_pynq.bit")
        self.registry = ModelRegistry(PROJECT / "models")
        self.charts = TrainingCharts(self.registry, self.active, PROJECT)
        self.inference_backend = "cpu"
        if self.registry.active_id() and self.registry.info()["algorithm"] not in ALGORITHMS:
            supported = [item for item in self.registry.catalog() if not item["retired"]]
            if supported:
                self.registry.activate(supported[0]["id"])
            else:
                from model_registry import write_json
                write_json(self.registry.root / "active.json", {"model_id":None})
            self.log("该模型类型已停用，历史版本保留供查看或删除")
        self.log("P4 网页已启动；CPU历史演示可直接运行，内部采集需先加载Overlay")

    def log(self, message):
        with self.lock:
            self.sequence += 1
            self.logs.append({"id": self.sequence, "time": time.strftime("%H:%M:%S"), "message": str(message)})
        print(message, flush=True)

    def update(self, **values):
        with self.lock:
            self.job.update(values)

    def active(self):
        return self.job["status"] in ("running", "stopping")

    def memory_frame(self, value):
        if not str(value).startswith("memory/"):
            return None
        with self.lock:
            cached = self.memory_frames.get(str(value))
        if cached is None:
            raise ValueError("这帧临时数据已过期，请查看最新帧")
        return cached

    def resolve_frame(self, value):
        if self.memory_frame(value) is not None:
            return PROJECT / value  # 虚拟路径只用于标识，不能创建文件或目录。
        return self.store.resolve_frame(value)

    def read_frame(self, path):
        cached = self.memory_frame(path.relative_to(PROJECT).as_posix())
        if cached is not None:
            counts, _ = cached
            return np.arange(len(counts), dtype=np.uint32), counts, None
        return self.store.read(path)

    def prepare_download(self, value):
        cached = self.memory_frame(value)
        if cached is None:
            path = self.store.resolve_frame(value)
            if path.suffix.lower() == ".csv":
                return str(path), path.name
            _, counts, _ = self.store.read(path)
            name = path.with_suffix(".csv").name
        else:
            counts, _ = cached
            name = "frame.csv"
        text = io.StringIO()
        np.savetxt(text, np.column_stack([np.arange(len(counts)), counts]), fmt="%d",
                   delimiter=",", header="bin_index,count", comments="")
        return io.BytesIO(text.getvalue().encode("utf-8")), name

    def network(self):
        addresses = local_addresses()
        ready = any(item["ip"] == self.config["local_ip"] for item in addresses)
        return {"addresses": addresses, "ready": True, "legacy_udp_ready": ready, "receive_ip": self.config["local_ip"], "tdc_ip": self.config["tdc_ip"], "port": self.config["local_port"], "transport":"内部AXI，不需要 .2 接收地址"}

    def hardware(self, action):
        with self.lock:
            if self.active():
                raise BusyError("请先停止当前任务")
            if action == "load":
                self.pl.load()
                self.range_calibration.clear()
                self.log("Overlay已加载；默认在实际采集期间使能TDC，历史回放无需外部输入")
            elif action == 'attach':
                self.pl.load(reuse_loaded=True)
                self.log('已接管本项目已加载Overlay，未重新下载，持续输出设置保持不变')
            elif action in ("cpu", "pl"):
                if action == "pl":
                    if self.pl.overlay is None:
                        raise ValueError("请先加载Overlay")
                    self.validate_pl_model(self.model_path())
                if action != self.inference_backend:
                    self.release_models()
                self.inference_backend = action
                self.log("推理方式：{}".format("PL特征提取和分类器" if action=="pl" else "PS CPU"))
            else:
                raise ValueError("硬件操作无效")
            return dict(self.pl.status(), inference_backend=self.inference_backend)

    def outputs(self, options):
        """开关独立于采集任务；修改参数则与任务互斥，避免同一帧中途改变条件。"""
        if options.get("action") == "defaults":
            with self.lock:
                if self.active():
                    raise BusyError("请先停止当前任务，再恢复默认参数")
                result = self.pl.restore_defaults()
                self.log("本页参数已恢复默认：输出关闭、内部参考、100 kHz，探测开启9000 ns/持续2000 ns；两路高电平正向码1023、阈值0.300 V")
                return result
        if options.get("action") == "thresholds":
            with self.lock:
                if self.active():
                    raise BusyError("请先停止当前任务，再修改比较器阈值")
                result = self.pl.configure_thresholds(options)
                values = result["thresholds"]
                self.log("前端阈值已发送：A={:.3f} V，B={:.3f} V".format(
                    values["threshold_a_v"], values["threshold_b_v"]))
                return result
        if options.get("action") == "enable":
            result = self.pl.enable_outputs(options.get("enabled"))
            self.log("连续信号输出已{}".format("开启" if result["enabled"] else "关闭"))
            return result
        if options.get("action") == "configure":
            if options.get("timing_schema") != TIMING_SCHEMA:
                raise ValueError("输出参数定义已更新，请强制刷新网页；门控参数现在表示低电平探测开启窗口")
            with self.lock:
                if self.active():
                    raise BusyError("请先停止采集或训练，再修改输出参数；关闭输出仍可使用")
                result = self.pl.configure_outputs(options)
                self.log("输出参数已生效：{:.6g} kHz；激光相位/高电平时长 {:.3f}/{:.3f} ns；探测开启相位/低电平时长 {:.3f}/{:.3f} ns（允许跨周期）".format(
                    *[result["actual"][key] for key in ("frequency_khz", "laser_delay_ns", "laser_width_ns", "gate_delay_ns", "gate_width_ns")]))
                return result
        if options.get("action") == "reference":
            with self.lock:
                if self.active():
                    raise BusyError("请先停止当前任务，再切换参考源")
                result = self.pl.set_reference(options.get("source"))
                self.log("TDC参考源已切换为{}".format("DAC1内部回接" if result["reference_source"] == "internal" else "外部LVDS输入（B3/A3）"))
                return result
        raise ValueError("输出控制操作无效")

    def delete_run(self, collection, run_id):
        with self.lock:
            if self.active():
                raise BusyError("请先停止当前任务，再删除采集批次")
            record = self.store.delete_run(collection, run_id)
            prefix = record["original"] + "/"
            if self.latest and self.latest["path"].startswith(prefix):
                self.latest = self.frame_cache = None
            if self.comparison and any(row["path"].startswith(prefix) for row in self.comparison["frames"]):
                self.comparison, self.comparison_frames = None, []
            self.log("已永久删除批次 {}；重新训练后模型才会排除该批数据".format(record["original"]))
            return record

    def model_path(self):
        return self.registry.path()

    def model_info(self):
        try:
            return dict(self.registry.info(), available=True)
        except (OSError, ValueError, KeyError):
            return {"available": False, "source": self.model_source, "classes": []}

    def model_catalog(self):
        return {"models": self.registry.catalog(), "active_model_id": self.registry.active_id(),
                "algorithms": [dict(item, key=key) for key, item in ALGORITHMS.items()]}

    def release_models(self):
        """任务空闲后调用；只释放参数，不释放公共直方图和Overlay。"""
        with self.model_lock:
            self.pl.release_model()
            self.model_cache = None
            gc.collect()

    def model_memory(self):
        cache, buffer, metadata = self.model_cache, self.pl.model_buffer, self.pl.metadata
        return {"ps_model_loaded": cache is not None, "pl_model_loaded": buffer is not None,
                "pl_parameter_bytes": int(buffer.nbytes) if buffer is not None else 0,
                "loaded_model_id": cache[1].get("model_id") if cache else metadata.get("model_id") if metadata else None}

    def artifact(self, path=None):
        with self.model_lock:
            path = self.model_path() if path is None else Path(path)
            report = path.with_suffix(".report.json")
            stats = report.stat()
            key = (str(path), stats.st_mtime_ns, stats.st_size)
            if self.model_cache is None or self.model_cache[0] != key:
                self.pl.release_model()
                self.model_cache = None
                gc.collect()
                self.model_cache = (key, inference.load_model(path, "auto"))
            return self.model_cache[1]

    def select_model(self, model_id):
        with self.lock:
            if self.active():
                raise BusyError("请先停止当前任务，再切换模型")
            if model_id == "board":  # 兼容尚未刷新的旧网页；不重新加载任何模型。
                model_id = self.registry.active_id()
            info = self.registry.info(model_id)
            if info["algorithm"] not in ALGORITHMS:
                raise ValueError("该模型类型已停用，该历史版本可查看或删除")
            if self.inference_backend == "pl" and not info["pl_compatible"]:
                raise ValueError("该版本超过PL容量，请先切到PS推理")
            self.release_models()
            self.registry.activate(info["id"])
        self.log("已切换模型：{}（{}）；旧参数已释放，新参数按需加载".format(info["name"], info["algorithm_name"]))

    def delete_model(self, model_id):
        with self.lock:
            if self.active():
                raise BusyError("请先停止当前任务，再删除模型版本")
            # 活动版本仍由版本库拒绝删除；先停止非活动版本的后台绘图。
            if model_id == self.registry.active_id():
                raise ValueError("当前识别模型不能删除，请先切换其他模型")
            self.registry.info(model_id)
            self.charts.cancel_model(model_id)
            record = self.registry.delete(model_id)
            self.log("已永久删除模型版本 {}；公共数据集保留".format(model_id))
            return record

    def snapshot(self, after_frame=0, capture_job=None):
        indexed = self.store.status_index()
        with self.lock:
            job, logs, latest, comparison = dict(self.job), list(self.logs), self.latest, self.comparison
            if capture_job != self.capture_job_id or after_frame > self.capture_cursor:
                after_frame = 0
            history = {"job_id": self.capture_job_id, "cursor": self.capture_cursor, "total": self.capture_total,
                       "frames": [row for row in self.capture_records if row["id"] > after_frame]}
        return {"job": job, "logs": logs, "latest": latest, "comparison": comparison, "capture_history": history, "model": self.model_info(), "model_memory": self.model_memory(), "range_calibration":dict(self.range_calibration.summary(),current_signature=timing_signature(dict(self.config,output_settings=self.pl.output_status()))), "network": self.network(), "hardware":dict(self.pl.status(), inference_backend=self.inference_backend), "dataset": {key: indexed[key] for key in ("frame_count", "specimen_count", "materials", "counts", "training_frame_count", "training_materials")}, "config": {key: self.config[key] for key in ("trig_freq_hz", "trig_num", "bin_num", "bin_width", "local_ip", "tdc_ip")}}

    def start(self, kind, options):
        if kind not in ("capture", "train", "recognize", "compare", "range_point"):
            raise ValueError("任务类型不正确")
        if kind == 'range_point':
            if self.pl.overlay is None:raise ValueError('请先加载本项目Overlay')
            distance=parse_distance(options.get('distance_cm'))
            if distance is None:raise ValueError('请输入样品实际距离')
            options['distance_cm']=distance
            options['mode']='multi'
            options['frames']=10
            self.range_calibration.check_context(self.frame_context(PROJECT/'memory/calibration','pl'))
        elif kind == "capture":
            source = options.get("source", "history")
            if source not in ("history", "pl"):
                raise ValueError("采集来源不正确")
            if source == "pl" and self.pl.overlay is None:
                raise ValueError("请先加载本项目Overlay，再启动内部采集")
            options["frames"] = bounded_int(options.get("frames", 10), 1, 1000, "帧数")
            options["interval_s"] = float(options.get("interval_s", 0))
            if not np.isfinite(options["interval_s"]) or not 0 <= options["interval_s"] <= 60:
                raise ValueError("额外帧间等待应在 0–60 秒之间")
            save_data = options.get("save_data", False)
            if not isinstance(save_data, bool):
                raise ValueError("save_data必须为布尔值")
            options["save_data"] = source == "pl" and save_data
            if options["save_data"]:
                options["material"] = identifier(str(options.get("material") or "").strip() or "unlabeled", "材质编号")
                options["specimen"] = identifier(str(options.get("specimen") or "").strip() or "sample_01", "实物编号")
                options['distance_cm'] = parse_distance(options.get('distance_cm'))
                options['illumination']=illumination(options.get('illumination'))
                options['experiment_round']=identifier(options.get('experiment_round') or 'round_01','实验轮次')
                if options.get('sample_kind','material') not in ('material','blocked_background','empty_background'):
                    raise ValueError('采集类型不正确')
                options['sample_kind'] = sample_kind(options)
                if options['sample_kind'] != 'material': options['material'] = 'bgm'
            else:
                options.pop("material", None)
                options.pop("specimen", None)
            options.pop("save_training", None)
        elif kind == "train":
            options["algorithm"] = options.get("algorithm", "random_forest")
            if options["algorithm"] not in ALGORITHMS:
                raise ValueError("训练算法不正确")
            options["trees"] = bounded_int(options.get("trees", 32), 1, 128, "树数")
            if options["algorithm"] == "decision_tree":
                options["trees"] = 1
            options["max_depth"] = bounded_int(options.get("max_depth", 8), 1, 16, "最大深度")
            options["name"] = str(options.get("name", "")).strip()
            if len(options["name"]) > 80:
                raise ValueError("模型名称不能超过80个字符")
            options["activate"] = options.get("activate", True)
            if not isinstance(options["activate"], bool):
                raise ValueError("activate必须为布尔值")
            allowed = {item["run_key"] for item in self.store.index()["frames"] if material_row(item)}
            selected = options.get("run_keys", sorted(allowed))
            if not isinstance(selected, list) or not selected or not all(isinstance(key, str) for key in selected):
                raise ValueError("请至少选择一个有标签的采集批次")
            if set(selected) - allowed:
                raise ValueError("所选批次不存在或没有带材质标签的数据，请刷新列表")
            options["run_keys"] = sorted(set(selected))
            if not isinstance(options.get('tune',False),bool):raise ValueError('tune必须为布尔值')
        elif kind == "compare":
            paths = options.get("paths")
            if not isinstance(paths, list) or not 1 <= len(paths) <= 4 or not all(isinstance(path, str) for path in paths):
                raise ValueError("请选择1至4帧进行对比")
            paths = [self.resolve_frame(path).relative_to(PROJECT).as_posix() for path in paths]
            if len(set(paths)) != len(paths):
                raise ValueError("对比列表不能重复选择同一帧")
            if not isinstance(options.get("recognize", False), bool):
                raise ValueError("recognize必须为布尔值")
            options.update(paths=paths, frames=len(paths), continuous=False)
        else:
            self.resolve_frame(options.get("path", ""))
        with self.lock:
            if self.active():
                raise BusyError("已有任务运行，请等待完成或点击停止")
            self.stop_event.clear()
            self.job = {"id": uuid.uuid4().hex[:10], "kind": kind, "status": "running", "completed": 0, "target": 0 if options.get("continuous") else options.get("frames", 1), "message": "任务启动中", "started_at": time.time()}
            if kind == "capture":
                self.capture_records.clear()
                self.capture_job_id, self.capture_total, self.capture_last_ready = self.job["id"], 0, None
            threading.Thread(target=self._run, args=(kind, dict(options), self.job["id"]), daemon=True).start()
            return dict(self.job)

    def _run(self, kind, options, job_id):
        try:
            getattr(self, "_" + kind)(options)
            if self.stop_event.is_set():
                raise Cancelled()
            self.update(status="done", message="模型训练完成，图表按需生成" if kind == "train" else "任务完成", finished_at=time.time())
            self.log("任务完成")
        except Cancelled:
            self.update(status="cancelled", message="已停止，已保存的完整帧保留", finished_at=time.time())
            self.log("任务已停止")
        except Exception as error:
            self.update(status="error", message=str(error), finished_at=time.time())
            self.log("任务失败：{}".format(error))
        finally:
            with self.lock:
                if self.job.get("id") == job_id:
                    self.process = None

    def stop(self):
        with self.lock:
            if self.active():
                if self.job.get("kind") == "train" and self.job.get("model_committed"):
                    return  # 新版本已经原子提交，等待任务完成状态发布。
                self.stop_event.set()
                self.job.update(status="stopping", message="正在停止任务")
                if self.process is not None and self.process.poll() is None:
                    self.process.terminate()
                self.log("收到停止请求")

    def check_stop(self):
        if self.stop_event.is_set():
            raise Cancelled()

    def recognize_counts(self, counts, path, source=None):
        """对同一份内存计数计时，排除采集、文件读取、网络和网页刷新。"""
        started = time.perf_counter()
        info = self.model_info()
        model_path = self.model_path() if self.inference_backend=='pl' else None
        context = self.frame_context(path,source)
        if self.inference_backend == "pl":
            if self.model_cache is not None:
                self.model_cache = None
                gc.collect()
            expected = [self.config["bin_num"], 2**self.config["bin_width"], self.config["trig_num"]] if source=="pl" else None
            result = self.pl.infer(counts, model_path.with_suffix(".portable.json"), captured=source=="pl", acquisition_settings=expected)
            # 驱动原有耗时是启动加速器到完成的PS侧观测时间，含寄存器轮询，
            # 不冒充精确的PL时钟周期。总耗时还要计入准备模型及PS/PL数据搬运。
            result["compute_ms"] = result["elapsed_ms"]
        else:
            artifact = self.artifact()
            if len(counts) != artifact["settings"][0]:
                raise ValueError("该帧 bin 数与模型不一致")
            compute_started = time.perf_counter()
            features, peaks = training.extract_features(counts)
            sample=inference.model_sample(artifact,counts,features,peaks)
            scores = inference.class_scores(artifact["model"], sample)[0]
            classes = artifact["model"].classes_
            # SVM按决策间隔分类，避免softmax舍入后的并列分数改变类别。
            material = str(classes[int(np.argmax(scores))])
            compute_ms = (time.perf_counter() - compute_started) * 1000
            result = {"material": material, "reference_bin": int(peaks["reference_bin"]), "return_bin": int(peaks["return_bin"]), "class_scores": {str(name): round(float(score), 4) for name, score in zip(classes, scores)}, "model_id": artifact["model_id"], "backend": artifact["backend"], "compute_ms": round(compute_ms, 3)}
            result['peak_shift_bins']=float(features[8]-artifact.get('timing_reference_bin',0)) if len(artifact.get('feature_names',[]))==9 else None
        result["score_kind"] = "model_probability"
        result['valid_signal']=True
        # 现场测距只用于显示；材质分类不再按距离选择子模型。
        correction=self._frame_range_profile(path,source)
        if correction:
            from ranging import estimate
            try:result.update(estimated_distance_cm=round(estimate(correction,result['return_bin'],**context),3),range_correction_applied=True)
            except ValueError as error:result['distance_warning']=str(error)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    @staticmethod
    def validate_pl_model(path):
        portable=Path(path).with_suffix('.portable.json')
        pack_model(portable)

    def frame_context(self,path,source=None):
        if source=='pl':
            config=dict(self.config,output_settings=self.pl.output_status())
        elif str(path) in self.frame_contexts:
            config=self.frame_contexts[str(path)]
        else:
            saved=Path(path).parent.parent/'config.json'
            if not saved.is_file():return {}
            config=load_json(saved)
        return dict(bin_width_ps=2**int(config['bin_width']),signature=timing_signature(config))

    def _frame_range_profile(self,path,source=None,model_id=None):
        if source=='pl':return self.range_calibration.profile()
        config=self.frame_contexts.get(str(path))
        if config is None:
            saved=Path(path).parent.parent/'config.json'
            config=load_json(saved)if saved.is_file()else{}
        profile=config.get('range_correction')
        from ranging import profile_applies_to_model
        return profile if profile_applies_to_model(profile,model_id)else None

    def range_action(self,options):
        with self.lock:
            if self.active():raise BusyError('请先停止当前任务')
            action=options.get('action')
            if action=='delete_point':
                point=self.range_calibration.delete_point(options.get('point_id'))
                self.log('已删除校准点：{:.3f} cm；如影响已应用拟合，需重新应用'.format(point['distance_cm']))
            elif action=='apply_multi':
                context=self.frame_context(PROJECT/'memory/unused','pl')
                points=self.range_calibration.summary()['points']
                if any(p['signature']!=context.get('signature')or p['bin_width_ps']!=context.get('bin_width_ps')for p in points):
                    raise ValueError('采集配置已改变，请清空校准点并重新采集')
                profile=self.range_calibration.apply_multi()
                self.log('多点测距校准已应用：{}个点，拟合MAE {:.3f} cm（不是独立验证精度）'.format(len(profile['points']),profile['fit_mae_cm']))
            else:raise ValueError('测距校准操作无效')
            return self.range_calibration.summary()

    def _range_point(self,options):
        """连续采10个完整帧形成一点；失败/取消不提交部分校准点。"""
        self.range_calibration.check_context(self.frame_context(PROJECT/'memory/calibration','pl'))
        before=self.pl.output_status();temporary=not before['enabled']
        if before.get('busy')or before.get('levels_pending')or before.get('reference_pending')or before.get('thresholds',{}).get('busy'):
            raise ValueError('输出参数尚未稳定，请稍后再采集校准点')
        try:
            if temporary:self.pl.enable_outputs(True)
            context=self.frame_context(PROJECT/'memory/calibration','pl')
            frames=[]
            for i in range(10):
                self.check_stop();self.update(message='采集校准点：第 {}/10 帧'.format(i+1),target=10)
                counts=self.pl.collect(self.config,self.stop_event);self.check_stop()
                if context!=self.frame_context(PROJECT/'memory/calibration','pl'):raise ValueError('采集期间配置发生变化，请重新采集该点')
                frames.append(counts.copy());self.update(completed=i+1)
            point=self.range_calibration.capture_group(frames,options['distance_cm'],context)
            self.log('校准点已保存：{:.3f} cm，10帧回波峰中位数{}'.format(point['distance_cm'],point['return_bin']))
        finally:
            if temporary:self.pl.enable_outputs(False)

    def publish_frame(self, path, bins, counts, source, frame_index, truth=None, packets=None, recognize=True, timing=None, frame_started=None):
        if source=='pl':
            self.frame_contexts[str(path)]=dict(self.config,output_settings=self.pl.output_status(),range_correction=self.range_calibration.profile())
            while len(self.frame_contexts)>4:self.frame_contexts.popitem(last=False)
        infer_started = time.perf_counter()
        result, error = None, None
        try:
            if recognize:
                result = self.recognize_counts(counts, path, source)
        except Exception as exception:
            error = str(exception)
            self.log("识别失败：{}".format(error))
        # 每次发布都有独立标识。同一文件、同一模型可能得到完全相同的结果，
        # 网页仍需知道这是本次重新计算的结果，不能按结果内容去重。
        payload = {"result_id": uuid.uuid4().hex, "path": path.relative_to(PROJECT).as_posix(), "source": source, "frame_index": frame_index, "total_counts": int(counts.sum()), "bin_num": len(counts), "result": result, "error": error, "truth": truth, "packets": packets}
        payload["saved"] = not payload["path"].startswith("memory/")
        cached_counts = counts.copy()
        ready = time.perf_counter()
        if timing is not None:
            measured = dict(timing)
            measured["inference_ms"] = round(result.get("elapsed_ms", (ready - infer_started) * 1000) if result else (ready - infer_started) * 1000, 3) if recognize else 0.0
            measured["frame_total_ms"] = round((ready - frame_started) * 1000, 3)
            measured["interval_ms"] = round((ready - self.capture_last_ready) * 1000, 3) if self.capture_last_ready is not None else None
            payload["timing"] = measured
        with self.lock:
            self.latest = payload
            self.frame_cache = (str(path), cached_counts, result)
            if not payload["saved"]:
                self.memory_frames[payload["path"]] = (self.frame_cache[1], result)
                self.memory_frames.move_to_end(payload["path"])
                while len(self.memory_frames) > 4:
                    self.memory_frames.popitem(last=False)
            if timing is not None:
                self.capture_cursor += 1
                self.capture_total += 1
                self.capture_last_ready = ready
                self.capture_records.append({"id": self.capture_cursor, "frame_index": frame_index,
                    "material": result["material"] if result else None, "saved": payload["saved"] and source == "pl",
                    "source": source, "error": error, "timing": measured})
        if result:
            self.log("第 {} 帧识别：材质={}，回波峰={}，模型={}".format(frame_index, result["material"], result["return_bin"], result["model_id"]))
        return payload

    def _recognize(self, options):
        path = self.resolve_frame(options["path"])
        self.update(message="读取并识别单帧")
        bins, counts, raw = self.read_frame(path)
        self.check_stop()
        result = self.publish_frame(path, bins, counts, "file", 1)
        if result["error"]:
            raise ValueError(result["error"])
        self.update(completed=1)

    def _compare(self, options):
        """串行读取/推理，分别保留各帧结果；不写入训练集，也不覆盖单帧结果。"""
        recognize = options.get("recognize", False)
        with self.lock:
            self.comparison = {"id": self.job["id"], "recognize": recognize,
                               "backend": self.inference_backend, "frames": []}
            self.comparison_frames = []
        self.log("开始{}，共{}帧".format("识别并对比" if recognize else "波形对比", len(options["paths"])))
        for index, value in enumerate(options["paths"], 1):
            self.check_stop()
            row = {"path": value, "result": None, "error": None, "total_counts": None,
                   "reference_bin": None, "return_bin": None}
            counts = None
            try:
                path = self.resolve_frame(value)
                _, counts, _ = self.read_frame(path)
                row["total_counts"] = int(counts.sum())
                if recognize:
                    # 与单帧识别共用同一PS/PL入口；PL始终一帧完成后再写下一帧RAM。
                    result = self.recognize_counts(counts, path)
                    row["result"] = result
                    row.update(reference_bin=result["reference_bin"], return_bin=result["return_bin"])
                # 展示指标独立于分类结果，不用当前模型基线，也不改写原始计数。
                # 只对最多4帧计算；识别计时仍由原推理入口负责。
                try:
                    features, peaks = training.extract_features(counts)
                    if not recognize:
                        row.update(reference_bin=int(peaks['reference_bin']),return_bin=int(peaks['return_bin']))
                    if features is not None:
                        row['metrics'] = dict(return_bin=int(peaks['return_bin']),
                            peak_gap_bins=int(peaks['return_bin']-peaks['reference_bin']),
                            area_ratio=float(features[1]),peak_ratio=float(features[2]),
                            half_width_bins=float(features[5]),weighted_sigma_bins=float(features[6]))
                except ValueError:
                    row['metrics'] = None
            except Exception as error:
                row["error"] = str(error)
                self.log("对比第{}帧失败：{}".format(index, error))
            with self.lock:
                # 每次替换摘要对象，避免Flask序列化时另一个线程修改同一列表。
                self.comparison = dict(self.comparison, frames=self.comparison["frames"] + [row])
                self.comparison_frames = self.comparison_frames + [counts]
            self.update(completed=index, message="对比已处理 {} / {} 帧".format(index, len(options["paths"])))

    @staticmethod
    def _plot_points(counts, left, right):
        """分组保留真实最大点，既限制网页数据量，也避免把窄峰平均掉。"""
        step = max(1, int(np.ceil((right - left) / 1800.0)))
        stop = min(right, len(counts))
        size = max(0, stop - left)
        complete = (size // step) * step
        groups = np.asarray(counts[left:left + complete]).reshape(-1, step)
        positions = left + np.arange(groups.shape[0]) * step + np.argmax(groups, axis=1)
        if complete < size:
            positions = np.append(positions, left + complete + int(np.argmax(counts[left + complete:stop])))
        return positions.tolist(), np.asarray(counts)[positions].astype(float).tolist()

    def comparison_plot(self, view):
        """所有曲线采用同一个坐标范围，回波视图覆盖各帧回波峰，便于比较偏移。"""
        if view not in ("full", "echo"):
            raise ValueError("图表范围无效")
        with self.lock:
            comparison, cached = self.comparison, list(self.comparison_frames)
        if comparison is None or not comparison["frames"]:
            raise ValueError("请先选择文件并开始对比")
        available = [(index, row, counts) for index, (row, counts) in enumerate(zip(comparison["frames"], cached)) if counts is not None]
        if not available:
            raise ValueError("没有可展示的有效直方图，请查看逐帧错误信息")
        left, right = 0, max(len(counts) for _, _, counts in available)
        if view == "echo":
            peaks = [row["return_bin"] for _, row, _ in available if row["return_bin"] is not None]
            if not peaks:
                raise ValueError("未找到有效回波峰，请切换到完整波形")
            left, right = max(0, min(peaks) - 800), min(right, max(peaks) + 801)
        curves = []
        for index, row, counts in available:
            x, y = self._plot_points(counts, left, right)
            curves.append(dict(path=row["path"], index=index, x=x, y=y))
        maximum = max((max(curve["y"]) for curve in curves if curve["y"]), default=0)
        return {"id": comparison["id"], "view": view, "curves": curves,
                "x_min": left, "x_max": right - 1, "y_max": 500 if view == "full" else max(10, maximum * 1.15)}

    def _capture(self, options):
        """真实采集走片内AXI；历史演示只读取已有帧，不再经过外部UDP。"""
        source, target = options.get("source", "history"), options["frames"]
        continuous = bool(options.get("continuous"))
        recognize = bool(options.get("recognize", True))
        indexed = self.store.index() if source == "history" else None
        writer = None
        if source == "history" and not indexed["frames"]:
            raise ValueError("数据集中没有可演示的历史帧")
        save_data = source == "pl" and options.get("save_data", False)
        if save_data:
            material = identifier(options.get("material") or "unlabeled", "材质编号")
            specimen = identifier(options.get("specimen") or "sample_01", "实物编号")
            metadata = dict(options, output_settings=self.pl.output_status())
            metadata['range_correction']=self.range_calibration.profile()
        if source == "pl":
            self.log("保存采集数据：{}".format("开启，完整帧按批次保存" if save_data else "关闭，仅在内存中保留最近4帧"))
        self.log("{}，{}".format("历史数据演示" if source=="history" else "内部AXI真实采集", "连续运行直到停止" if continuous else "目标 {} 帧".format(target)))
        count = 0
        while continuous or count < target:
            self.check_stop()
            frame_started = time.perf_counter()
            timing = {"acquire_ms": 0.0, "read_ms": 0.0, "file_read_ms": 0.0,
                      "save_ms": 0.0, "extra_wait_ms": options["interval_s"] * 1000}
            count += 1
            truth = None
            if source == "history":
                material = random.choice(indexed["materials"])
                item = random.choice([row for row in indexed["frames"] if row["material"]==material])
                path = self.store.resolve_frame(item["path"])
                read_started = time.perf_counter()
                bins, counts, raw = self.store.read(path)
                timing["file_read_ms"] = round((time.perf_counter() - read_started) * 1000, 3)
                truth = item["material"]
            else:
                self.update(message="内部AXI采集第 {} 帧".format(count))
                collect_started = time.perf_counter()
                counts = self.pl.collect(self.config, self.stop_event)
                timing.update(self.pl.last_capture_timing or {"acquire_ms": round((time.perf_counter() - collect_started) * 1000, 3)})
                bins = np.arange(65536, dtype=np.uint32)
                if save_data:
                    save_started = time.perf_counter()
                    # 收到第一帧完整数据才创建批次，失败/取消不会留下空批次。
                    if writer is None:
                        writer = FrameWriter(material, specimen, self.config, source, metadata)
                    path = writer.save(count, bins, counts, None)
                    # 当前批次已落盘后更新缓存，其他批次复用已有索引。
                    self.store.index()
                    timing["save_ms"] = round((time.perf_counter() - save_started) * 1000, 3)
                else:
                    path = PROJECT / "memory" / ("frame_" + uuid.uuid4().hex + ".csv")
            published=self.publish_frame(path, bins, counts, source, count, truth=truth, recognize=recognize,
                               timing=timing, frame_started=frame_started)
            self.update(completed=count, message="已完成 {} 帧{}".format(count, "，已保存" if writer else "，未保存" if source == "pl" else ""), saved_run=writer.root.relative_to(PROJECT).as_posix() if writer else None)
            if source=='history' and (continuous or target>1):
                # 仅历史演示节流：真实PL采集仍保持用户原设定的速度。
                # 浏览器画完当前帧后确认；没有浏览器时最多等待3秒，避免永久挂起。
                began=time.monotonic();minimum=max(1.0,options['interval_s'])
                while True:
                    elapsed=time.monotonic()-began
                    shown=not options.get('demo_sync',False) or self.demo_displayed_id==published['result_id']
                    if elapsed>=minimum and (shown or elapsed>=max(3.0,minimum)):break
                    if self.stop_event.wait(.05):raise Cancelled()
            elif (continuous or count < target) and self.stop_event.wait(options["interval_s"]):
                raise Cancelled()

    def acknowledge_demo(self,result_id):
        """只确认当前历史帧；过期/其他任务的确认不会放行新帧。"""
        with self.lock:
            if self.latest and self.latest.get('source')=='history' and self.latest.get('result_id')==result_id:
                self.demo_displayed_id=result_id

    def _train(self, options):
        """子进程只读公共数据集，成功后归档新版本，不覆盖其他版本。"""
        started = time.perf_counter()
        self.release_models()
        staging = WEB / "runtime" / ("train_" + uuid.uuid4().hex[:10])
        staging.mkdir()
        selection = staging / "training_runs.json"
        selection.write_text(json.dumps({"run_keys": options["run_keys"]}), encoding="utf-8")
        command = [sys.executable, "-u", str(PROJECT / "train_material.py"), "--dataset", str(PROJECT / "dataset"), "--model", str(staging / "material_model.joblib"), "--algorithm", options["algorithm"], "--runs-file", str(selection), "--trees", str(options["trees"]), "--max-depth", str(options["max_depth"]), "--prefer-raw", "--no-open", "--no-figures"]
        if options.get('tune'):command.append('--tune')
        self.update(message="读取所选批次并训练" + ALGORITHMS[options["algorithm"]]["name"], target=0)
        description = "9→32→16→类别，ReLU" if options["algorithm"] == "mlp" else "256点回波→4通道卷积→平均池化＋9维统计→8神经元→类别" if options["algorithm"] == "tiny_cnn" else "{}棵树，最大深度{}".format(options["trees"],options["max_depth"])
        self.log("开始训练{}：{}批次，{}".format(ALGORITHMS[options["algorithm"]]["name"],len(options["run_keys"]),description))
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND="Agg", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"))
        except Exception:
            shutil.rmtree(staging)
            raise
        with self.lock:
            self.process = process
        try:
            for line in process.stdout:
                if line.strip():
                    self.log(line.rstrip())
                    if line.startswith("正在生成"):
                        self.update(message=line.strip())
                if self.stop_event.is_set() and process.poll() is None:
                    process.terminate()
            status = process.wait()
            self.check_stop()
            if status != 0:
                raise ValueError("训练未完成，原模型保留，请查看运行日志")
            inference.load_model(staging / "material_model.joblib", "auto")
            report = load_json(staging / "material_model.report.json")
            if report.get("pl_compatible", False):
                self.validate_pl_model(staging / "material_model.joblib")
            with self.lock, self.model_lock:
                self.check_stop()
                info = self.registry.register(staging, options["name"])
                if options["activate"] or self.registry.active_id() is None:
                    if self.inference_backend == "pl" and not info["pl_compatible"]:
                        self.log("新版本已保存，但超过PL容量，继续使用原版本")
                    else:
                        self.registry.activate(info["id"])
                self.job["model_committed"] = True
            self.update(completed=1, message="新模型已保存，可立即识别；图表按需生成", trained_model_id=info["id"],
                        model_ready_seconds=round(time.perf_counter() - started, 3))
            self.log("新版本{}已归档，共用原始数据集；未选版本不加载参数".format(info["id"]))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            # 仅清理本次创建且位于runtime直接子目录的临时文件。
            if staging.parent.resolve() == (WEB / "runtime").resolve() and not staging.is_symlink():
                shutil.rmtree(staging)

    def plot(self, path_value, view):
        memory = self.memory_frame(path_value)
        if memory is not None:
            counts, result = memory
        else:
            path = self.store.resolve_frame(path_value)
            with self.lock:
                cached = self.frame_cache
            if cached and cached[0] == str(path):
                counts, result = cached[1], cached[2]
            else:
                _, counts, _ = self.store.read(path)
                result = None
        if result is None:
            try:
                _, peaks = training.extract_features(counts)
                result = peaks
            except ValueError:
                result = None
        left, right = 0, len(counts)
        if view == "echo" and result and result.get('return_bin') is not None:
            center = result["return_bin"]
            left, right = max(0, center - 800), min(len(counts), center + 801)
        # 分组取真实最大点，保留窄峰高度；不把计数相加或取对数。
        x, y = self._plot_points(counts, left, right)
        return {"x": x, "y": y, "x_min": left, "x_max": right - 1, "y_max": 500 if view != "echo" else max(10, float(max(y)) * 1.15), "reference_bin": result.get("reference_bin") if result else None, "return_bin": result.get("return_bin") if result else None, "view": view}
