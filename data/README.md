# 数据与模型

dataset包含88个批次、1580帧：1400帧材质数据和180帧背景。每个run目录保留manifest、采集配置和原始uint32 NPY。原始帧已与源快照逐文件核对。

models/versions提供随机森林、MLP和CNN各一个有效版本，active.json指定随机森林。决策树可通过训练入口生成版本。各版本引用公共批次，保存自身参数、类别顺序、特征配置、评价与图表快照。

manifest中的csv_path记录帧文件路径，可指向.npy。frame_index、material_id、specimen_id、distance_cm、illumination、experiment_round和sample_kind共同描述样品及采集条件。背景数据用于辅助观察，材质训练读取带有效材质标签的帧。

当前21种材质标签，每类50～100帧，覆盖不同距离和光照条件。连续帧具有相关性，保存报告中的同批次留出准确率用于评价重复测量可分性。独立实物评价按实物分组另采测试数据。

跨sklearn版本使用同前缀portable.json及共享特征代码。joblib加载限于可信来源和兼容环境。算法数值验证见sim/results/cpp_parity.json与sim/results/pl_history_parity.json。
