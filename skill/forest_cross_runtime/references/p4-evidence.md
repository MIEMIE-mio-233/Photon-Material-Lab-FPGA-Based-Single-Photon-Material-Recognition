# 跨环境示例与P4项目证据（2026-10-17）

demo_sensor_forest.py采用5个特征、3个数值标签、独立合成测试样本，比较原生与便携森林，并补阈值邻域输入。电脑与P4各自训练后均在各自环境内保持一致。两端独立训练不要求同一参数或同一编号。

另外将电脑同一份portable JSON、108行特征和参考概率传到P4，只用NumPy执行verify_portable_reference.py，概率最大误差0，标签一致。同一模型跨环境比对的详情及三文件哈希见[validation-20261017.json](validation-20261017.json)。

使用示例（在本技能目录）：

```bash
python scripts/demo_sensor_forest.py --output demo_out
python scripts/verify_portable_reference.py --portable demo_out/forest.portable.json --features demo_out/features.npy --reference demo_out/reference.json --report demo_out/portable_check.json
```

把三个demo_out输入文件复制到另一环境再运行第二条命令；只需NumPy，不需要源sklearn或原生joblib。

TDC项目过去完成8维特征+随机森林的HLS实现、C++/RTL/PL分层验证，原始记录由reference-compare技能保存。相关HLS实现按其特征契约和容量配置使用。既有PL核有64类、128树、16384节点、深度32等容量及特定特征契约。

历史130帧记录评价同一模型的实现一致性，保存其原模型ID和输入。
