#!/usr/bin/env python3
"""执行Python整数FIR和NumPy卷积，生成可复现非TDC黄金参考案例。"""
import argparse
import json
from pathlib import Path
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    samples = [2**53 + 1, 3, -7, 9, 0, -5, 2]
    taps = [1, -2, 3]
    scalar = [sum(samples[i + k] * taps[k] for k in range(len(taps))) for i in range(len(samples) - len(taps) + 1)]
    vector = np.convolve(np.asarray(samples, dtype=np.int64), np.asarray(taps[::-1], dtype=np.int64), mode="valid").tolist()
    for name, values in (("python_scalar", scalar), ("numpy_vector", vector)):
        (args.output / (name + ".json")).write_text(json.dumps({"fir": values}), encoding="utf-8")
    manifest = {"schema_version": 1, "case": "synthetic_integer_fir",
        "provenance": {"kind": "synthetic_software_execution", "hardware_executed": False,
                       "implementations": ["Python arbitrary-precision integers", "NumPy int64 valid convolution"]},
        "comparisons": [{"name": "scalar_to_vector", "reference": "python_scalar.json", "observed": "numpy_vector.json"}]}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"synthetic": True, "hardware_executed": False, "samples": len(scalar)}))


if __name__ == "__main__":
    main()
