#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出单输出随机森林节点表，比较原生/便携概率；兼容 Python 3.6。"""

import argparse
import json
import sys
import uuid
from pathlib import Path

import numpy as np

FORMAT = "tdc_random_forest_v1"


def load_native(path):
    # 原生模型须在其相容的训练环境中读取；便携推理不需要这两个库。
    import joblib
    import sklearn
    from sklearn.ensemble import RandomForestClassifier

    artifact = joblib.load(str(path))
    metadata = {key: value for key, value in artifact.items() if key != "model"} if isinstance(artifact, dict) else {}
    model = artifact.get("model") if isinstance(artifact, dict) else artifact
    if not isinstance(model, RandomForestClassifier) or getattr(model, "n_outputs_", 0) != 1:
        raise ValueError("Only fitted single-output RandomForestClassifier is supported")
    if not getattr(model, "estimators_", None):
        raise ValueError("Forest has not been fitted")
    trained_version = metadata.get("library_versions", {}).get("sklearn")
    if trained_version and trained_version != sklearn.__version__:
        raise ValueError("Export/verify native model in its training sklearn version")
    return model, metadata


def export_forest(model, metadata=None):
    import sklearn

    payload = dict(metadata or {})
    payload.setdefault("model_id", uuid.uuid4().hex[:12])
    payload["model_type"] = "RandomForestClassifier"
    payload.setdefault("library_versions", {"sklearn": sklearn.__version__, "numpy": np.__version__})
    payload["format"] = FORMAT
    payload["class_names"] = model.classes_.tolist()
    # 新版 sklearn 与旧版 0.19 的特征数属性不同。
    n_features = getattr(model, "n_features_in_", None)
    if n_features is None:
        n_features = getattr(model, "n_features_", None)
    if n_features is None:
        raise ValueError("Missing input feature count")
    payload["n_features"] = int(n_features)
    payload.setdefault("feature_names", ["feature_{}".format(i) for i in range(n_features)])
    payload["trees"] = []
    for estimator in model.estimators_:
        tree = estimator.tree_
        values = tree.value[:, 0, :].astype(np.float64)
        totals = values.sum(axis=1, keepdims=True)
        if not np.all(totals > 0):
            raise ValueError("Tree contains a node with no class weight")
        payload["trees"].append({
            "left": tree.children_left.tolist(), "right": tree.children_right.tolist(),
            "feature": tree.feature.tolist(), "threshold": tree.threshold.tolist(),
            "probabilities": (values / totals).tolist(),
        })
    PortableForest(payload)  # 写文件前先核验结构。
    return payload


class PortableForest:
    """按全局类别顺序累加各树叶概率；不进行多数标签投票。"""

    def __init__(self, payload):
        if payload.get("format") != FORMAT:
            raise ValueError("Unknown forest JSON format")
        self.classes_ = np.asarray(payload["class_names"])
        self.n_features = int(payload.get("n_features", len(payload.get("feature_names", []))))
        self.trees = payload["trees"]
        if self.classes_.ndim != 1 or not self.classes_.size or not self.trees or self.n_features <= 0:
            raise ValueError("Empty forest, classes or feature count")
        if "feature_names" in payload and len(payload["feature_names"]) != self.n_features:
            raise ValueError("Feature name count differs from feature count")
        for tree in self.trees:
            count = len(tree["left"])
            if not count or any(len(tree[key]) != count for key in ("right", "feature", "threshold", "probabilities")):
                raise ValueError("Node array lengths differ")
            probabilities = np.asarray(tree["probabilities"], dtype=np.float64)
            if probabilities.shape != (count, self.classes_.size):
                raise ValueError("Class probability dimensions differ")
            if not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0):
                raise ValueError("Invalid class probabilities")
            if not np.allclose(probabilities.sum(axis=1), 1.0, rtol=0, atol=1e-10):
                raise ValueError("Class probabilities are not normalized")
            for node in range(count):
                left, right, feature = tree["left"][node], tree["right"][node], tree["feature"][node]
                if not all(isinstance(v, int) and not isinstance(v, bool) for v in (left, right, feature)):
                    raise ValueError("Node indexes must be integers")
                if (left == -1) != (right == -1):
                    raise ValueError("Leaf children must both equal -1")
                if left != -1:
                    if not (0 <= left < count and 0 <= right < count and 0 <= feature < self.n_features):
                        raise ValueError("Child or feature index is out of range")
                    if not np.isfinite(tree["threshold"][node]):
                        raise ValueError("Non-finite split threshold")

    def predict_proba(self, samples):
        # sklearn 的树输入先量化到 float32；阈值仍按原 double 数值比较。
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != self.n_features or not np.all(np.isfinite(samples)):
            raise ValueError("Features must be a finite two-dimensional array with matching columns")
        output = np.zeros((len(samples), len(self.classes_)), dtype=np.float64)
        for row, sample in enumerate(samples):
            for tree in self.trees:
                node = 0
                for _ in range(len(tree["left"])):
                    if tree["left"][node] == -1:
                        output[row] += np.asarray(tree["probabilities"][node], dtype=np.float64)
                        break
                    key = "left" if float(sample[tree["feature"][node]]) <= tree["threshold"][node] else "right"
                    node = tree[key][node]
                else:
                    raise ValueError("Cyclic forest node table")
        return output / len(self.trees)

    def predict(self, samples):
        return self.classes_[np.argmax(self.predict_proba(samples), axis=1)]


