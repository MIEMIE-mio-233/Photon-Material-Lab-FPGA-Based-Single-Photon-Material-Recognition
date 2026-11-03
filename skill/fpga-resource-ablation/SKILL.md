---
name: fpga-resource-ablation
description: 建立同功能、同约束的FPGA资源消融实验，解析HLS或Vivado报告，核对实例复用、资源预算与性能代价；适用于量化优化收益和审查资源比较口径。
---
# FPGA资源消融与预算

先确定待决策内容：减少DSP、降低BRAM、改善时序，或在吞吐预算内复用算子。输入至少包括前后源码、器件、工具版本、时钟约束、测试向量及两份报告。

1. 固定功能、数据类型、接口、容量、目标时钟与工具设置。一次只改变实例共享、存储绑定或并行度等一个结构因素。历史版本功能不同，应另列“架构演进”。
2. 给两版输入同一黄金向量，检查标签、数值、边界和错误状态。新建对照源在独立工作目录；部署源码保持可追踪。
3. 查看综合层级确认实例数量。ALLOCATION与INLINE的语义及参数顺序随工具版本核验；警告和生成RTL比源码中的pragma更能说明实际结果。
4. 使用[报告比较器](scripts/compare_resources.py)，输出数量、差值、降幅与预算判定。HLS的BRAM_18K与Vivado的Block RAM Tile分开计量。
5. 同时记录延迟/II、估算周期、布局布线WNS与约束覆盖。串行复用的节省需与吞吐约束一起判断。

```bash
python scripts/compare_resources.py before_csynth.xml after_csynth.xml --contract contract.json --output /tmp/resources.json
```

返回0表示报告可比较且满足给定预算，1表示预算超出，2表示缺项或口径不一致。脚本核对报告元数据；测试向量、源码与约束哈希由调用者提供并与原文件核对。

契约、验证场景和跨工程迁移见[实验规范](references/experiment.md)。本项目的[受控实验](../../build/experiments/dense_sharing/README.md)与[实测资源表](../../report/resource_optimization.md)可直接复现。脚本自测见[技能验证入口](../verify_extended.py)。
