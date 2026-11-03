"""磁盘上的模型版本库；只索引轻量元数据，不预加载所有模型参数。"""

import hashlib
import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from model_algorithms import ALGORITHMS, algorithm_key, algorithm_info
from dense_models import FORMAT as DENSE_FORMAT, pack_dense, PortableDense
from cnn_models import FORMAT as CNN_FORMAT, pack_cnn, PortableCNN


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ModelRegistry:
    """每个版本只保存模型/报告/图表；训练数据始终引用公共 dataset。"""
    def __init__(self, folder):
        self.root = Path(folder).resolve()
        self.versions = self.root / "versions"
        self.versions.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._catalog_signature, self._catalog_cache = None, []
        # 首次升级归档现有模型，原 material_model.* 保留给旧命令行工具。
        legacy = self.root / "material_model.joblib"
        marker = self.root / "registry_initialized.json"
        if not marker.exists() and legacy.is_file() and legacy.with_suffix(".portable.json").is_file() and legacy.with_suffix(".report.json").is_file():
            report = read_json(legacy.with_suffix(".report.json"))
            model_id = self.checked_id(report["model_id"])
            if not (self.versions / model_id / "version.json").is_file():
                self.register(legacy.parent, name="已有模型", origin="imported")
            if not (self.root / "active.json").exists():
                if algorithm_key(report['model_type']) in ALGORITHMS:
                    self.activate(model_id)
                else:
                    write_json(self.root / 'active.json', {'model_id':None})
        # 仅首次导入旧根目录模型，删除归档后不会在重启时重新出现。
        if not marker.exists():
            write_json(marker, {"schema_version":1})

    @staticmethod
    def checked_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("模型版本编号无效")
        return value

    def version_dir(self, model_id):
        path = self.versions / self.checked_id(model_id)
        if path.is_symlink() or path.resolve().parent != self.versions.resolve():
            raise ValueError("模型版本目录无效")
        return path

    def active_id(self):
        with self.lock:
            path = self.root / "active.json"
            return read_json(path).get("model_id") if path.is_file() else None

    def path(self, model_id=None):
        model_id = model_id or self.active_id()
        if not model_id:
            raise ValueError("还没有可用模型，请先训练")
        folder = self.version_dir(model_id)
        if not (folder / "version.json").is_file():
            raise ValueError("找不到模型版本")
        return folder / "material_model.joblib"

    def info(self, model_id=None):
        path = self.path(model_id)
        return read_json(path.parent / "version.json")

    def catalog(self):
        """轮询不读取 joblib 或整份树 JSON，也不缓存模型权重。"""
        with self.lock:
            files = sorted(p for p in self.versions.glob("*/version.json") if not p.parent.name.startswith('.'))
            signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
            if signature != self._catalog_signature:
                records = [read_json(p) for p in files]
                self._catalog_cache = sorted(records, key=lambda r: r["created_at"], reverse=True)
                self._catalog_signature = signature
            return [dict(item, retired=item["algorithm"] not in ALGORITHMS) for item in self._catalog_cache]

    def delete(self, model_id):
        """永久删除非活动模型的参数和图表，不触碰公共dataset。"""
        with self.lock:
            model_id = self.checked_id(model_id)
            if model_id == self.active_id():
                raise ValueError("当前识别模型不能删除，请先切换其他模型")
            info = self.info(model_id)
            folder = self.version_dir(model_id)
            if folder.resolve().parent != self.versions.resolve() or folder.is_symlink():
                raise ValueError("模型目录超出允许范围")
            pending = self.versions / (".deleting_" + model_id + "_" + uuid.uuid4().hex)
            folder.rename(pending)
            try:
                shutil.rmtree(pending)
                legacy_report = self.root / "material_model.report.json"
                # 旧默认路径若是同一版本的兼容副本，一并清除，避免删除后仍被显式调用。
                if legacy_report.is_file() and read_json(legacy_report).get("model_id") == model_id:
                    for file in self.root.glob("material_model.*"):
                        if file.is_file() and not file.is_symlink() and file.parent == self.root:
                            file.unlink()
            finally:
                self._catalog_signature = None
            return {"id":model_id, "name":info["name"], "permanent":True}

    def activate(self, model_id):
        """只切换持久化指针；由业务层先等待空闲并释放旧模型。"""
        with self.lock:
            info = self.info(model_id)
            if info['algorithm'] not in ALGORITHMS:
                raise ValueError('该模型类型已停用，该历史版本可查看或删除')
            folder = self.version_dir(model_id)
            for name, expected in info["parameter_hashes"].items():
                if file_hash(folder / name) != expected:
                    raise ValueError("模型参数已改变或损坏：{}".format(name))
            write_json(self.root / "active.json", {"model_id": model_id})
            return info

    def register(self, staging, name="", origin="board"):
        """成功模型整套归档后才对外可见；训练取消不会覆盖任何历史版本。"""
        with self.lock:
            staging = Path(staging).resolve()
            prefix = staging / "material_model.joblib"
            report = read_json(prefix.with_suffix(".report.json"))
            model_id = self.checked_id(report["model_id"])
            algorithm = algorithm_key(report["model_type"])
            portable = read_json(prefix.with_suffix(".portable.json"))
            if portable.get("model_id") != model_id or portable.get("model_type") != report["model_type"]:
                raise ValueError("模型参数与训练报告不属于同一版本")
            trees = portable.get("trees", [])
            classes = report["class_names"]
            nodes = sum(len(tree["left"]) for tree in trees)
            dense = portable.get("format") == DENSE_FORMAT
            cnn = portable.get('format') == CNN_FORMAT
            if dense:
                PortableDense(portable)
            if cnn:PortableCNN(portable)
            model_bytes = int(pack_dense(portable).nbytes) if dense and len(classes) <= 64 else (len(trees) + nodes * (4 + len(classes))) * 8
            if cnn:model_bytes=int(pack_cnn(portable).nbytes)
            pl_compatible = bool(report.get("pl_compatible", len(classes) <= 64 and len(trees) <= 128 and nodes <= 16384))
            title = str(name).strip() or algorithm_info(algorithm)["name"] + " " + model_id
            if len(title) > 80:
                raise ValueError("模型名称不能超过80个字符")
            info = {"id": model_id, "name": title, "algorithm": algorithm,
                    "algorithm_name": algorithm_info(algorithm)["name"], "model_type": report["model_type"],
                    "created_at": report.get("created_at", datetime.fromtimestamp(prefix.stat().st_mtime, timezone.utc).isoformat()),
                    "source": origin, "classes": classes, "trees": len(trees), "nodes": nodes,
                    "distance_centers_cm": report.get('distance_centers_cm', []), "expert_count": report.get('expert_count', 0),
                    "calibration_id": report.get('calibration_id'), "distance_tolerance_cm": report.get('distance_tolerance_cm'),
                    "hidden_layer_sizes": report.get('model_parameters',{}).get('hidden_layer_sizes'), "tuning":report.get('tuning'),
                    "samples": report["samples"], "accuracy": report.get("holdout_accuracy"),
                    "holdout_method": report.get("holdout_method"), "feature_version": report["feature_version"],
                    "training_runs": report.get("training_runs", []), "pl_compatible": pl_compatible,
                    "pl_parameter_bytes": model_bytes,
                    "pl_model_kind": {"tiny_cnn":3,"mlp":2}.get(algorithm,0),
                    "feature_count": len(report.get('feature_names',[])),
                    "timing_reference_bin":report.get('timing_reference_bin'),
                    "timing_reference_source":report.get('timing_reference_source'),
                    "score_kind": portable.get("score_kind", "model_probability"),
                    "parameter_hashes": {p.name: file_hash(p) for p in (prefix, prefix.with_suffix(".portable.json"), prefix.with_suffix(".report.json"))}}
            destination = self.version_dir(model_id)
            if destination.exists():
                existing = self.info(model_id)
                if existing["parameter_hashes"] != info["parameter_hashes"]:
                    raise ValueError("模型编号重复且参数不同")
                return existing
            temporary = self.versions / (".pending_" + uuid.uuid4().hex)
            temporary.mkdir()
            try:
                for file in staging.glob("material_model.*"):
                    if file.is_file() and not file.is_symlink():
                        shutil.copyfile(str(file), str(temporary / file.name))
                info["disk_bytes"] = sum(p.stat().st_size for p in temporary.iterdir())
                write_json(temporary / "version.json", info)
                try:
                    temporary.replace(destination)
                except OSError:
                    # 两个进程首次启动时可能同时归档同一份旧模型。
                    # 只有完整版本已由另一进程写好、且哈希相同时才复用。
                    ready = destination / "version.json"
                    if ready.is_file() and read_json(ready).get("parameter_hashes") == info["parameter_hashes"]:
                        return read_json(ready)
                    raise
                self._catalog_signature = None
            finally:
                if temporary.exists() and temporary.parent == self.versions and not temporary.is_symlink():
                    shutil.rmtree(temporary)
            return info
