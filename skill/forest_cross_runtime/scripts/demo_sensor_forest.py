#!/usr/bin/env python3
"""非TDC合成五维传感器分类：训练、导出、阈值邻域一致性验证。"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from forest_portable import export_forest, PortableForest, add_boundary_samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from sklearn.ensemble import RandomForestClassifier
    rng = np.random.RandomState(71)
    centers = np.asarray([[-4, 0, 1, 3, 0], [0, 4, -3, 0, 2], [4, -4, 2, -3, -2]])
    train = np.vstack([rng.normal(center, 0.5, size=(40, 5)) for center in centers])
    labels = np.repeat([10, 20, 30], 40)
    samples = np.vstack([rng.normal(center, 0.5, size=(12, 5)) for center in centers])
    model = RandomForestClassifier(n_estimators=11, max_depth=5, random_state=71, n_jobs=1).fit(train, labels)
    payload = export_forest(model, {"feature_version": "synthetic_sensor_5d_v1"})
    portable = PortableForest(payload)
    compared = add_boundary_samples(model, samples, 96)
    a, b = model.predict_proba(compared), portable.predict_proba(compared)
    error = float(np.max(np.abs(a - b)))
    labels_equal = bool(np.array_equal(model.predict(compared), portable.predict(compared)))
    test_accuracy = float(np.mean(model.predict(samples) == np.repeat([10, 20, 30], 12)))
    report = {"passed": labels_equal and error <= 1e-12 and test_accuracy >= 0.9,
        "synthetic": True, "hardware_executed": False, "classes": payload["class_names"], "features": 5,
        "compared_rows": len(compared), "max_probability_error": error, "labels_equal": labels_equal,
        "synthetic_holdout_accuracy": test_accuracy,
        "scope": "native/portable equality in this runtime; synthetic data is not real sensor accuracy"}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "forest.portable.json").write_text(json.dumps(payload), encoding="utf-8")
    np.save(str(args.output / "features.npy"), compared, allow_pickle=False)
    # 可在另一Python环境仅用NumPy读取JSON和features，再与此概率参考比较。
    (args.output / "reference.json").write_text(json.dumps({"model_id": payload["model_id"], "class_names": payload["class_names"], "labels": model.predict(compared).tolist(),
        "probabilities": a.reshape(-1).tolist()}), encoding="utf-8")
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
