"""Compare finite numeric JSON vectors. Exit 0: pass, 1: mismatch, 2: invalid."""
import argparse
import json
import math
import sys
from pathlib import Path


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key: " + key)
        obj[key] = value
    return obj


def read_vectors(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if isinstance(data, list):
        data = {"vector": data}
    if not isinstance(data, dict) or not data:
        raise ValueError("expected a nonempty list or object of lists")
    for key, values in data.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"{key}: expected nonempty numeric list")
        for value in values:
            if type(value) not in (int, float):
                raise ValueError(f"{key}: expected numeric values, not bool/text/nesting")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{key}: non-finite value")
    return data


def compare(reference, observed, atol=0.0, rtol=0.0):
    if any(not math.isfinite(t) or t < 0 for t in (atol, rtol)):
        raise ValueError("tolerances must be finite and >= 0")
    if reference.keys() != observed.keys():
        return {"passed": False, "reason": "key_set_mismatch",
                "missing": sorted(reference.keys() - observed.keys()),
                "extra": sorted(observed.keys() - reference.keys())}
    total = 0
    failures = 0
    examples = []
    for key, expected in reference.items():
        actual = observed[key]
        if len(expected) != len(actual):
            return {"passed": False, "reason": "length_mismatch", "key": key,
                    "expected_length": len(expected), "observed_length": len(actual)}
        for index, (ref, got) in enumerate(zip(expected, actual)):
            total += 1
            if atol == 0 and rtol == 0:
                matched = (ref == got)  # preserve arbitrary-precision integer equality
            else:
                error = abs(got - ref)
                threshold = atol + rtol * abs(ref)
                if not math.isfinite(error) or not math.isfinite(threshold):
                    raise ValueError("tolerance arithmetic overflow; rescale data or use exact integer comparison")
                matched = error <= threshold
            if not matched:
                failures += 1
                if len(examples) < 20:
                    examples.append({"key": key, "index": index, "reference": ref, "observed": got})
    return {"passed": failures == 0, "compared_values": total,
            "mismatches": failures, "atol": atol, "rtol": rtol,
            "first_mismatches": examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference")
    parser.add_argument("observed")
    parser.add_argument("--atol", type=float, default=0.0)
    parser.add_argument("--rtol", type=float, default=0.0)
    args = parser.parse_args()
    try:
        result = compare(read_vectors(args.reference), read_vectors(args.observed), args.atol, args.rtol)
    except (OSError, ValueError, OverflowError) as exc:
        print(json.dumps({"passed": False, "input_error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
