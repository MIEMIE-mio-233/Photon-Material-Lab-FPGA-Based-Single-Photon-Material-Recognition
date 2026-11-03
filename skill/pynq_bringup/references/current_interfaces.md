# 当前接口

控制桥版本5采用低有效跨周期窗口；分类输入为九维，CNN结果协议3包含88槽。检查覆盖地址、时钟、维数、基线寄存器、结果布局及客户端schema，文件核验见[元数据记录](../../../sim/results/overlay_check.json)。

网页启动沿用已加载Overlay，硬件重配后按复位默认检查输出。软件默认、bit复位默认和运行接管分别定义。

输出语义见[波形契约](../../waveform-control-contract/SKILL.md)，参数切换见[模型生命周期](../../pynq-model-lifecycle/SKILL.md)。当前硬件配置对应XCZU4EV。
