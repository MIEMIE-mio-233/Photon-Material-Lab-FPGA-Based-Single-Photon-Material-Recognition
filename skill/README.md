# 可复用技能包

共14项，其中9项为通用FPGA/软件技能，5项面向PYNQ。SKILL.md提供使用入口，references记录工程案例与验证，scripts提供辅助工具。

| 目录 | 适用范围 | 使用方法 | 失效条件 |
| --- | --- | --- | --- |
| pynq_bringup | bit/HWH、地址与版本核验 | [SKILL.md](pynq_bringup/SKILL.md)，运行check_overlay.py，按目标工程契约核对版本与协议 | 镜像未启动、DMA未验证、硬件版本不匹配 |
| reference_compare | 黄金参考逐层数值比对 | [SKILL.md](reference_compare/SKILL.md)，运行compare_stages.py，核对九维/CNN结果 | 输入、单位或顺序不同，容差无依据 |
| pynq_pipeline_profiler | 分段计时和性能比较 | [SKILL.md](pynq_pipeline_profiler/SKILL.md)，记录同输入/模型/完成范围；profile_http.py定位状态、目录与波形延迟 | 把轮询当周期，比较不同完成事件 |
| forest_cross_runtime | 随机森林跨环境便携迁移 | [SKILL.md](forest_cross_runtime/SKILL.md)，导出JSON并核验概率 | 非树模型、任意joblib或错误特征契约 |
| pynq_offline_ml | 可启动PYNQ的离线依赖 | [SKILL.md](pynq_offline_ml/SKILL.md)，先探测ABI，再独立安装与内核验证 | 架构、Python ABI或基础依赖不匹配 |
| pynq-model-lifecycle | 版本归档、共享数据、按需加载和参数契约 | [SKILL.md](pynq-model-lifecycle/SKILL.md)，用当前源码和案例落实生命周期 | 算子/协议/容量不匹配，未等待硬件空闲 |
| instrument-web-workflow | 模型先可用、异步图表、筛选与实时展示 | [SKILL.md](instrument-web-workflow/SKILL.md)，复用request_gate.js并检查过期响应 | 应用请求与缓存协议不匹配 |
| waveform-control-contract | 有效电平、跨周期窗口和整组提交 | [SKILL.md](waveform-control-contract/SKILL.md)，运行validate_windows.py检查整数拍 | 模拟响应未知、需要多周期延迟或未实现窗口类型 |
| histogram-feature-contract | 选峰、基线、预处理和分组验证 | [SKILL.md](histogram-feature-contract/SKILL.md)，核对特征契约与多点校准来源 | 分组定义、基线或采集条件变化 |
| anonymous-fpga-release | 匿名、授权分界、交付及文件清单 | [SKILL.md](anonymous-fpga-release/SKILL.md)，在电脑端运行audit_release.py | 超出文本、属性或哈希检查范围 |
| fpga-resource-ablation | HLS/Vivado同口径资源消融与预算 | [SKILL.md](fpga-resource-ablation/SKILL.md)，解析报告、核验约束及输出资源差值 | 不同统计阶段、工具、器件或缺少等价性依据 |
| axi-cdc-verification | AXI4-Lite背压、事务和跨域配置验证 | [SKILL.md](axi-cdc-verification/SKILL.md)，逐拍轨迹检查及CDC测试矩阵 | burst/ID/乱序协议、缺失X态处理或物理CDC结论 |
| hls-verification-archive | HLS/RTL分层测试与证据归档 | [SKILL.md](hls-verification-archive/SKILL.md)，执行受信计划、记录输入哈希及完成标志 | 缺黄金参考、只凭返回码、向量或源码不匹配 |
| pynq-buffer-ownership | 共享DDR所有权、缓存与超时恢复 | [SKILL.md](pynq-buffer-ownership/SKILL.md)，运行离线事件检查器 | 多任务未建模、实际缓存属性/完成语义未知 |

技能结构、链接及辅助工具的本地合成检查见[验证摘要](validation_summary.json)。

在仓库根目录使用Python3.9或更新版本可重做通用示例检查：

```bash
python skill/verify_examples.py --report /tmp/skill_examples.json
```

检查报告保存在仓库外，测试使用临时数据；前端请求检查使用Node.js，缺少时报告跳过。技能结构由skill-creator校验器检查。

使用时从目标工程读取地址、引脚、容量与实验参数，再按对应契约执行。案例中的数值用于说明具体实现。

## 通用FPGA与软件技能

资源消融、AXI/CDC验证、HLS验证归档、黄金参考比较、模型跨环境迁移、周期波形控制、直方图特征契约、仪器网页交互和发布核验共9项，均可在不依赖PYNQ运行库的条件下使用。实例地址和模型结构来自目标工程，技能本身提供检查方法及参数化工具。

## 通用PYNQ技能

Overlay核验、离线机器学习依赖、流水线性能分析、模型生命周期及共享缓冲所有权共5项。非TDC元数据、合成向量和缓冲状态例子用于验证可迁移行为；涉及目标板的接口和时序仍依据其实际设计核验。

## 历史证据与新增验证

[历史证据索引](historical_evidence_index.json)恢复5份2026-10-17原始技术记录；日期、版本和适用范围保持原记录。新工具通过[44项正反例检查](extended_validation.json)，可在仓库外输出复测记录：

```bash
python skill/verify_extended.py --report /tmp/extended_skills.json
```

资源优化的实际综合与仿真见[资源对照](../report/resource_optimization.md)，RTL实际运行见[归档](../sim/results/rtl_20261103/summary.json)。新增脚本以Python3.9或更新版本执行，仅依赖标准库。
