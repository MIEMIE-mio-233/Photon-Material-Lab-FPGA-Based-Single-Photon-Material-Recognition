#!/usr/bin/env python3
"""按清单比较多阶段结果，逐字段设置容差。只比较已有文件，不运行硬件。"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from compare_vectors import compare, read_vectors, unique_object


def verify(path):
    manifest = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if manifest.get("schema_version") != 1 or not manifest.get("case") or not manifest.get("comparisons"):
        raise ValueError("expected schema_version=1, case and nonempty comparisons")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or not provenance.get("kind") or type(provenance.get("hardware_executed")) is not bool:
        raise ValueError("provenance needs kind and boolean hardware_executed")
    results, names = [], set()
    for item in manifest["comparisons"]:
        name = item["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("comparison names must be nonempty and unique")
        names.add(name)
        ref_path, got_path = (path.parent / item["reference"]), (path.parent / item["observed"])
        reference, observed = read_vectors(ref_path), read_vectors(got_path)
        rules = item.get("tolerances", {})
        if not isinstance(rules, dict) or set(rules) - set(reference):
            raise ValueError("unknown tolerance field: " + name)
        if reference.keys() != observed.keys():
            fields = {"structure": compare(reference, observed)}
        else:
            fields = {}
            for key in reference:
                rule = rules.get(key, {})
                if not isinstance(rule, dict) or set(rule) - {"atol", "rtol"}:
                    raise ValueError("tolerance accepts only atol and rtol")
                fields[key] = compare({key: reference[key]}, {key: observed[key]},
                                      float(rule.get("atol", 0)), float(rule.get("rtol", 0)))
        results.append({"name": name, "passed": all(v["passed"] for v in fields.values()), "fields": fields,
                        "reference_sha256": hashlib.sha256(ref_path.read_bytes()).hexdigest(),
                        "observed_sha256": hashlib.sha256(got_path.read_bytes()).hexdigest()})
    return {"passed": all(r["passed"] for r in results), "case": manifest["case"],
            "provenance": provenance, "comparisons": results,
            "scope": "numeric parity of supplied artifacts; provenance is declared, not independently attested"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.manifest.resolve())
        code = 0 if report["passed"] else 1
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        report, code = {"passed": False, "input_error": str(exc)}, 2
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
