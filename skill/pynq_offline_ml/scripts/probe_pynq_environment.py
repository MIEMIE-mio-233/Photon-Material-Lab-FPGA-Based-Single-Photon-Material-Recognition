#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记录 PYNQ 实际 Python/库环境；不加载 Overlay，不改网络或模型。

设备就绪后推荐在板端 Jupyter 的单元格运行：
%run /path/to/probe_pynq_environment.py --json pynq_environment.json
也可在终端运行，但应以实际执行项目的 Jupyter 内核结果为准。
"""

import argparse
import importlib
import importlib.util
import json
import os
import platform
import shutil
import struct
import sys
from pathlib import Path


def collect_environment():
    report = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "machine": platform.machine(),
        "system": platform.system(),
        "pointer_bits": struct.calcsize("P") * 8,
        "working_directory": os.getcwd(),
        "effective_uid": os.geteuid() if hasattr(os, "geteuid") else None,
        "packages": {},
    }
    for name in ("pynq", "numpy", "scipy", "sklearn", "joblib",
                 "matplotlib", "ipywidgets", "notebook", "IPython",
                 "ipykernel", "flask", "werkzeug", "jinja2", "tornado",
                 "threadpoolctl"):
        try:
            module = importlib.import_module(name)
            item = {
                "available": True,
                "version": str(getattr(module, "__version__", getattr(module, "version", "unknown"))),
                "path": str(getattr(module, "__file__", "unknown")),
            }
            if name == "pynq":
                # 只检查符号是否存在，不创建硬件对象或下载比特流。
                item["has_Xlnk"] = hasattr(module, "Xlnk")
                item["has_allocate"] = hasattr(module, "allocate")
            report["packages"][name] = item
        except Exception as exc:
            report["packages"][name] = {
                "available": False,
                "error": "{}: {}".format(type(exc).__name__, exc),
            }
    report["python_features"] = {
        "dataclasses_available": importlib.util.find_spec("dataclasses") is not None,
        "path_is_relative_to": hasattr(Path, "is_relative_to"),
    }
    # 检查关键接口能否导入，不加载模型、分配 DMA 或更改 PL 电路。
    checks = {}
    for module_name, symbol in (("sklearn.ensemble", "RandomForestClassifier"),
                                ("scipy.ndimage", "uniform_filter1d")):
        try:
            module = importlib.import_module(module_name)
            checks[module_name + "." + symbol] = hasattr(module, symbol)
        except Exception as exc:
            checks[module_name + "." + symbol] = str(exc)
    report["required_apis"] = checks
    capacity = shutil.disk_usage(os.getcwd())
    report["storage"] = {"total_bytes": capacity.total, "free_bytes": capacity.free}
    memory = Path("/proc/meminfo")
    if memory.is_file():
        entries = {}
        for line in memory.read_text().splitlines():
            key, value = line.split(":", 1)
            if key in ("MemTotal", "MemAvailable", "SwapTotal"):
                entries[key] = value.strip()
        report["memory"] = entries
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="可选，将环境报告保存为 JSON")
    args = parser.parse_args()
    report = collect_environment()
    # ASCII JSON 在旧镜像的 ASCII 终端中也能输出，中文错误会安全转义。
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
