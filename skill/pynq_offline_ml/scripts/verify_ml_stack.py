#!/usr/bin/env python3
"""验证NumPy/SciPy/sklearn实际计算；可要求PYNQ可导入，不加载硬件。"""
import argparse
import json
from pathlib import Path
import platform
import struct
import sys
import time


def verify(require_pynq=False):
    import numpy as np
    import scipy
    import sklearn
    import joblib
    from scipy.ndimage import uniform_filter1d
    from sklearn.ensemble import RandomForestClassifier
    started = time.perf_counter()
    # 小型非TDC样本：三种合成状态、四个连续特征，检查原生扩展确实参与计算。
    rng = np.random.RandomState(43)
    data = np.vstack([rng.normal(center, 0.1, size=(20, 4)) for center in (-3, 0, 3)])
    labels = np.repeat([0, 1, 2], 20)
    model = RandomForestClassifier(n_estimators=7, max_depth=4, random_state=43, n_jobs=1).fit(data, labels)
    score = float(np.mean(model.predict(data) == labels))
    filtered = uniform_filter1d(np.arange(8, dtype=np.float64), size=3)
    if score < 0.95 or filtered.shape != (8,) or not np.isfinite(filtered).all():
        raise ValueError("native extension fit/filter check failed")
    pynq_info = {"available": False, "required": require_pynq}
    try:
        import pynq
        pynq_info.update(available=True, version=getattr(pynq, "__version__", "unknown"),
                         has_allocate=hasattr(pynq, "allocate"), has_Xlnk=hasattr(pynq, "Xlnk"))
    except Exception as exc:
        pynq_info["error"] = str(exc)
        if require_pynq:
            raise ValueError("PYNQ import failed in this interpreter: " + str(exc))
    return {"passed": True, "python": sys.version, "executable": sys.executable,
            "architecture": platform.machine(), "pointer_bits": struct.calcsize("P") * 8,
            "numpy": np.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__, "joblib": joblib.__version__,
            "pynq": pynq_info, "synthetic_training_accuracy": score,
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "scope": "this interpreter only; no Overlay load, allocation, network changes or Jupyter kernel selection"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-pynq", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report, code = verify(args.require_pynq), 0
    except (ImportError, OSError, ValueError, TypeError) as exc:
        report, code = {"passed": False, "error": str(exc)}, 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