def read_features(path):
    loaded = np.load(str(path), allow_pickle=False)
    if hasattr(loaded, "files"):
        try:
            features = np.asarray(loaded["X"], dtype=np.float64)
        finally:
            loaded.close()
    else:
        features = np.asarray(loaded, dtype=np.float64)
    if features.ndim != 2 or not len(features) or not np.all(np.isfinite(features)):
        raise ValueError("Features must contain at least one finite two-dimensional sample")
    return features


def add_boundary_samples(model, features, limit):
    """用真实首帧作为其他列的基准，补充阈值两侧的 float32 输入。"""
    rows = []
    for estimator in model.estimators_:
        tree = estimator.tree_
        for feature, threshold in zip(tree.feature, tree.threshold):
            if feature < 0:
                continue
            center = np.float32(threshold)
            for value in (np.nextafter(center, np.float32(-np.inf)), center,
                          np.nextafter(center, np.float32(np.inf))):
                if len(rows) >= limit:
                    return np.vstack([features] + rows) if rows else features
                sample = features[0].copy()
                sample[feature] = value
                rows.append(sample)
    return np.vstack([features] + rows) if rows else features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    export = commands.add_parser("export")
    export.add_argument("--native", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--native", type=Path, required=True)
    verify.add_argument("--portable", type=Path, required=True)
    verify.add_argument("--features", type=Path, required=True)
    verify.add_argument("--boundary-limit", type=int, default=512)
    verify.add_argument("--atol", type=float, default=1e-12)
    verify.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "export":
            model, metadata = load_native(args.native)
            payload = export_forest(model, metadata)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            print(json.dumps({"passed": True, "trees": len(payload["trees"]), "classes": len(payload["class_names"]), "model_id": payload["model_id"]}))
            return 0
        if args.command != "verify":
            parser.error("Choose export or verify")
        if args.boundary_limit < 0 or args.atol < 0 or not np.isfinite(args.atol):
            raise ValueError("Boundary limit and finite tolerance must be non-negative")
        model, metadata = load_native(args.native)
        payload = json.loads(args.portable.read_text(encoding="utf-8"))
        portable = PortableForest(payload)
        if not np.array_equal(model.classes_, portable.classes_):
            raise ValueError("Class order differs")
        if metadata.get("model_id") and metadata["model_id"] != payload.get("model_id"):
            raise ValueError("Native and portable model identifiers differ")
        features = read_features(args.features)
        if features.shape[1] != portable.n_features:
            raise ValueError("Feature column count differs from forest")
        samples = add_boundary_samples(model, features, args.boundary_limit)
        native_scores, portable_scores = model.predict_proba(samples), portable.predict_proba(samples)
        error = float(np.max(np.abs(native_scores - portable_scores)))
        same_labels = bool(np.array_equal(model.predict(samples), portable.predict(samples)))
        passed = bool(error <= args.atol and same_labels)
        report = {"passed": passed, "feature_rows": len(features), "compared_samples": len(samples),
                  "classes": len(portable.classes_), "trees": len(portable.trees), "n_features": portable.n_features,
                  "max_probability_error": error, "atol": args.atol, "labels_equal": same_labels,
                  "model_id": payload.get("model_id")}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if passed else 1
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
