---
name: hls-verification-archive
description: 将HLS C仿真、RTL协同仿真和模块回归组织为可复核证据包，绑定源码、向量、工具版本与完成标志，识别工具返回成功但仿真未通过的情况。
---
# HLS与RTL验证归档

从一次可重放的测试开始，明确输入、黄金输出、数值容差、顶层接口和完成条件。各层结果独立记录：C仿真、HLS综合、C/RTL协同仿真、布局布线、板上回放、传感器实测。

1. 工作目录与发布源分离；记录顶层、测试台、向量、约束、脚本SHA256和工具版本。
2. C测试台对结果逐槽比较，显式拒绝NaN/Inf，超出容差返回非零；覆盖动态长度、容量上限、非法头、空输入。
3. RTL测试台设置超时及断言。PASS标志必须在比较完成后输出。工具退出码、完成标志、错误关键字和报告文件同时检查。
4. 协同仿真保留cosim报告、真实延迟周期和输入种类。单帧CNN通过只证明此向量；多种模型和极端输入需要独立向量集。
5. 正式归档保存技术日志、源哈希和重放入口；机器用户名/路径可按规则替换，同时保留原始与归档日志哈希。

[run_evidence.py](scripts/run_evidence.py)执行经过检查的本地计划；输入命令拥有当前用户权限：

```bash
python scripts/run_evidence.py plan.json --root /tmp/verification --output /tmp/evidence
```

格式和判定策略见[归档规范](references/archive.md)。项目的[仿真目录](../../sim/README.md)提供真实归档和重跑入口；[通用自测](../verify_extended.py)注入PASS缺失、错误输出、非零返回和输入被改写。
