---
name: reference-compare
description: 逐字段比较软件、C++、RTL或板端有限数值向量，记录输入哈希、显式容差及CI退出码。
---

# 分阶段数值对照

固定输入、参数、单位、缩放、溢出及舍入规则，沿原始计数、特征、分支、分数和应用结果逐层比较。

## 工具

[compare_vectors.py](scripts/compare_vectors.py)比较数字JSON列表或键到列表的对象。键与长度一致，默认精确比较，Python大整数保留整数表示。

```bash
python scripts/compare_vectors.py reference.json observed.json
python scripts/compare_stages.py manifest.json --report parity.json
```

[compare_stages.py](scripts/compare_stages.py)支持字段级atol/rtol及输入SHA256。规则为abs(observed-reference)<=atol+rtol*abs(reference)，未指定容差的字段精确比较。退出码0通过、1失配、2输入无效。

峰位、bin数和类别索引采用精确比较，浮点误差预算依据算法定义。NaN、无穷、布尔、重复键、空向量及不支持的嵌套结构返回输入错误。

## 分层记录

先核对软件参考，再比较C++、RTL协同仿真与板上输出。每层保存输入、工具、模型、bit版本、容差和失配位置。树输入float32及阈值邻域作为独立边界用例。

provenance记录调用者提供的数据来源；合成输入、历史帧和真实采集分别标识。总线、时序及光学性能通过对应测试记录。

FIR示例见[多阶段清单](references/multistage.md)，硬件案例见[验证记录](references/validated-cases.md)，当前88槽协议见[结果定义](references/current_protocol.md)。
