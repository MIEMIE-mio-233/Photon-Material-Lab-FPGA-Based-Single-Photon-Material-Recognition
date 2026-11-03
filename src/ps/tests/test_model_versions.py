"""版本/批次筛选/三种便携树模型/释放资源的离线回归，只使用临时数据集。"""
import argparse
import csv
import gc
import json
import sys
import tempfile
import unittest
import weakref
import shutil
import concurrent.futures
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "web")]
import train_material as training
import predict_material as inference
import services
import server
from model_registry import ModelRegistry
from model_algorithms import ALGORITHMS
from pl_runtime import pack_model


class ModelVersions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tdc_versions_")
        cls.project = Path(cls.temporary.name)
        cls.dataset = cls.project / "dataset"
        cls.config = json.loads((ROOT / "web/config.json").read_text())
        bins = np.arange(65536)
        for material, width in [("alpha", 25), ("beta", 100)]:
            for specimen in range(2):
                run = cls.dataset / ("run_{}_{}".format(material, specimen))
                folder = run / "frames"; folder.mkdir(parents=True)
                with (run / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=services.MANIFEST_FIELDS); writer.writeheader()
                    for number in range(1, 7):
                        counts = (2 + 5000 * np.exp(-((bins - 10120) / 4) ** 2) + (90 + number) * np.exp(-((bins - 17500) / (width + number)) ** 2)).astype("uint32")
                        name = "frame_{:04d}.npy".format(number)
                        np.save(str(folder / name), counts, allow_pickle=False)
                        writer.writerow(dict(run_id=run.name, material_id=material,
                            specimen_id=material + str(specimen), frame_index=number,
                            bin_num=65536, bin_width_ps=8, trig_num=100000,
                            total_counts=int(counts.sum()), csv_path="frames/" + name, raw_path=""))
        cls.selection = ["dataset/run_alpha_0", "dataset/run_beta_0"]
        cls.registry = ModelRegistry(cls.project / "models")
        cls.ids = {}
        for algorithm in ALGORITHMS:
            staging = cls.project / algorithm; staging.mkdir()
            args = argparse.Namespace(dataset=cls.dataset, model=staging / "material_model.joblib",
                algorithm=algorithm, run_keys=cls.selection, trees=4, max_depth=3,
                prefer_raw=False, no_figures=True)
            seen = []
            real_read = training.read_frame
            def record(path):
                seen.append(Path(path)); return real_read(path)
            with patch.object(training, "read_frame", side_effect=record):
                training.train(args)
            # 12帧训练读取，另取每类1帧保存绘图快照；不读取未选批次。
            assert len(seen) == (26 if algorithm=="tiny_cnn" else 14) and all("_0" in p.parents[1].name for p in seen)
            version = cls.registry.register(staging, algorithm)
            cls.ids[algorithm] = version["id"]
        cls.registry.activate(cls.ids["random_forest"])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def controller(self):
        with patch.object(services, "PROJECT", self.project), patch.object(services, "WEB", self.project / "web"):
            return services.Controller(self.config)

    def test_all_tree_types_native_portable_and_pl_pack(self):
        data = training.load_training_data(self.dataset, run_keys=self.selection)
        for algorithm, model_id in self.ids.items():
            path = self.registry.path(model_id)
            native = inference.load_model(path, "sklearn")
            portable = inference.load_model(path, "portable")
            probes = [data.features]
            payload = json.loads(path.with_suffix(".portable.json").read_text())
            for tree in payload.get("trees", []):
                for feature, threshold in zip(tree["feature"], tree["threshold"]):
                    if feature < 0: continue
                    for value in [np.float32(threshold), np.nextafter(np.float32(threshold), np.float32(-np.inf)), np.nextafter(np.float32(threshold), np.float32(np.inf))]:
                        sample = data.features[0].copy(); sample[feature] = value; probes.append(sample[None, :])
            samples = np.vstack(probes)
            if algorithm=="tiny_cnn":
                samples=np.vstack([inference.model_sample(native,training.read_frame(path)[1],feature,detail) for feature,(path,row,detail) in zip(data.features,data.details)])
            np.testing.assert_allclose(inference.class_scores(native["model"],samples), portable["model"].predict_proba(samples), atol=1e-12, rtol=0)
            meta, packed, nodes = pack_model(path.with_suffix(".portable.json"))
            info = self.registry.info(model_id)
            self.assertEqual(packed.nbytes, info["pl_parameter_bytes"])
            self.assertEqual(nodes, info["nodes"])
            self.assertEqual(meta["model_type"], ALGORITHMS[algorithm]["model_type"])
            self.assertEqual(info["training_runs"], self.selection)
            self.assertEqual(info["samples"], 12)
            self.assertEqual(info["trees"], 1 if algorithm == "decision_tree" else 4 if algorithm == 'random_forest' else 0)
        self.assertEqual(len(list(self.dataset.rglob("*.npy"))), 24)
        self.assertEqual(list((self.project / "models").rglob("*.npy")), [])

    def test_selection_missing_empty_and_unselected_batches(self):
        with self.assertRaises(ValueError): training.discover_frames(self.dataset, [])
        with self.assertRaises(ValueError): training.discover_frames(self.dataset, ["dataset/run_missing"])
        self.assertEqual(len(training.discover_frames(self.dataset, self.selection)), 12)
        self.assertEqual(len(training.discover_frames(self.dataset)), 24)

    def test_pl_infer_uses_compact_metadata_after_model_upload(self):
        """上传后不缓存整棵树；推理仍须向HLS传入正确树数。"""
        from pl_runtime import PlRuntime
        class Buffer(np.ndarray):
            physical_address = 0x10000000
            def flush(self): pass
            def invalidate(self): pass
            def freebuffer(self): pass
        def allocate(shape, dtype): return np.zeros(shape, dtype=dtype).view(Buffer)
        runtime = PlRuntime(self.project / 'dummy.bit')
        runtime.overlay = object()
        runtime.supports_dense = True
        runtime.supports_shift = True
        runtime.allocate = allocate
        runtime.result_buffer = allocate((88,), np.float64)
        class Capture:
            def read(self, address): return 1
        class Histogram:
            array = np.zeros(65536, dtype=np.uint32)
        class Accelerator:
            def __init__(self): self.registers = {}
            def read(self, address): return 6  # ap_idle + ap_done
            def write(self, address, value):
                self.registers[address] = value
                if address == 0:
                    runtime.result_buffer[:]=0
                    runtime.result_buffer[[2,3,4,5,24]]=[10120,17500,3,9,1]
        runtime.capture, runtime.hist, runtime.hist_address = Capture(), Histogram(), 0x40000000
        runtime.accelerator = Accelerator()
        for key, model_id in self.ids.items():
            result = runtime.infer(np.zeros(65536, dtype=np.uint32), self.registry.path(model_id).with_suffix('.portable.json'))
            self.assertNotIn('trees', runtime.metadata)
            self.assertEqual(runtime.accelerator.registers[0x44], 1 if key == 'decision_tree' else 4 if key == 'random_forest' else 0)
            self.assertEqual(runtime.accelerator.registers[0x54], {'tiny_cnn':3,'mlp':2}.get(key,0))
            self.assertEqual(result['model_id'], model_id)
            if key in ('tiny_cnn','mlp'):
                self.assertEqual(list(result['class_scores'].values()),[0.7311,0.2689])
            runtime.release_model()

    def test_switch_releases_old_weights_and_persists_selection(self):
        controller = self.controller()
        controller.select_model(self.ids["random_forest"])
        old = weakref.ref(controller.artifact()["model"])
        controller.select_model(self.ids["tiny_cnn"])
        gc.collect()
        self.assertIsNone(old())
        self.assertIsNone(controller.model_cache)
        self.assertFalse(controller.model_memory()["ps_model_loaded"])
        fresh = self.controller()
        self.assertEqual(fresh.model_info()["id"], self.ids["tiny_cnn"])
        self.assertIsNone(fresh.model_cache)
        class Buffer:
            nbytes = 4096
            freed = False
            def freebuffer(self): self.freed = True
        class Accelerator:
            ready = 4
            def read(self, offset): return self.ready
        buffer = Buffer(); accelerator = Accelerator()
        controller.pl.model_buffer, controller.pl.accelerator = buffer, accelerator
        accelerator.ready = 0
        with self.assertRaises(ValueError): controller.select_model(self.ids["decision_tree"])
        self.assertFalse(buffer.freed)
        accelerator.ready = 4
        controller.select_model(self.ids["decision_tree"])
        self.assertTrue(buffer.freed)
        self.assertIsNone(controller.pl.model_buffer)

    def test_api_selection_and_rejection_while_busy(self):
        controller = self.controller()
        with patch.object(server, "controller", controller):
            client = server.app.test_client()
            self.assertEqual(len(client.get('/api/models').get_json()['models']), 4)
            self.assertEqual(client.post('/api/jobs/train', json={'run_keys': []}).status_code, 400)
            self.assertEqual(client.post('/api/jobs/train', json={'run_keys': ['dataset/run_missing']}).status_code, 400)
            self.assertEqual(client.post('/api/model', json={'model_id': '../escape'}).status_code, 400)
            response = client.post('/api/model', json={'model_id': self.ids['decision_tree']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['model']['trees'], 1)
            controller.job['status'] = 'running'
            self.assertEqual(client.post('/api/model', json={'model_id': self.ids['random_forest']}).status_code, 409)
            controller.job['status'] = 'idle'
            response = client.get('/api/model/download/portable')
            self.assertEqual(json.loads(response.data)['model_id'], self.ids['decision_tree'])
            response.close()

    def test_atomic_archive_from_two_registry_instances(self):
        with tempfile.TemporaryDirectory(prefix="tdc_registry_race_") as folder:
            registries = [ModelRegistry(folder), ModelRegistry(folder)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                records = list(pool.map(lambda registry: registry.register(self.project / 'random_forest'), registries))
            self.assertEqual(records[0]['id'], records[1]['id'])
            self.assertEqual(len(registries[0].catalog()), 1)

    def test_training_failure_cancel_and_save_without_activate(self):
        controller = self.controller()
        controller.select_model(self.ids['random_forest'])
        options = dict(algorithm='tiny_cnn', trees=4, max_depth=3, name='new version',
                       run_keys=self.selection, activate=False)
        origin = self.project / 'tiny_cnn'
        class Process:
            status = 0
            stdout = []
            def __init__(self, command, **kwargs):
                assert '--no-figures' in command, '网页训练不能等待PNG绘制'
                folder = Path(command[command.index('--model') + 1]).parent
                for file in origin.glob('material_model.*'):
                    shutil.copyfile(file, folder / file.name)
            def poll(self): return self.status
            def wait(self, **kwargs): return self.status
        with patch.object(services, 'PROJECT', self.project), patch.object(services, 'WEB', self.project / 'web'), patch.object(services.subprocess, 'Popen', Process):
            controller._train(options)
            self.assertEqual(controller.registry.active_id(), self.ids['random_forest'])
            self.assertEqual(list((self.project / 'web/runtime').glob('train_*')), [])
            Process.status = 1
            with self.assertRaises(ValueError): controller._train(options)
            self.assertEqual(controller.registry.active_id(), self.ids['random_forest'])
            Process.status = 0; controller.stop_event.set()
            with self.assertRaises(services.Cancelled): controller._train(options)
            self.assertEqual(controller.registry.active_id(), self.ids['random_forest'])
            self.assertEqual(list((self.project / 'web/runtime').glob('train_*')), [])

    def test_delete_version_and_no_legacy_resurrection(self):
        with tempfile.TemporaryDirectory(prefix='tdc_delete_model_') as folder:
            root = Path(folder)
            for file in (self.project/'random_forest').glob('material_model.*'):
                shutil.copyfile(file,root/file.name)
            registry = ModelRegistry(root)
            old = registry.active_id()
            new = registry.register(self.project/'decision_tree')['id']
            with self.assertRaises(ValueError): registry.delete(old)
            registry.activate(new)
            controller = self.controller(); controller.registry = registry
            with patch.object(server,'controller',controller):
                client = server.app.test_client()
                controller.job['status']='running'
                self.assertEqual(client.post('/api/models/delete',json={'model_id':old}).status_code,409)
                controller.job['status']='idle'
                self.assertEqual(client.post('/api/models/delete',json={'model_id':'../escape'}).status_code,400)
                self.assertEqual(client.post('/api/models/delete',json={'model_id':new}).status_code,400)
                self.assertEqual(client.post('/api/models/delete',json={'model_id':old}).status_code,200)
            fresh = ModelRegistry(root)
            self.assertEqual([item['id'] for item in fresh.catalog()],[new])
            self.assertFalse((root/'material_model.joblib').exists())
            self.assertEqual(len(list(self.dataset.rglob('*.npy'))),24)


if __name__ == '__main__':
    unittest.main()
