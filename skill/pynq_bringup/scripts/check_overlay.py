#!/usr/bin/env python3
"""检查bit/HWH文件及接口契约；默认离线，--read-live也只读、不下载、不启动IP。"""
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def integer(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not an address")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError("expected integer or hex string")
    return int(value, 0)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inventory(path):
    root = ET.parse(str(path)).getroot()
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    system = root.find(".//SYSTEMINFO")
    if system is None:
        raise ValueError("HWH has no SYSTEMINFO")
    modules = {}
    for module in root.findall(".//MODULE"):
        name = module.get("FULLNAME", module.get("INSTANCE", "")).strip("/")
        if not name or name in modules:
            raise ValueError("missing or ambiguous module path: " + name)
        registers = {}
        for reg in module.findall(".//REGISTER"):
            properties = {p.get("NAME"): p.get("VALUE") for p in reg.findall("./PROPERTY")}
            if "ADDRESS_OFFSET" in properties:
                item = {"offset": integer(properties["ADDRESS_OFFSET"])}
                if "SIZE" in properties:
                    item["bits"] = integer(properties["SIZE"])
                key = reg.get("NAME")
                if key in registers and registers[key] != item:
                    raise ValueError("ambiguous register: " + name + "/" + key)
                registers[key] = item
        modules[name] = {"vlnv": module.get("VLNV"), "instance": module.get("INSTANCE"),
                         "registers": registers, "ranges": []}
    for region in root.findall(".//MEMRANGE"):
        matching = [v for k, v in modules.items() if k == region.get("INSTANCE") or
                    v["instance"] == region.get("INSTANCE")]
        if not matching:
            continue
        if len(matching) > 1:
            raise ValueError("ambiguous MEMRANGE instance: " + region.get("INSTANCE", ""))
        base, high = integer(region.get("BASEVALUE")), integer(region.get("HIGHVALUE"))
        if base < 0 or high < base:
            raise ValueError("invalid HWH address range")
        item = {"base": base, "bytes": high - base + 1,
                "master": region.get("MASTERBUSINTERFACE"), "interface": region.get("SLAVEBUSINTERFACE")}
        if item not in matching[0]["ranges"]:
            matching[0]["ranges"].append(item)
    return {"system": dict(system.attrib), "ips": modules}


def validate(contract, directory):
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported contract schema")
    paths = {}
    for kind in ("bit", "hwh"):
        item = contract["artifacts"][kind]
        path = (directory / item["path"]).resolve()
        expected = item["sha256"]
        if not isinstance(expected, str) or not re.fullmatch("[0-9a-fA-F]{64}", expected):
            raise ValueError("missing SHA256: " + kind)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("missing/empty artifact: " + kind)
        if digest(path) != expected.lower():
            raise ValueError("SHA256 mismatch: " + kind)
        paths[kind] = path
    if paths["bit"].suffix.lower() != ".bit" or paths["hwh"].suffix.lower() != ".hwh" or paths["bit"].stem != paths["hwh"].stem:
        raise ValueError("expected same-basename .bit/.hwh pair")
    info = inventory(paths["hwh"])
    for key, expected in contract.get("system", {}).items():
        if info["system"].get(key) != expected:
            raise ValueError("system mismatch: " + key)
    if not isinstance(contract.get("ips"), dict) or not contract["ips"]:
        raise ValueError("contract needs at least one IP")
    checked = {}
    for name, spec in contract["ips"].items():
        if name not in info["ips"]:
            raise ValueError("missing IP: " + name)
        actual = info["ips"][name]
        if not spec.get("vlnv") or actual["vlnv"] != spec["vlnv"]:
            raise ValueError("VLNV mismatch: " + name)
        address = spec["address"]
        base, size = integer(address["base"]), integer(address["min_bytes"])
        if base < 0 or base % 4 or size < 4:
            raise ValueError("invalid required address span")
        spans = [r for r in actual["ranges"] if r["base"] == base and r["bytes"] >= size and
                 all(address[k] == r[k] for k in ("master", "interface") if k in address)]
        if not spans:
            raise ValueError("address span/master/interface mismatch: " + name)
        for reg, expected in spec.get("registers", {}).items():
            got = actual["registers"].get(reg, {})
            if any(got.get(k) != integer(v) for k, v in expected.items()):
                raise ValueError("register mismatch: " + name + "/" + reg)
        for probe in spec.get("probes", []):
            if "value" not in probe:
                raise ValueError("probe requires an expected value")
            offset = integer(probe["offset"])
            if offset < 0 or offset % 4 or offset + 4 > size or probe.get("safe_read_only") is not True:
                raise ValueError("probe needs aligned in-range offset and explicit safe_read_only")
            for key in ("value", "mask"):
                number = integer(probe.get(key, 0xffffffff))
                if not 0 <= number <= 0xffffffff:
                    raise ValueError("probe value/mask must be uint32")
        checked[name] = {"base": base, "bytes": size, "registers_checked": len(spec.get("registers", {}))}
    return paths, {"passed": True, "scope": "artifact and metadata contract; no hardware access",
                   "synthetic": bool(contract.get("synthetic", False)), "system": info["system"], "checked_ips": checked}


def read_live(contract, paths, report):
    if contract.get("synthetic"):
        raise ValueError("synthetic demo artifacts cannot be used for live probing")
    if not any(spec.get("probes") for spec in contract["ips"].values()):
        raise ValueError("no explicit read-only probes")
    from pynq import PL, MMIO
    if not PL.bitfile_name or Path(PL.bitfile_name).resolve() != paths["bit"]:
        raise ValueError("requested bitfile is not the loaded PL.bitfile_name")
    values = []
    for name, spec in contract["ips"].items():
        if not spec.get("probes"):
            continue
        desc = PL.ip_dict.get(name)
        base, size = integer(spec["address"]["base"]), integer(spec["address"]["min_bytes"])
        if not desc or desc.get("phys_addr") != base or desc.get("addr_range", 0) < size or desc.get("type") != spec["vlnv"]:
            raise ValueError("loaded IP metadata mismatch: " + name)
        mmio = MMIO(base, size)
        for probe in spec["probes"]:
            offset, expected = integer(probe["offset"]), integer(probe["value"])
            mask = integer(probe.get("mask", 0xffffffff))
            actual = mmio.read(offset)
            if actual & mask != expected & mask:
                raise ValueError("live readback mismatch: {}+0x{:x}".format(name, offset))
            values.append({"ip": name, "offset": offset, "value": actual})
    report.update(scope="artifact/metadata plus explicitly safe live reads; no writes or download", live_reads=values,
                  identity_limit="loaded path and IP metadata; not a digest of FPGA configuration memory")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--contract", type=Path)
    group.add_argument("--inventory", type=Path)
    parser.add_argument("--read-live", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.inventory:
            if args.read_live:
                raise ValueError("--read-live requires a contract")
            report = dict(inventory(args.inventory), passed=True, scope="HWH inventory only; no hardware access")
        else:
            contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
            paths, report = validate(contract, args.contract.resolve().parent)
            if args.read_live:
                read_live(contract, paths, report)
        code = 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, AttributeError, RuntimeError, ET.ParseError) as exc:
        report, code = {"passed": False, "error": str(exc)}, 2
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
