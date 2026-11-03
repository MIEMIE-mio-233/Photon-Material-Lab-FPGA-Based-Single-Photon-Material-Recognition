# 多阶段清单与非TDC示例

在本技能目录运行（示例需要NumPy，比对器本身仅需标准库）：

```bash
python scripts/make_demo.py --output demo_out
python scripts/compare_stages.py demo_out/manifest.json --report demo_out/parity.json
```

示例分别执行Python整数FIR与NumPy int64卷积，输入含大于2^53的整数，全部按精确整数比较；provenance记录hardware_executed=false。将numpy_vector.json中一个整数加1应返回1。使用本机verify_bundle.py可自动做此失败演练。

schema_version=1，case为案例标识，provenance至少含kind及布尔hardware_executed。comparisons每项有唯一name、reference、observed，相对路径按清单目录解析；可选tolerances={"features":{"atol":0.000001,"rtol":0.000001}}。输入JSON示例{"features":[0.1,0.2],"indices":[1,2]}，其中indices仍默认精确。

每个比较保存两个输入文件哈希与逐字段失配位置。各阶段容差按预先定义的数值预算设置。

最小示例比较两种软件实现；C++、RTL和板端输出由目标算子的对应执行过程生成。
