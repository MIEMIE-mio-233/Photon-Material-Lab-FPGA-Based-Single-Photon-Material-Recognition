# 便携随机森林契约与辅助程序

scripts/forest_portable.py 兼容 Python 3.6；便携推理只需 NumPy。导出和原生核验还需与源模型相容的 sklearn/joblib。只加载当前任务提供的可信 joblib。

## 导出与验证

```bash
python scripts/forest_portable.py export --native material_model.joblib --output exported.portable.json
python scripts/forest_portable.py verify --native material_model.joblib --portable exported.portable.json --features features.npz --report verification.json
```

features.npz 使用名为 X 的二维特征数组，也接受二维 .npy。该数组由共享特征代码生成。默认增加最多 512 个阈值附近输入；这些输入用于补充阈值附近的数值检查。`--boundary-limit 0` 只核验提供的特征，默认概率绝对容差 1e-12；报告记录样本数、最大误差和类别一致性。

退出码：成功 0；模型概率/类别不一致 1；输入或模型格式错误 2。脚本使用独立输出路径测试，不覆盖应用现有模型；导出时显式提供的输出地址属于调用者选择。

## JSON 格式

- format：tdc_random_forest_v1，沿用当前项目的格式名称；算法并不依赖 TDC 波形。
- class_names：真实全局类别顺序，支持字符串或数值标签；单输出。
- n_features：输入特征数；兼容旧文件时可由 feature_names 长度确定。
- trees：每棵树有 left、right、feature、threshold、probabilities 等长数组。叶节点左右子节点均为 -1。
- probabilities[node]：该节点按类别顺序归一化的概率。推理平均每棵树抵达叶节点的概率。
- model_id、model_type、library_versions：来源标识。字典模型内已有这些字段时导出保留；裸模型导出补充来源字段。

应用层还应记录并校验 feature_names、feature_version、feature_settings、采集 settings 等。辅助导出保留字典元数据，提取逻辑通过原始帧到特征检查。便携JSON独立于sklearn序列化布局，支持所述单输出森林。

## 移植到应用

保留模型 classes_ 到 class_scores 的映射。加载先检查模型/报告编号和特征配置，再按运行库版本选择 joblib 或便携 JSON。MATLAB 等调用只读取 stdout 的单行 JSON；提示、诊断和错误写 stderr，失败返回非零。中文路径可输出 ensure_ascii=True 的 JSON，jsondecode 后仍得到原始中文。

导出对多输出、非森林模型明确拒绝。推理校验输入有限、维度正确；节点表检查长度、叶结构、索引及归一化概率，遍历设节点数上限，循环结构不会无限运行。
