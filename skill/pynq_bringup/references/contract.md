# 离线接口契约与非TDC示例

在本技能目录运行：

```bash
python scripts/make_demo.py --output demo_out
python scripts/check_overlay.py --contract demo_out/contract.json --report demo_out/check.json
```

示例为向量求和IP的合成元数据，采用Zynq-7000地址布局。bit占位文件和HWH夹具仅用于离线检查，硬件加载使用实际构建产物。

schema_version=1。artifacts.bit/hwh各有path、sha256；相对路径按契约文件所在目录解析。system是HWH SYSTEMINFO中要精确匹配的属性。ips以MODULE完整路径为键，vlnv精确匹配；address包含base、min_bytes，可选master、interface，用于区分PS与HLS等不同主接口看到的地址。

registers以寄存器名为键，offset、bits从HWH REGISTER属性检查。省略registers时跳过该IP的寄存器离线检查。probes中offset为32位对齐地址，value为期望值，mask可选；safe_read_only=true由接口设计者根据寄存器语义配置。

本工具支持已测试Vivado2020.2 EDKSYSTEM XML结构（含默认命名空间）。其他版本先inventory后核对实际XML；不支持XSA、DTBO、partial reconfiguration及运行中互不兼容的驱动。返回0表示所选检查通过，2表示输入、契约或回读失败。

失败演练：改错VLNV、地址范围、寄存器偏移、文件哈希，检查必须返回非零。Overlay加载与接口契约分别核验。
