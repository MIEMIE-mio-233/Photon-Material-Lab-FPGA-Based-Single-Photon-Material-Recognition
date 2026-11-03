"""输出协议和批次删除的离线检查；只操作临时目录，不删除真实采集数据。"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "web")]
from output_settings import DEFAULTS, LEVEL_DEFAULTS, parse_settings, parse_levels, window_summary
from pl_runtime import PlRuntime
from threshold_settings import parse_thresholds
import services
import server


class FakeCapture:
    """只模拟输出寄存器握手，真实跨域和脉冲行为由RTL仿真核验。"""
    def __init__(self):
        self.regs = {0x40: 0, 0x5c: 0, 0x74: 0, 0x7c: 2, 0x88: 125000000,
                     0x80: 0x00660200, 0x84: 0x00660200, 0x90: 0x00660200, 0x94: 0x00660200,
                     0xac: 2, 0xb0: 300, 0xb4: 300, 0xb8: 0, 0xbc: (1174 << 16) | 1174}
        self.regs.update(zip((0x60, 0x64, 0x68, 0x6c, 0x70), (1250, 0, 625, 1100, 250)))

    def read(self, offset):
        return self.regs.get(offset, 0)

    def write(self, offset, value):
        self.regs[offset] = value
        if offset == 0xa8:
            a, b = self.regs.get(0xa0, 300), self.regs.get(0xa4, 300)
            self.regs.update({0xb0: a, 0xb4: b, 0xb8: self.regs[0xb8] + 1,
                              0xbc: (((b + 2048) // 2) << 16) | ((a + 2048) // 2), 0xac: 2})
        if offset == 0x44:
            for source, target in zip((0x48, 0x4c, 0x50, 0x54, 0x58), (0x60, 0x64, 0x68, 0x6c, 0x70)):
                self.regs[target] = self.regs[source]
            self.regs[0x74] += 1
        if offset == 0x78:
            self.regs[0x7c] = 2 | value
        if offset in (0x80, 0x84):
            self.regs[offset + 0x10] = value
        if offset == 0x40:
            self.regs[0x5c] = 9 if value else 0


class WebControls(unittest.TestCase):
    def test_binary_compatibility_and_vectorized_plot(self):
        """二进制与CSV保留相同计数和特征；向量绘图保持原来的分组最大点。"""
        np = services.np
        with tempfile.TemporaryDirectory(prefix="tdc_binary_test_") as temporary:
            root = Path(temporary)
            bins = np.arange(65536)
            counts = (2 + 5000 * np.exp(-((bins - 10500) / 4) ** 2) + 100 * np.exp(-((bins - 17500) / 80) ** 2)).astype("uint32")
            binary, csv = root / "frame.npy", root / "frame.csv"
            np.save(str(binary), counts, allow_pickle=False)
            np.savetxt(str(csv), np.column_stack([bins, counts]), fmt="%d", delimiter=",", header="bin_index,count", comments="")
            _, a = services.training.read_frame(binary); _, b = services.training.read_frame(csv)
            self.assertTrue(np.array_equal(a, b))
            self.assertTrue(np.array_equal(services.training.extract_features(a)[0], services.training.extract_features(b)[0]))
            for left, right in [(0, 65536), (16700, 18301), (65531, 65536)]:
                step = max(1, int(np.ceil((right - left) / 1800)))
                expected = [i + int(np.argmax(counts[i:min(i + step, right)])) for i in range(left, right, step)]
                x, y = services.Controller._plot_points(counts, left, right)
                self.assertEqual(x, expected); self.assertEqual(y, [float(counts[i]) for i in expected])
            np.save(str(binary), counts.astype("float64"), allow_pickle=False)
            with self.assertRaises(ValueError): services.training.read_frame(binary)

    def test_capture_save_choice_and_memory_frames(self):
        """不保存时不写文件；单/批量/连续采集沿用同一开关，临时帧仍可绘图下载。"""
        with tempfile.TemporaryDirectory(prefix="tdc_capture_save_test_") as temporary:
            project = Path(temporary)
            with patch.object(services, "PROJECT", project), patch.object(services, "WEB", project / "web"):
                controller = services.Controller(json.loads((ROOT / "web/config.json").read_text(encoding="utf-8")))
                controller.pl.overlay = object()
                result = {"material": "paper", "reference_bin": 1000, "return_bin": 2000,
                          "class_scores": {"paper": 1.0}, "model_id": "capture-test", "backend": "test"}
                calls = []
                def collect(*args):
                    calls.append(1)
                    return services.np.full(65536, len(calls), dtype="uint32")
                def wait_job(expected="done"):
                    deadline = time.monotonic() + 20
                    while controller.active() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(controller.job["status"], expected, controller.job)
                with patch.object(server, "controller", controller), patch.object(controller.pl, "collect", side_effect=collect) as acquisition, patch.object(controller.pl, "output_status", return_value={"enabled": False}), patch.object(controller, "recognize_counts", return_value=result) as predictor, patch.object(controller, "publish_frame", wraps=controller.publish_frame) as publisher:
                    client = server.app.test_client()
                    options = {"source": "pl", "frames": 6, "interval_s": 0, "save_data": False, "recognize": True, "material": "ignored/bad"}
                    self.assertEqual(client.post("/api/jobs/capture", json=dict(options, save_data="false")).status_code, 400)
                    self.assertEqual(client.post("/api/jobs/capture", json=options).status_code, 202)
                    wait_job()
                    self.assertEqual(predictor.call_count, 6)
                    self.assertEqual(len(controller.capture_records), 6)
                    with patch.object(controller.pl, "status", return_value={"loaded": True}):
                        history = client.get("/api/state").get_json()["capture_history"]
                        self.assertEqual(len(history["frames"]), 6)
                        incremental = client.get("/api/state", query_string={"capture_job": history["job_id"], "after_frame": history["cursor"]}).get_json()["capture_history"]
                        self.assertEqual(incremental["frames"], [])
                        reconnected = client.get("/api/state", query_string={"capture_job": "old-service", "after_frame": history["cursor"]}).get_json()["capture_history"]
                        self.assertEqual(len(reconnected["frames"]), 6)
                    self.assertEqual(controller.capture_records[-1]["timing"]["extra_wait_ms"], 0)
                    self.assertGreaterEqual(controller.latest["timing"]["frame_total_ms"], 0)
                    self.assertEqual(controller.store.index()["frame_count"], 0)
                    self.assertEqual(list(project.rglob("*.csv")), [])
                    self.assertEqual(list((project / "dataset").iterdir()), [])
                    self.assertFalse((project / "memory").exists())
                    self.assertEqual(len(controller.memory_frames), 4)
                    self.assertFalse(controller.latest["saved"])
                    self.assertIsNone(controller.job["saved_run"])
                    path = controller.latest["path"]
                    first = publisher.call_args_list[0].args[0].relative_to(project).as_posix()
                    self.assertEqual(client.get("/api/plot", query_string={"path": first}).status_code, 400)
                    plotted = client.get("/api/plot", query_string={"path": path}).get_json()
                    self.assertTrue(plotted["ok"]); self.assertEqual(plotted["y_max"], 500)
                    response = client.get("/api/frame/download", query_string={"path": path})
                    self.assertEqual(response.status_code, 200)
                    rows = services.np.loadtxt(services.io.BytesIO(response.data), delimiter=",", skiprows=1, dtype="uint32")
                    self.assertEqual(rows.shape, (65536, 2)); self.assertTrue((rows[:, 1] == 6).all())
                    response.close()
                    # 临时帧重复识别仍走模型，不能为了识别把它偷偷写入数据集。
                    self.assertEqual(client.post("/api/jobs/recognize", json={"path": path}).status_code, 202); wait_job()
                    self.assertEqual(list(project.rglob("*.csv")), [])
                    # 勾选后保存到同一个dataset，且只在第一帧采集成功后创建批次。
                    saved = dict(options, frames=2, save_data=True, material="paper", specimen="paper_01")
                    self.assertEqual(client.post("/api/jobs/capture", json=saved).status_code, 202); wait_job()
                    self.assertTrue(controller.latest["saved"])
                    self.assertEqual(controller.store.index()["frame_count"], 2)
                    self.assertEqual(controller.store.index()["training_frame_count"], 2)
                    self.assertEqual(controller.latest["path"].split(".")[-1], "npy")
                    self.assertEqual(len(list(project.rglob("frame_*.npy"))), 2)
                    downloaded = client.get("/api/frame/download", query_string={"path": controller.latest["path"]})
                    self.assertEqual(downloaded.status_code, 200); self.assertIn(b"bin_index,count", downloaded.data); downloaded.close()
                    self.assertEqual(len(list((project / "dataset").glob("run_*"))), 1)
                    acquisition.side_effect = ValueError("test acquisition failed")
                    self.assertEqual(client.post("/api/jobs/capture", json=saved).status_code, 202); wait_job("error")
                    self.assertEqual(len(list((project / "dataset").glob("run_*"))), 1)
                    # 连续采集取消后也不新增保存批次。
                    continuous_calls = []
                    def continuous_collect(*args):
                        continuous_calls.append(1)
                        if len(continuous_calls) == 3:
                            controller.stop_event.set()
                        return services.np.ones(65536, dtype="uint32")
                    acquisition.side_effect = continuous_collect
                    self.assertEqual(client.post("/api/jobs/capture", json=dict(options, continuous=True)).status_code, 202)
                    wait_job("cancelled")
                    self.assertEqual(controller.job["completed"], 3)
                    self.assertFalse(controller.latest["saved"])
                    self.assertEqual(controller.store.index()["frame_count"], 2)
                    # 没传save_data默认不保存，适用于单帧采集。
                    acquisition.side_effect = collect
                    default = dict(options, frames=1); default.pop("save_data")
                    self.assertEqual(client.post("/api/jobs/capture", json=default).status_code, 202); wait_job()
                    self.assertFalse(controller.latest["saved"])
                    self.assertEqual(controller.store.index()["frame_count"], 2)

    def test_cpu_and_pl_timing_scope(self):
        """总计时包含模型准备；计算计时覆盖特征及分类或PL启动至完成。"""
        with tempfile.TemporaryDirectory(prefix="tdc_timing_test_") as temporary:
            project = Path(temporary)
            with patch.object(services, "PROJECT", project), patch.object(services, "WEB", project / "web"):
                controller = services.Controller(json.loads((ROOT / "web/config.json").read_text(encoding="utf-8")))
                class CpuModel:
                    classes_ = services.np.array(["paper", "wood"])
                    def predict_proba(self, features):
                        time.sleep(0.002)
                        return services.np.array([[0.25, 0.75]])
                artifact = {"settings": [65536], "model": CpuModel(), "model_id": "timing-model", "backend": "test-cpu", "feature_version":services.training.FEATURE_VERSION,"feature_names":services.training.FEATURE_NAMES}
                def prepare_model():
                    time.sleep(0.004)
                    return artifact
                with patch.object(controller, "artifact", side_effect=prepare_model), patch.object(services.training, "extract_features", return_value=(services.np.zeros(9), {"reference_bin": 1000, "return_bin": 2000})):
                    result = controller.recognize_counts(services.np.ones(65536), project / "frame.csv")
                self.assertEqual(result["material"], "wood")
                self.assertGreaterEqual(result["compute_ms"], 1)
                self.assertGreater(result["elapsed_ms"] - result["compute_ms"], 2)
                controller.inference_backend = "pl"
                def pl_infer(*args, **kwargs):
                    time.sleep(0.004)
                    return {"material": "wood", "elapsed_ms": 1.234, "backend": "PL"}
                with patch.object(controller.pl, "infer", side_effect=pl_infer), patch.object(controller, "model_path", return_value=project / "models/material_model.joblib"):
                    result = controller.recognize_counts(services.np.ones(65536), project / "frame.csv")
                self.assertEqual(result["compute_ms"], 1.234)
                self.assertGreaterEqual(result["elapsed_ms"], 3)

    def test_repeated_single_frame_recognition(self):
        """同一帧连续请求三次：每次都推理，并发布不同标识供网页刷新。"""
        with tempfile.TemporaryDirectory(prefix="tdc_repeat_test_") as temporary:
            project = Path(temporary)
            with patch.object(services, "PROJECT", project), patch.object(services, "WEB", project / "web"):
                controller = services.Controller(json.loads((ROOT / "web/config.json").read_text(encoding="utf-8")))
                writer = services.FrameWriter("paper", "paper_01", controller.config, "pl", {})
                path = writer.save(1, services.np.arange(65536), services.np.ones(65536), None).relative_to(project).as_posix()
                identical_result = {"material": "paper", "reference_bin": 1, "return_bin": 6,
                                    "class_scores": {"paper": 1.0}, "model_id": "test-model", "backend": "test"}
                publications = []
                with patch.object(server, "controller", controller), patch.object(controller, "recognize_counts", return_value=identical_result) as predictor:
                    client = server.app.test_client()
                    for _ in range(3):
                        response = client.post("/api/jobs/recognize", json={"path": path})
                        self.assertEqual(response.status_code, 202)
                        deadline = time.monotonic() + 15
                        while controller.active() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertEqual(controller.job["status"], "done", controller.job)
                        publications.append(dict(controller.latest))
                self.assertEqual(predictor.call_count, 3)
                self.assertEqual(len({frame["result_id"] for frame in publications}), 3)
                self.assertTrue(all(frame["path"] == path and frame["result"] == identical_result for frame in publications))

    def test_unified_data_and_training_labels(self):
        """统一存储；训练只根据材质标签筛选，不依赖旧保存标志。"""
        with tempfile.TemporaryDirectory(prefix="tdc_catalog_test_") as temporary:
            project = Path(temporary)
            with patch.object(services, "PROJECT", project), patch.object(services, "WEB", project / "web"):
                controller = services.Controller(json.loads((ROOT / "web/config.json").read_text(encoding="utf-8")))
                labeled = services.FrameWriter("paper", "paper_01", controller.config, "pl", {})
                labeled.save(1, services.np.arange(8), services.np.ones(8), None)
                unlabeled = services.FrameWriter("unlabeled", "sample_01", controller.config, "pl", {})
                unlabeled.save(1, services.np.arange(8), services.np.ones(8), None)
                self.assertEqual(labeled.root.parent, unlabeled.root.parent)
                self.assertEqual(labeled.root.parent.name, "dataset")
                self.assertNotIn("save_training", json.loads((labeled.root / "config.json").read_text()))
                indexed = controller.store.index()
                self.assertEqual(indexed["frame_count"], 2)
                self.assertEqual(indexed["training_frame_count"], 1)
                self.assertEqual(indexed["training_materials"], ["paper"])
                frames = services.training.discover_frames(project / "dataset")
                self.assertEqual(len(frames), 1)
                self.assertEqual(frames[0][1]["material_id"], "paper")

    def test_four_frame_comparison(self):
        """逐帧调用推理，共轴绘图；拒绝第五帧/重复路径，单帧缓存互不覆盖。"""
        with tempfile.TemporaryDirectory(prefix="tdc_compare_test_") as temporary:
            project = Path(temporary)
            with patch.object(services, "PROJECT", project), patch.object(services, "WEB", project / "web"):
                controller = services.Controller(json.loads((ROOT / "web/config.json").read_text(encoding="utf-8")))
                writer = services.FrameWriter("paper", "paper_01", controller.config, "pl", {})
                paths = [writer.save(i + 1, services.np.arange(65536), services.np.full(65536, i + 1), None).relative_to(project).as_posix() for i in range(4)]
                controller.latest = {"path": paths[0], "sentinel": "single-frame"}
                def infer(counts, path):
                    number = int(counts[0])
                    return {"material": "material_" + str(number), "reference_bin": 1000,
                            "return_bin": 1900 + number * 100, "class_scores": {"material_" + str(number): 1.0},
                            "model_id": "test-model", "backend": "test"}
                def wait_job():
                    # ARM板端解析4个完整CSV较慢，不以电脑端读文件速度设超时。
                    deadline = time.monotonic() + 30
                    while controller.active() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(controller.job["status"], "done", controller.job)
                with patch.object(server, "controller", controller), patch.object(controller, "recognize_counts", side_effect=infer) as predictor:
                    client = server.app.test_client()
                    for bad in ([], paths + [paths[0]], [paths[0], paths[0]]):
                        self.assertEqual(client.post("/api/jobs/compare", json={"paths": bad, "recognize": True}).status_code, 400)
                    response = client.post("/api/jobs/compare", json={"paths": paths, "recognize": True})
                    self.assertEqual(response.status_code, 202); wait_job()
                    self.assertEqual(predictor.call_count, 4)
                    rows = controller.comparison["frames"]
                    self.assertEqual([row["result"]["material"] for row in rows], ["material_" + str(i) for i in range(1, 5)])
                    full = client.get("/api/comparison/plot?view=full").get_json()
                    self.assertEqual(full["y_max"], 500); self.assertEqual(len(full["curves"]), 4)
                    self.assertTrue(all(len(curve["x"]) <= 1800 for curve in full["curves"]))
                    echo = client.get("/api/comparison/plot?view=echo").get_json()
                    self.assertEqual((echo["x_min"], echo["x_max"]), (1200, 3100))
                    self.assertEqual(controller.latest["sentinel"], "single-frame")
                    self.assertEqual(controller.store.index()["frame_count"], 4)
                    # 只看波形时不调用分类器。
                    predictor.reset_mock()
                    with patch.object(services.training, "extract_features", return_value=(None, {"reference_bin": 1000, "return_bin": 2000})):
                        self.assertEqual(client.post("/api/jobs/compare", json={"paths": paths, "recognize": False}).status_code, 202)
                        wait_job()
                    self.assertEqual(predictor.call_count, 0)
                    # 删除已对比的批次时，同时清空缓存，避免继续显示已删除数据。
                    controller.delete_run("dataset", writer.run_id)
                    self.assertIsNone(controller.comparison)

    def test_output_units_and_rejection(self):
        self.assertEqual(parse_settings(DEFAULTS), [1250, 0, 625, 1125, 250])
        self.assertEqual(parse_settings(dict(DEFAULTS, laser_delay_ns=5))[1], 1)
        wrapping = parse_settings(dict(DEFAULTS, laser_delay_ns=9000, gate_delay_ns=9800))
        windows = window_summary(wrapping)
        self.assertEqual(windows['laser']['segments_ns'], [[0,4000],[9000,10000]])
        self.assertEqual(windows['gate']['segments_ns'], [[0,1800],[9800,10000]])
        self.assertEqual(windows['gate']['active_level'], 'low')
        self.assertEqual(windows['gate']['idle_level'], 'high')
        for changes in ({"frequency_khz": 0}, {"frequency_khz": "nan"}, {"laser_width_ns": 0},
                        {"laser_width_ns": 10000}, {"gate_delay_ns": 10000}, {"laser_delay_ns": True}):
            with self.assertRaises(ValueError):
                parse_settings(dict(DEFAULTS, **changes))

    def test_output_off_does_not_wait_capture_lock(self):
        runtime = PlRuntime(ROOT / "overlays/tdc_pynq.bit")
        runtime.overlay, runtime.capture = object(), FakeCapture()
        self.assertFalse(runtime.output_status()["enabled"])
        self.assertEqual(runtime.configure_outputs(DEFAULTS)["cycles"], [1250, 0, 625, 1125, 250])
        self.assertTrue(runtime.enable_outputs(True)["running"])
        with runtime.lock:
            worker = threading.Thread(target=runtime.enable_outputs, args=(False,))
            worker.start(); worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), "OFF被整帧采集锁阻挡")
        self.assertFalse(runtime.output_status()["running"])

    def test_gate_migration_and_stale_client_rejection(self):
        """保留旧版稳态低电平区间；旧页面不能把旧含义参数写入v5。"""
        period, _, _, start, width = parse_settings(dict(DEFAULTS,gate_delay_ns=8800))
        for phase in range(period):
            old_detector_open = not (100 <= phase < 1100)
            new_detector_open = ((phase-start) % period) < width
            self.assertEqual(old_detector_open,new_detector_open)
        with tempfile.TemporaryDirectory(prefix='tdc_gate_protocol_') as temporary:
            project=Path(temporary)
            with patch.object(services,'PROJECT',project),patch.object(services,'WEB',project/'web'):
                controller=services.Controller(json.loads((ROOT/'web/config.json').read_text(encoding='utf-8')))
                controller.pl.overlay,controller.pl.capture=object(),FakeCapture()
                with patch.object(server,'controller',controller):
                    client=server.app.test_client()
                    options=dict(DEFAULTS,action='configure')
                    self.assertEqual(client.post('/api/outputs',json=options).status_code,400)
                    response=client.post('/api/outputs',json=dict(options,timing_schema='active_windows_v1'))
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.get_json()['outputs']['windows']['gate']['segments_ns'],[[0,1000],[9000,10000]])

    def test_frontend_thresholds(self):
        self.assertEqual(parse_thresholds({}), [300, 300])
        self.assertEqual(parse_thresholds(dict(threshold_a_v="0.301", threshold_b_v=0)), [302, 0])
        for bad in (-0.1, 1.001, "nan", "Infinity", True, None):
            with self.assertRaises(ValueError): parse_thresholds({"threshold_a_v": bad})
        runtime = PlRuntime(ROOT / "overlays/tdc_pynq.bit")
        runtime.overlay, runtime.capture = object(), FakeCapture()
        result = runtime.configure_thresholds({"threshold_a_v": 0.15, "threshold_b_v": 0.4})["thresholds"]
        self.assertEqual((result["code_a"], result["code_b"]), (1099, 1224))
        self.assertEqual((result["threshold_a_v"], result["threshold_b_v"]), (0.15, 0.4))
        runtime.enable_outputs(True)
        with self.assertRaises(ValueError): runtime.configure_thresholds({})
        runtime.enable_outputs(False)
        runtime.capture.regs[8] = 2
        with self.assertRaises(ValueError): runtime.configure_thresholds({})
        runtime.capture.regs[8] = 0
        result = runtime.configure_thresholds({})["thresholds"]
        self.assertEqual(result["threshold_a_v"], 0.3)
        self.assertEqual(result["threshold_b_v"], 0.3)

    def test_restore_all_hardware_defaults(self):
        runtime = PlRuntime(ROOT / "overlays/tdc_pynq.bit")
        runtime.overlay, runtime.capture = object(), FakeCapture()
        runtime.configure_outputs(dict(DEFAULTS, frequency_khz=50, laser_delay_ns=160, dac1_high=400, dac2_high=350))
        runtime.set_reference("internal")
        runtime.configure_thresholds({"threshold_a_v": 0.15, "threshold_b_v": 0.4})
        runtime.enable_outputs(True)
        result = runtime.restore_defaults()
        self.assertFalse(result["enabled"])
        self.assertFalse(result["actual_enabled"])
        self.assertEqual(result["reference_source"], "internal")
        self.assertEqual(result["cycles"], [1250, 0, 625, 1125, 250])
        self.assertEqual(result["levels"], LEVEL_DEFAULTS)
        self.assertEqual(result["levels"]["dac1_high"], 0)
        self.assertEqual(result["levels"]["dac2_high"], 0)
        self.assertEqual(result["thresholds"]["threshold_a_v"], 0.3)
        self.assertEqual(result["thresholds"]["threshold_b_v"], 0.3)

    def test_dac_levels_and_reference(self):
        runtime = PlRuntime(ROOT / "overlays/tdc_pynq.bit")
        runtime.overlay, runtime.capture = object(), FakeCapture()
        self.assertEqual(parse_levels({}), LEVEL_DEFAULTS)
        for invalid in (-1, 1024, 1.5, "nan", True):
            with self.assertRaises(ValueError): parse_levels({"dac1_high": invalid})
        self.assertEqual(runtime.set_reference("internal")["reference_source"], "internal")
        with self.assertRaises(ValueError): runtime.set_reference("invalid")
        levels = dict(DEFAULTS, dac1_high=100, dac2_low=500)
        self.assertEqual(runtime.configure_outputs(levels)["levels"]["dac1_high"], 100)
        runtime.enable_outputs(True)
        with self.assertRaises(ValueError): runtime.set_reference("external")
        with self.assertRaises(ValueError): runtime.configure_outputs(dict(levels, dac1_high=101))
        runtime.enable_outputs(False)
        runtime.capture.regs[8] = 2
        with self.assertRaises(ValueError): runtime.set_reference("external")
        runtime.capture.regs[8] = 0
        self.assertEqual(runtime.set_reference("external")["reference_source"], "external")
        runtime.capture.regs[0x7c] = 0
        with self.assertRaises(ValueError): runtime.enable_outputs(True)
        self.assertFalse(runtime.enable_outputs(False)["enabled"])

    def test_batch_api_and_path_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="tdc_web_test_") as temporary:
            project = Path(temporary)
            with patch.object(services, "PROJECT", project), patch.object(services, "WEB", project / "web"):
                controller = services.Controller(json.loads((ROOT / "web/config.json").read_text(encoding="utf-8")))
                writer = services.FrameWriter("paper", "paper_01", controller.config, "pl", {})
                writer.save(1, services.np.arange(8), services.np.ones(8, dtype="uint32"), None)
                ordinary = services.FrameWriter("unlabeled", "sample_01", controller.config, "pl", {})
                self.assertEqual(controller.store.index()["frame_count"], 1)
                self.assertEqual(len(controller.store.browser_index()["runs"]), 2)
                self.assertIsNone(json.loads((writer.root / "config.json").read_text())["distance_cm"])
                controller.latest = {"path": str(writer.root.relative_to(project).as_posix()) + "/frame.csv"}
                (project / "models").mkdir(exist_ok=True); model = project / "models/keep.json"; model.write_text("untouched")
                (writer.folder / "frame_0001.dat").write_bytes(b"raw fixture")
                try:
                    (writer.folder / "model_link.json").symlink_to(model)
                except OSError:
                    pass  # Windows未开启符号链接权限时，仍执行其余删除校验。
                with patch.object(server, "controller", controller):
                    client = server.app.test_client()
                    payload = {"collection": "dataset", "run_id": writer.run_id}
                    controller.job["status"] = "running"
                    self.assertEqual(client.post("/api/data/delete_run", json=payload).status_code, 409)
                    controller.job["status"] = "idle"
                    for bad in ("../models", "run_../models", "/tmp"):
                        self.assertEqual(client.post("/api/data/delete_run", json=dict(payload, run_id=bad)).status_code, 400)
                    self.assertEqual(client.post("/api/data/delete_run", json=payload, headers={"Origin": "http://other-host"}).status_code, 403)
                    result = client.post("/api/data/delete_run", json=payload)
                    self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
                    self.assertFalse(writer.root.exists())
                    self.assertTrue(result.get_json()["deleted"]["permanent"])
                    self.assertNotIn("trashed", result.get_json()["deleted"])
                    self.assertFalse((project / ".trash").exists())
                    self.assertTrue(ordinary.root.is_dir(), "不能删除其他采集批次")
                    self.assertEqual(controller.store.index()["frame_count"], 0)
                    self.assertIsNone(controller.latest)
                    self.assertEqual(model.read_text(), "untouched")
                    # 同一数据目录的空批次也可直接删除，不会残留回收目录。
                    response = client.post("/api/data/delete_run", json={"collection": "dataset", "run_id": ordinary.run_id})
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(ordinary.root.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
