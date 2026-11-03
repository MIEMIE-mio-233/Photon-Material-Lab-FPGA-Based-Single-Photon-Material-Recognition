# 分层验证来源与边界（2026-10-17）

本项目的浮点滑动统计在不同NumPy/SciPy环境下曾造成半高阈值附近1bin差异；单看最终标签容易漏掉特征不同。将选峰与窗口计算统一后，再把特征float32量化、树阈值分支和叶概率平均逐层核验。

validation-20261017.json保留来源文件SHA256和原报告：C++算法130真实历史帧及额外用例；HLS C/RTL协同仿真1帧、80个输出字；旧Overlay实际PL回放130帧；最新双DAC Overlay另有1帧PS/PL回归。每份记录保留model_id、bit版本和计时范围。

旧130帧回放记录calibrated=false，对应文件输入与当时模型。真实采集另检查校准状态及事件输入。

FIR分别运行Python标量和NumPy卷积，在电脑/P4均精确一致；大整数改1可检测，NaN/bool/空输入/重复键/容差字段拼错均被拒绝。该FIR例只执行软件，provenance明确hardware_executed=false。真实硬件黄金结果须由使用者自己的C++、仿真或板测产生。
