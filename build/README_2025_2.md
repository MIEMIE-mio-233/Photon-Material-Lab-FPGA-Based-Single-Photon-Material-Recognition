# Vivado / Vitis 2025.2 构建

## 环境与范围

目标器件为 `xczu4ev-sfvc784-1-i`。使用 Vivado 2025.2、Vitis Unified 2025.2，并安装 Zynq UltraScale+ MPSoC 器件支持及相应许可证。HLS 顶层为 `tdc_accelerator`，目标时钟为 100 MHz。

本入口重建 PL Overlay，包括 RTL、HLS IP、PS Block Design 配置及 bit/HWH。板端 Linux/PYNQ 应用的安装和验证见 `../board/README.md`。SD 卡镜像单独准备。

仓库已有 Overlay 和实现报告由 2020.2 生成。2025.2 入口已于 2026-11-03 完整执行通过：HLS、工程创建、综合、布局布线、bit/HWH 导出及产物检查（`BUILD_COMPLETE`），并复跑一次干净构建确认结果一致。板端功能验收仍待上板执行。干净构建实测：

- 时序：setup WNS +0.058 ns、hold WHS +0.010 ns，全部约束满足；CDC 与 bus skew 报告均无 VIOLATED。
- 资源：LUT 40357/87840、寄存器 48224/175680、BRAM 80/128、DSP 27/728，全部在预算内，低于 2020.2 报告值（新版综合映射差异）。
- 产物：`project/board/overlays/tdc_pynq.bit`、`tdc_pynq.hwh`；HWH 地址 0xA0000000/0xA0040000/0xA0050000 已核对。

相对 2020.2 的脚本适配均源于 2025.2 行为差异：`-version` 查询退出码（loader.bat 固定返回 1）；仓库未随附基础 BD 的 PS 实例 XCI，构建时重建并烤入 PS 配置、VLNV 提升到目录版本（3.5 下配置必须烤入 XCI，事后对单元设置会被还原；SD1 的 2020.2 MIO 路由声明与 UART0 冲突，hwh 不再声明，板卡外设由 PYNQ 镜像引导配置）；BD 嵌套 XCI 不参与顶层 generate_target；HWH 导出路径按 glob 适配。适配按 `tdc_modern_build` 开关隔离，2020.2 源码构建入口按设计保持原行为，未在 2020.2 环境回归。

## 一键执行

打开已配置 AMD 2025.2 工具环境的 PowerShell，在仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build/scripts/build_2025_2.ps1 -WorkDirectory E:\fpga_build\photon_2025_2
```

`WorkDirectory` 为仓库外的空英文目录；每次干净构建使用新目录。源码仓库可保留在中文路径中，工具在英文工作副本内运行。

工具未加入 PATH 时，显式指定启动程序，路径按安装位置填写：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build/scripts/build_2025_2.ps1 `
  -WorkDirectory E:\fpga_build\photon_2025_2 `
  -VivadoCommand D:\AMD\Vivado\2025.2\bin\vivado.bat `
  -HlsCommand D:\AMD\Vitis\2025.2\bin\vitis-run.bat
```

入口分别检查 Vivado 和 Vitis 版本，任一步骤返回错误即停止。Windows 安装目录结构因安装选项而异，以实际 `vivado.bat` 与 `vitis-run.bat` 位置为准。

仅检查所需文件、准备源码副本与输入哈希清单：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build/scripts/build_2025_2.ps1 -WorkDirectory E:\fpga_build\photon_prepare_2025_2 -PrepareOnly
```

`-PrepareOnly` 无需启动 AMD 工具，不代表硬件编译通过。正式构建另选空目录。增加 `-RunCosim` 可在 HLS 综合后运行所附固定向量的 Verilog 协同仿真。

## 构建流程

1. `src/hls/build_hls_2025_2.tcl`：C 仿真、HLS 综合、可选 C/RTL 协同仿真、原生 IP 导出；固定 64 位 AXI master 地址。
2. `build/scripts/create_pynq_project_2025_2.tcl`：检查工具版本，在副本中升级源 XCI 与基础 BD，调用公共脚本创建 PS/PL 工程。PS DDR、MIO 配置沿用仓库中的板卡配置。
3. `build/scripts/build_pynq_bit_2025_2.tcl`：重新综合、导入 TDC 网表、布局布线，检查资源预算、setup/hold 与总线偏斜，导出 bit/HWH。

资源预算沿用工程设置：LUT 不超过 61488、Block RAM Tile 不超过 102、DSP 不超过 86。新版工具若改变资源映射导致超预算，应结合实现报告调整设计并重新验收。

生成目录：

```text
工作目录/
  build_inputs.json                       输入文件及SHA256
  logs/                                   两套工具版本及各阶段日志
  project/build/output/hls/                HLS工程、仿真与综合结果、IP
  project/build/output/vivado/             Vivado工程、综合/布线检查点
  project/build/reports/                   IP升级、资源、时序、CDC报告
  project/board/overlays/tdc_pynq.bit
  project/board/overlays/tdc_pynq.hwh
```

## 上板前核验

- HLS C仿真通过；完整软件/硬件数值比较按 `../sim/README.md` 执行。
- 核对 HLS 生成的寄存器映射：hist/model/result 指针偏移分别为 `0x10/0x1c/0x28`；feature_count、timing_reference_bin 为 `0x5c/0x64`。
- 核对 HWH 地址：直方图 `0xA0000000`、采集控制 `0xA0040000`、HLS核 `0xA0050000`；其余接口约定见 `../board/overlays/overlay_contract.json`。
- 检查 `timing_summary.rpt`、`utilization.rpt`、`cdc.rpt`、`bus_skew.rpt`，同时检查未约束端点与I/O告警。
- 使用同次构建的 bit/HWH，先比较同一输入帧、同一模型的 PS/PL 特征及预测，再验证真实采集、TDC校准、DAC和比较阈值控制。

TDC网表位于 `src/netlist/time_merge_eval.dcp`。导入层级为 `u_top_tdc/u_time_merge`。

正式发布时，将验证通过的 bit/HWH 成对复制到 `board/overlays`，同步实现报告、工具版本说明和 `report/release_manifest.json`。构建入口的 `BUILD_COMPLETE` 表示编译及脚本检查完成，板端功能验收另行记录。

## 官方参考

- [AMD 2025.2 HLS命令行与Tcl入口](https://docs.amd.com/r/2025.2-English/ug1399-vitis-hls/vitis-v-and-vitis-run-Commands)
- [AMD 2025.2 upgrade_ip](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/upgrade_ip)
