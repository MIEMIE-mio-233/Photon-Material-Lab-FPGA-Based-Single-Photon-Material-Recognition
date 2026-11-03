#!/usr/bin/env python3
"""只用NumPy核验源环境导出的森林和概率参考，不反序列化源joblib。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from forest_portable import PortableForest, read_features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--atol", type=float, default=1e-12)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not np.isfinite(args.atol) or args.atol < 0:
            raise ValueError("finite nonnegative tolerance required")
        payload = json.loads(args.portable.read_text(encoding="utf-8-sig"))
        reference = json.loads(args.reference.read_text(encoding="utf-8-sig"))
        if reference.get("model_id") != payload.get("model_id") or reference.get("class_names") != payload["class_names"]:
            raise ValueError("reference model ID or class order differs")
        model = PortableForest(payload)
        features = read_features(args.features)
        actual = model.predict_proba(features)
        expected = np.asarray(reference["probabilities"], dtype=np.float64)
        if expected.shape != (actual.size,) or not np.isfinite(expected).all() or len(reference["labels"]) != len(features):
            raise ValueError("reference shape or finite values invalid")
        error = float(np.max(np.abs(actual.reshape(-1) - expected)))
        labels_equal = bool(np.array_equal(model.predict(features), reference["labels"]))
        report = {"passed": error <= args.atol and labels_equal, "model_id": payload["model_id"],
            "rows": len(features), "max_probability_error": error, "labels_equal": labels_equal,
            "numpy": np.__version__, "scope": "portable inference vs supplied source reference; no sklearn import or hardware access",
            "sha256": {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in
                       (("portable", args.portable), ("features", args.features), ("reference", args.reference))}}
        code = 0 if report["passed"] else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report, code = {"passed": False, "error": str(exc)}, 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
