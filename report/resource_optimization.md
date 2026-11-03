# 共享计算单元的资源优化对比

## 对照条件

采用同一版tdc_accelerator源码构造受控实验，比较卷积与全连接分别实现乘加函数、以及当前共用dense_layer函数两种结构。测试保持模型计算、double/float精度、接口、数组容量、器件和时钟约束一致。独立函数方案为本次重建的比较基线。两版对同一CNN历史直方图进行C仿真和C/RTL协同仿真，88个结果槽均满足绝对误差1e-12。

工具为Vitis HLS 2020.2，器件XCZU4EV-SFVC784-1-I，目标周期10 ns，时钟不确定度2.7 ns；统计范围为HLS顶层综合估算。

## 资源优化前后对比

| 资源 | 独立乘加函数（对照） | 共享乘加函数（当前结构） | 减少量 | 降幅 |
| --- | ---: | ---: | ---: | ---: |
| LUT | 35,403 | 32,547 | 2,856 | 8.07% |
| FF | 20,034 | 17,031 | 3,003 | 14.99% |
| DSP | 54 | 40 | 14 | 25.93% |
| BRAM_18K | 42 | 36 | 6 | 14.29% |

共享结构将卷积和全连接的运算请求分时送入同一函数实例，减少算术逻辑及相关存储开销。层级报告中，对照方案同时出现convolution_layer和dense_layer；当前结构只有dense_layer实例。功能实例变化还影响HLS的循环调度与存储实现，因此表中数值代表整体结构的综合结果。

两版HLS周期估算均为13.838 ns，目标II未全部满足。同一帧RTL延迟由独立结构的71,836拍增加到共享结构的114,828拍，增加59.85%；共享以更长的串行计算换取资源节省。单事务仿真未测定II，整机吞吐需连续事务和实际访存测试。2020.2对原源码ALLOCATION参数顺序有警告，实例复用以生成报告核验。

## 当前整板资源

| 资源 | 已布局布线用量 | 器件容量 | 占用率 |
| --- | ---: | ---: | ---: |
| LUT | 44,031 | 87,840 | 50.13% |
| FF | 51,026 | 175,680 | 29.04% |
| Block RAM Tile | 82 | 128 | 64.06% |
| DSP | 35 | 728 | 4.81% |

整板统计来自2026-10-24 Vivado 2020.2 Routed报告，包含TDC、控制和接口等模块。它与HLS估算的阶段、优化过程及BRAM单位不同。已分析路径WNS为0.345 ns；完整约束覆盖需结合时序报告中的未约束路径条目审查。

## 复现与证据

- [实验生成及运行方法](../build/experiments/dense_sharing/README.md)
- [机器可读对比](../build/reports/dense_sharing/comparison.json)、[比较契约](../build/reports/dense_sharing/contract.json)
- [独立方案HLS报告](../build/reports/dense_sharing/separate_tdc_accelerator_csynth.rpt)、[共享方案HLS报告](../build/reports/dense_sharing/shared_tdc_accelerator_csynth.rpt)
- [共享层级](../build/reports/dense_sharing/shared_dense_infer_csynth.rpt)、[独立层级](../build/reports/dense_sharing/separate_dense_infer_csynth.rpt)
- [当前整板资源](../build/reports/utilization.rpt)、[当前整板时序](../build/reports/timing_summary.rpt)
- [独立方案C仿真](../sim/results/rtl_20261103/separate_csim.log)、[共享方案C仿真](../sim/results/rtl_20261103/shared_csim.log)

本次实验只在独立工作目录运行，发布bit/HWH与部署源码保持原版本。2025.2脚本迁移的完整工具构建结论由对应版本实际运行结果给出。

[C/RTL协同仿真结果](../sim/results/rtl_20261103/cosim_summary.json)保留两版周期数、输出容差及DSP原语OPMODE告警计数；完整日志随结果归档。
