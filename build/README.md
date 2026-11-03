# 硬件构建

2025.2构建入口、命令与验收步骤见[2025.2构建说明](README_2025_2.md)。

## 工具版本与入口

| 工具版本 | 构建入口 | 验证记录 |
| --- | --- | --- |
| Vivado / Vitis HLS 2020.2 | [仓库原始构建流程](../README.md) | 已归档Overlay、实现报告与板端验证 |
| Vivado / Vitis Unified 2025.2 | [一键构建说明](README_2025_2.md) | 交付版本已完成完整编译及干净构建复跑，板端验收待执行 |

目标器件为`xczu4ev-sfvc784-1-i`。2025.2入口在独立英文工作目录中复制源码、运行HLS、创建Vivado工程、执行综合与布局布线，并导出成对bit/HWH。参数接口与板端核验步骤见对应版本说明。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build/scripts/build_2025_2.ps1 -WorkDirectory D:\fpga_build\photon_2025_2
```

准备源码和输入哈希可加`-PrepareOnly`，执行C/RTL协同仿真可加`-RunCosim`。2020.2使用原始HLS构建及IP封装入口。

## 资源结构对照

[共享乘加实验](experiments/dense_sharing/README.md)提供独立工作目录生成器、HLS运行脚本和同帧验证方法。[结果表](../report/resource_optimization.md)给出资源节省及RTL周期代价。
