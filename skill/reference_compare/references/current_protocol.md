# 九维与CNN结果协议

逐层比较选峰、整数窗口、float32边界、模型基线、标准化、卷积池化、类别顺序及分数归一化。协议3按88槽布局解析，预留槽按核定义处理。

[C++记录](../../../sim/results/cpp_parity.json)包含四种格式各120帧，[板上历史回放](../../../sim/results/pl_history_parity.json)包含三种格式各120帧。峰位和特征按精确规则比较，double分数按预先定义的容差核验。

[板端推理核验](../../../sim/results/pl_history_parity.json)记录模型、特征及分类分数误差。CNN输入和88槽参考向量用于后续RTL协同仿真。
