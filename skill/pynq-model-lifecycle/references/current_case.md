# 多模型版本管理案例

模型版本保存类别、特征、基线及参数，训练按批次选择，PS和PL按需装载当前版本。共享RAM与特征核供各算法复用，MLP和CNN共享乘加及2048个double缓存。当前树核最多64类、128树和16384节点。

CNN输入256点局部波形与九维统计量，PL输出logits，PS执行归一化。参数使用double，特征经过float32边界。兼容参数切换复用已加载Overlay。

- [驱动](../../../src/ps/pl_runtime.py)、[版本库](../../../src/ps/model_registry.py)、[特征契约](../../../src/ps/feature_contract.py)。
- [C++对照](../../../sim/results/cpp_parity.json)：四种格式各120历史帧。
- [板上历史回放](../../../sim/results/pl_history_parity.json)：MLP、九维森林和CNN各120帧，模型ID随记录保存。
- [板端推理核验](../../../sim/results/pl_history_parity.json)：历史帧的特征与分类分数对照。
- [版本测试](../../../src/ps/tests/test_model_versions.py)：归档、启用、删除及内存状态。

性能配对采用相同计算范围，独立样品评价按实物分组开展。
