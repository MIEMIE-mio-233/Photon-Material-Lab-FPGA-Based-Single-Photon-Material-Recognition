# 共享乘加单元资源对照

当前加速器让CNN卷积与全连接调用同一个dense_layer函数。对照版本从相同源码自动生成：复制卷积侧函数为convolution_layer并保持非内联，其余数值计算、数据类型、数组容量与顶层接口一致。该版本用于隔离结构因素，并非历史部署版本。

在仓库根目录执行：

```powershell
python build/experiments/dense_sharing/prepare.py --work E:\fpga_ablation
cd E:\fpga_ablation
vitis_hls -f run.tcl
```

2025.2使用`vitis-run --mode hls --tcl run.tcl`。工作目录必须为空且路径为ASCII；生成inputs.json、两版kernel.cpp及测试向量。脚本进行C仿真和HLS综合；需要C/RTL协同仿真时，在对应project/solution1上运行`cosim_design -rtl verilog -tool xsim -trace_level none`，并设置TDC_TEST_DATA_DIR为fixtures绝对路径。

2026-11-03已在Vitis HLS 2020.2完成两版综合及C/RTL协同仿真实验，器件xczu4ev-sfvc784-1-i，目标周期10 ns，不确定度2.7 ns。完整表见[资源优化分析](../../../report/resource_optimization.md)。综合报告位于[结果目录](../../reports/dense_sharing)，数值一致性与RTL测试位于[仿真目录](../../../sim/results/rtl_20261103)。

2020.2对原源码的ALLOCATION参数顺序发出警告；层级报告确认共享版本实际只有一个dense_layer实例。因此本次量化的是生成电路的函数复用效果。HLS目标II未全部满足、周期估算13.838 ns均保留于报告。资源估算与现有整板routed资源分别统计。
