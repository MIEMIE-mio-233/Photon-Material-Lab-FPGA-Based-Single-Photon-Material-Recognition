#!/usr/bin/env python3
"""通用分段计时、同输入性能比对，以及临时目录中的CSV/NPY示例。"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time


class StageTimer:
    """各段互斥，total从构造到finish；不支持嵌套，以免重复累计。"""
    def __init__(self, **metadata):
        self.metadata, self.stages, self.active = metadata, {}, None
        self.started = time.perf_counter()

    @contextmanager
    def stage(self, name):
        if self.active is not None or not isinstance(name, str) or not name or name in self.stages:
            raise ValueError("stage names must be unique; nested/overlapping stages are unsupported")
        self.active, started = name, time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = (time.perf_counter() - started) * 1000
            self.active = None

    def finish(self):
        if self.active is not None:
            raise ValueError("cannot finish an active stage")
        result = dict(self.metadata, stages_ms=dict(self.stages), total_ms=(time.perf_counter() - self.started) * 1000)
        validate_record(result)
        return result


def validate_record(record):
    for key in ("case", "backend", "model_id", "scope"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ValueError("missing string: " + key)
    checksum = record.get("input_sha256", "")
    if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("input_sha256 must be lowercase 64-character hex")
    if type(record.get("warmup")) is not bool:
        raise ValueError("warmup must be an explicit boolean")
    stages = record.get("stages_ms")
    if not isinstance(stages, dict) or not stages or any(not isinstance(k, str) or not k for k in stages):
        raise ValueError("expected named exclusive stages")
    values = list(stages.values()) + [record.get("total_ms")]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("times must be finite, nonnegative milliseconds")
    if sum(stages.values()) > record["total_ms"] + 0.001:
        raise ValueError("stage sum exceeds total; check nested timing, units or rounding")


def stats(values):
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lo, hi = int(position), min(int(position) + 1, len(ordered) - 1)
    p95 = ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)
    return {"count": len(values), "median_ms": statistics.median(values), "p95_ms": p95,
            "min_ms": ordered[0], "max_ms": ordered[-1]}


def summarize(records, baseline=None, candidate=None):
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a nonempty list")
    if bool(baseline) != bool(candidate) or (baseline and baseline == candidate):
        raise ValueError("choose distinct baseline and candidate together")
    grouped, warmups = {}, 0
    # 使用输入哈希、模型和测量范围组成比较键，不跨不同工作负载计算加速比。
    identity = ("case", "input_sha256", "model_id", "scope")
    for record in records:
        validate_record(record)
        if record["warmup"]:
            warmups += 1
            continue
        key = tuple(record[k] for k in identity) + (record["backend"],)
        grouped.setdefault(key, []).append(record)
    if not grouped:
        raise ValueError("no steady-state records after excluding warmup")
    groups, pairs = [], {}
    for key, rows in sorted(grouped.items()):
        fields = set(rows[0]["stages_ms"])
        if any(set(r["stages_ms"]) != fields for r in rows):
            raise ValueError("stage names changed within one measurement group")
        group = dict(zip(identity, key[:-1]))
        group.update(backend=key[-1], total=stats([r["total_ms"] for r in rows]),
                     stages={field: stats([r["stages_ms"][field] for r in rows]) for field in sorted(fields)})
        groups.append(group)
        pairs.setdefault(key[:-1], {})[key[-1]] = group
    comparisons, unpaired = [], []
    if baseline:
        for key, options in sorted(pairs.items()):
            if baseline not in options or candidate not in options:
                unpaired.append(dict(zip(identity, key)))
                continue
            a, b = options[baseline]["total"], options[candidate]["total"]
            comparisons.append(dict(dict(zip(identity, key)), baseline=baseline, candidate=candidate,
                baseline_count=a["count"], candidate_count=b["count"],
                total_median_ratio=a["median_ms"] / b["median_ms"] if b["median_ms"] else None))
        if not comparisons:
            raise ValueError("no comparable pairs: inputs/model/scope must match")
    return {"passed": True, "warmup_records_excluded": warmups, "groups": groups,
            "comparisons": comparisons, "unpaired": unpaired,
            "scope": "application timings; ratios do not imply hardware cycle latency or universal speedup"}


def storage_demo(directory, repeats, length, durable):
    import numpy as np
    if repeats < 1 or length < 1:
        raise ValueError("positive repeats and length required")
    # 非TDC例子：16位灰度像素行。验证两种格式保留完全相同的数值。
    values = ((np.arange(length, dtype=np.uint64) * 17) % 65536).astype(np.uint16)
    checksum = hashlib.sha256(values.tobytes()).hexdigest()
    records = []
    with tempfile.TemporaryDirectory(prefix="pynq_storage_demo_", dir=str(directory) if directory else None) as work:
        for repeat in range(repeats + 1):
            for backend in (("csv", "npy") if repeat % 2 == 0 else ("npy", "csv")):
                path = Path(work) / ("pixels." + backend)
                timer = StageTimer(case="synthetic_grayscale_row", input_sha256=checksum, model_id="none",
                    backend=backend, scope="write_read_verify_fsync" if durable else "write_read_verify_os_cache", warmup=repeat == 0)
                with timer.stage("write"):
                    with path.open("wb") as stream:
                        if backend == "npy":
                            np.save(stream, values, allow_pickle=False)
                        else:
                            np.savetxt(stream, values, fmt="%u", delimiter=",")
                        stream.flush()
                        if durable:
                            os.fsync(stream.fileno())
                with timer.stage("read"):
                    if backend == "npy":
                        loaded = np.load(str(path), allow_pickle=False)
                    else:
                        loaded = np.loadtxt(str(path), dtype=np.uint16, delimiter=",", ndmin=1)
                with timer.stage("verify"):
                    if loaded.dtype != values.dtype or not np.array_equal(loaded, values):
                        raise ValueError("storage changed dtype or values")
                records.append(timer.finish())
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    view = sub.add_parser("summarize")
    view.add_argument("records", type=Path)
    view.add_argument("--baseline")
    view.add_argument("--candidate")
    demo = sub.add_parser("storage-demo")
    demo.add_argument("--directory", type=Path)
    demo.add_argument("--repeats", type=int, default=5)
    demo.add_argument("--length", type=int, default=8192)
    demo.add_argument("--durable", action="store_true")
    demo.add_argument("--records", type=Path, required=True)
    for cmd in (view, demo):
        cmd.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "storage-demo":
            records = storage_demo(args.directory, args.repeats, args.length, args.durable)
            report = summarize(records, "csv", "npy")
            report["storage_note"] = "read uses OS cache; fsync={}; no cache eviction or physical SD latency claim".format(args.durable)
            args.records.parent.mkdir(parents=True, exist_ok=True)
            args.records.write_text(json.dumps(records, indent=2), encoding="utf-8")
        elif args.command == "summarize":
            content = args.records.read_text(encoding="utf-8-sig")
            records = json.loads(content) if content.lstrip().startswith("[") else [json.loads(line) for line in content.splitlines() if line.strip()]
            report = summarize(records, args.baseline, args.candidate)
        else:
            parser.error("choose summarize or storage-demo")
        code = 0
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError) as exc:
        report, code = {"passed": False, "error": str(exc)}, 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
