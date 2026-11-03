# 分层验证

## 软件检查

在仓库根目录执行`python sim/run_checks.py`。检查使用临时样本，覆盖特征、参数、模型版本与网页状态。Node.js用于前端测试；检查产生的空运行目录可在完成后清理。

## RTL与HLS

Vivado2020.2加入PATH并设置XILINX_VIVADO后执行：

```bash
vivado -mode batch -source sim/scripts/test_bridge.tcl
vivado -mode batch -source sim/scripts/test_tof.tcl
vivado -mode batch -source sim/scripts/test_dual_dac.tcl
```

HLS先运行src/hls/build_hls.tcl综合，再执行`vitis_hls -f src/hls/check_rtl.tcl`。hls目录提供真实历史帧、CNN参数及88槽参考输出，已完成Python/C++向量核对，供RTL协同仿真使用。

## 结果索引

| 文件 | 验证内容 |
| --- | --- |
| results/software_checks.json | 软件与网页回归 |
| results/cpp_parity.json | Python与C++算法数值对照 |
| results/pl_history_parity.json | 板上历史帧推理对照 |
| results/overlay_check.json | 文件、地址与元数据契约 |

各记录保留对应模型、输入和日期。性能比较按相同计算范围配对；光学采集测试另记录触发累积、完整率及实际条件。

## 采集展示与目录缓存

test_catalog_cache.py覆盖变化批次重建、删除、路径边界和索引锁占用时的状态读取；test_capture_refresh.js覆盖采集进度与列表刷新分离。这两项通过统一入口sim/run_checks.py运行。

[板端性能记录](results/capture_display_performance.json)给出HTTP采样与5帧真实采集的分段计时。使用正在运行的网页服务，可将只读HTTP测量结果保存到仓库外：

```bash
python skill/pynq_pipeline_profiler/scripts/profile_http.py --url http://board:8080 --repeats 5 --output /tmp/web_api_profile.json
```

工具不启动采集。首次索引建立和模型准备分别观察；网页前端绘制时间需由网页前端自身计时。

## 当前源码仿真归档

2026-11-03在独立源码副本运行Vivado/Vitis HLS 2020.2，发布RTL与HLS文件保持一致：

| 归档 | 覆盖内容 | 结果 |
| --- | --- | --- |
| [RTL摘要](results/rtl_20261103/summary.json) | AXI桥、快照、双DAC、跨周期触发4组 | 全部通过 |
| [C仿真](results/rtl_20261103/shared_csim.log) | 共享结构历史CNN帧，88槽参考 | 通过 |
| [结构对照C仿真](results/rtl_20261103/separate_csim.log) | 独立函数，同一输入和参考 | 通过 |
| [C/RTL摘要](results/rtl_20261103/cosim_summary.json) | 两版同帧RTL比对，误差阈值1e-12 | 全部通过 |

每组RTL记录顶层、源码SHA256及日志SHA256。协同仿真保留原语OPMODE告警和单事务II不可测说明；单帧结论限定于所附CNN向量。测试没有连接板卡或驱动光源。

使用仓库外的源副本执行原有三个Tcl入口；新增周期触发入口为`vivado -mode batch -source sim/scripts/test_trigger.tcl`。HLS共享/独立结构的重放方法见[实验说明](../build/experiments/dense_sharing/README.md)。
