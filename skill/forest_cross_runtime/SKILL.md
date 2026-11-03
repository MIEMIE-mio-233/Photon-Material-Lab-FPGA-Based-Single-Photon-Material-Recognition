---
name: forest-cross-runtime
description: 迁移单输出随机森林到不同Python/sklearn环境，以便携节点参数核验类别和概率，并接入训练、连续识别及MATLAB接口。
---

# 随机森林跨运行时迁移

保证同输入、同特征顺序与同参数的类别及概率一致。首先检查实际调用模型、classes_、树数、模型编号和训练报告。

## 应用契约

训练和识别共用特征代码，元数据保存特征顺序、版本、选峰、归一化和采集参数。类别数取模型classes_，输出分数按其顺序配对。森林图表使用特征重要性与混淆矩阵，应用文件名和JSON字段保持接口兼容。

## 便携参数

可信joblib在兼容环境加载；跨版本可在目标环境重训，或从源环境导出节点表。同一模型比较时同步joblib、portable JSON、报告与特征代码，并核对编号。

节点表包含左右子节点、特征号、阈值及叶概率。输入按sklearn转换为float32，分支使用<=，输出取各树叶概率平均。tree.value按节点类别总和归一化。通用工具支持单输出、有限数值的RandomForestClassifier。

[forest_portable.py](scripts/forest_portable.py)支持原生模型及含model的字典，兼容tdc_random_forest_v1格式，命令见[参数契约](references/portable-contract.md)。多输出、回归及NaN路由按目标估计器另实现。

## 验证

1. 比较原始帧、峰位、面积、宽度和特征顺序，明确整数与浮点误差规则。
2. 源环境比较原生与便携概率，加入float32阈值邻域；目标环境复用同一模型和输入。
3. 覆盖单帧、连续输入、JSON stdout、退出码及MATLAB等实际入口。
4. 按实物或批次评价，连续帧留出标为重复测量诊断。

双峰、旧运行时及中文路径案例见[历史案例](references/tdc-case.md)，工具核验见[结果](references/helper-validation.json)。

在技能目录运行`python scripts/demo_sensor_forest.py --output demo_out`，生成五特征、三类合成样本，完成节点导出、参考概率与阈值邻域比较。P4数值记录见[板端案例](references/p4-evidence.md)。
