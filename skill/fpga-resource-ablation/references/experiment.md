# 可迁移的资源实验规范

## 契约

JSON包含scope、equivalence、controlled_change三个非空说明字段，before_source_sha256、after_source_sha256、constraints_sha256、fixture_sha256四个SHA256字段，以及可选budgets，如{"DSP":80,"BRAM_18K":64}。before/after必须来自相同工具、器件、顶层、统计阶段；HLS还检查目标周期和时钟不确定度。实际执行命令和全部向量哈希随归档保存。

## 决策路径

- DSP紧张：先看层级实例与操作绑定，确认并行乘法是否有实际吞吐需求；试限制实例而非直接降低位宽。
- BRAM紧张：检查数组分区/复制和端口冲突；一个36K tile可能分成两个18K块，比较前统一单位。并行读取引起的存储复制应与原始数组容量分开说明。
- LUT增加但DSP下降：属于资源置换，结合器件预算和时序判定，不能只展示下降项。
- II未达到目标：查看依赖、端口冲突、运算器延迟；流水线目标不等于已实现II。
- 黑盒/OOC：综合顶层可能未计入子IP，报告范围需记录展开状态。当前项目的综合报告与最终routed报告BRAM差异即属此类审查线索。

HLS关键路径估算与Vivado最终时序分别呈现。缺少有效时钟/输入输出约束时，正WNS只能描述已分析路径。

## 提炼来源和验证

本工程历史版本同时增加了阈值、DAC和CNN，版本间差值无法隔离共享乘加收益。因此构造相同顶层、同一CNN黄金向量的独立卷积函数/共享函数对照。2026-11-03实际运行Vitis HLS 2020.2，两版C仿真通过，并归档层级报告及资源差值。

通用自测包含实际HLS报告解析、DSP预算超限、时钟变化、缺失计数、Vivado/HLS阶段混用；故障注入用于验证检查器行为。共享方案对其他算法的收益需由其实际报告确定。

## 参考

工作流设计参考[开源FPGA Development skill](https://github.com/magnus919/agent-skills/blob/main/fpga-development/SKILL.md)的分层证据思想；本技能正文和脚本独立编写。算子复用参考[AMD ALLOCATION说明](https://docs.amd.com/r/2022.2-English/ug1399-vitis-hls/pragma-HLS-allocation)。
