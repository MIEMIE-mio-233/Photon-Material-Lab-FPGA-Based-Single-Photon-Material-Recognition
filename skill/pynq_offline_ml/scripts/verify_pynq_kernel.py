#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动指定 Jupyter 内核，验证环境和小森林拟合；不加载 Overlay。"""

import argparse
import json
import sys
import time
from pathlib import Path


def verify_kernel(kernel, working_directory, expected_python=None, timeout=60):
    from jupyter_client import KernelManager

    helper_directory = str(Path(__file__).resolve().parent)
    code = """
import sys, json
sys.path.insert(0, {helper_directory!r})
from probe_pynq_environment import collect_environment
report = collect_environment()
report['kernel_name'] = {kernel!r}
expected = {expected_python!r}
for name in ('pynq', 'numpy', 'scipy', 'sklearn', 'joblib'):
    if not report['packages'][name]['available']:
        raise RuntimeError(name + ': ' + report['packages'][name].get('error', 'unavailable'))
if expected and report['python_executable'] != expected:
    raise RuntimeError('Wrong kernel interpreter: ' + report['python_executable'])
import numpy as np
from sklearn.ensemble import RandomForestClassifier
X = np.arange(240, dtype=np.float64).reshape(30, 8)
y = np.repeat(np.arange(3), 10)
model = RandomForestClassifier(n_estimators=4, max_depth=4, random_state=42, n_jobs=1)
model.fit(X, y)
assert model.predict_proba(X[:1]).shape == (1, 3)
report['random_forest_smoke_test'] = 'passed'
report['passed'] = True
print('SKILL_KERNEL_JSON=' + json.dumps(report, ensure_ascii=True))
""".format(helper_directory=helper_directory, kernel=kernel, expected_python=expected_python)
    manager = KernelManager(kernel_name=kernel)
    client = None
    try:
        manager.start_kernel(cwd=str(working_directory))
        client = manager.client()
        client.start_channels()
        client.wait_for_ready(timeout=timeout)
        message_id = client.execute(code)
        output = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = client.get_iopub_msg(timeout=max(1, deadline - time.time()))
            if message.get("parent_header", {}).get("msg_id") != message_id:
                continue
            kind, content = message["header"]["msg_type"], message["content"]
            if kind == "stream":
                output.append(content["text"])
            elif kind == "error":
                raise RuntimeError("{}: {}".format(content["ename"], content["evalue"]))
            elif kind == "status" and content.get("execution_state") == "idle":
                text = "".join(output)
                for line in text.splitlines():
                    if line.startswith("SKILL_KERNEL_JSON="):
                        return json.loads(line.split("=", 1)[1])
                raise RuntimeError("Kernel did not return environment JSON: " + text)
        raise RuntimeError("Kernel execution timed out")
    finally:
        if client is not None:
            client.stop_channels()
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", required=True)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--expected-python")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise ValueError("Timeout must be positive")
        report = verify_kernel(args.kernel, args.cwd, args.expected_python, args.timeout)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
