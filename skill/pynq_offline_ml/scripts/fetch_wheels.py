#!/usr/bin/env python3
"""按清单下载并校验离线wheel；不安装、不修改解释器。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.request


def checksum(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        items = json.loads(args.manifest.read_text(encoding="utf-8-sig"))["packages"]
        if not isinstance(items, list) or not items:
            raise ValueError("nonempty packages required")
        names = set()
        for item in items:
            name = item["filename"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", name) or name in names:
                raise ValueError("invalid/duplicate wheel filename")
            names.add(name)
            if not item["url"].startswith("https://") or not re.fullmatch("[a-f0-9]{64}", item["sha256"]):
                raise ValueError("HTTPS URL and SHA256 required")
        args.output.mkdir(parents=True, exist_ok=True)
        results = []
        for item in items:
            destination = args.output / item["filename"]
            if destination.exists():
                if checksum(destination) != item["sha256"]:
                    raise ValueError("existing wheel checksum mismatch; file retained: " + item["filename"])
                results.append({"filename": item["filename"], "cached": True})
                continue
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=str(args.output), prefix="wheel_fetch_", delete=False) as stream:
                    temporary = Path(stream.name)
                    with urllib.request.urlopen(item["url"], timeout=30) as response:
                        for block in iter(lambda: response.read(1024 * 1024), b""):
                            stream.write(block)
                if checksum(temporary) != item["sha256"]:
                    raise ValueError("download checksum mismatch: " + item["filename"])
                temporary.replace(destination)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            results.append({"filename": item["filename"], "cached": False})
        print(json.dumps({"passed": True, "installed": False, "packages": results}))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
