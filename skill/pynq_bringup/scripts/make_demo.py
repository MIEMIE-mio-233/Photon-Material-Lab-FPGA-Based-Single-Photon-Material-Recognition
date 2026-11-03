#!/usr/bin/env python3
"""生成非TDC接口校验样例。bit是不可烧录的合成文件，只用于离线检查。"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bit = args.output / "vector_sum.bit"
    hwh = args.output / "vector_sum.hwh"
    bit.write_bytes(b"SYNTHETIC METADATA FIXTURE - NOT A PROGRAMMABLE BITSTREAM\n")
    hwh.write_text('''<?xml version="1.0"?>
<EDKSYSTEM><SYSTEMINFO ARCH="zynq" DEVICE="xc7z020"/>
<MODULES><MODULE INSTANCE="vector_sum" FULLNAME="/vector_sum" VLNV="example.org:hls:vector_sum:1.0">
<REGISTERS>
<REGISTER NAME="ID"><PROPERTY NAME="ADDRESS_OFFSET" VALUE="0"/><PROPERTY NAME="SIZE" VALUE="32"/></REGISTER>
<REGISTER NAME="VERSION"><PROPERTY NAME="ADDRESS_OFFSET" VALUE="4"/><PROPERTY NAME="SIZE" VALUE="32"/></REGISTER>
<REGISTER NAME="RESULT"><PROPERTY NAME="ADDRESS_OFFSET" VALUE="16"/><PROPERTY NAME="SIZE" VALUE="32"/></REGISTER>
</REGISTERS></MODULE></MODULES>
<MEMRANGES><MEMRANGE INSTANCE="vector_sum" BASEVALUE="0x43c00000" HIGHVALUE="0x43c0ffff"
 MASTERBUSINTERFACE="M_AXI_GP0" SLAVEBUSINTERFACE="s_axi_control"/></MEMRANGES></EDKSYSTEM>
''', encoding="utf-8")
    contract = {"schema_version": 1, "synthetic": True,
        "system": {"ARCH": "zynq", "DEVICE": "xc7z020"},
        "artifacts": {kind: {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for kind, p in (("bit", bit), ("hwh", hwh))},
        "ips": {"vector_sum": {"vlnv": "example.org:hls:vector_sum:1.0",
            "address": {"base": "0x43c00000", "min_bytes": 65536, "master": "M_AXI_GP0", "interface": "s_axi_control"},
            "registers": {"ID": {"offset": 0, "bits": 32}, "VERSION": {"offset": 4}, "RESULT": {"offset": 16}},
            "probes": [{"offset": 0, "value": "0x56454331", "safe_read_only": True}]}}}
    (args.output / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    print(json.dumps({"synthetic": True, "hardware_executed": False, "contract": str(args.output / "contract.json")}))


if __name__ == "__main__":
    main()
