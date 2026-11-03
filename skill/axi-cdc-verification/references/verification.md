# 事务与CDC验证规范

## 逐拍采样

JSON为数组，cycle从0连续递增，每条记录是上升沿之前的信号值。包含reset_n和aw/w/b/ar/r各自valid、ready；VALID=1时提供awaddr/awprot、wdata/wstrb、bresp、araddr/arprot、rdata/rresp。reset_n=0丢弃在途记分项。最后一拍应无在途事务与被阻塞响应。

检查器限定AXI4-Lite，无burst、ID与乱序返回，整数载荷需在记录前处理X/Z；未解析X态直接作为输入错误。max_age是验证环境设定的等待上限，AXI协议本身不承诺固定响应期限。检查器核对时序和数量，地址对应的内容需额外黄金寄存器模型。

## CDC测试矩阵

| 变量 | 最少覆盖 | 检查点 |
| --- | --- | --- |
| 时钟关系 | 互质周期、相位偏移、快到慢/慢到快 | 请求不丢失、配置整组更新 |
| 更新时机 | 目标空闲、周期中途、边界前后 | 提交点和ACK语义一致 |
| 背压 | 请求前/响应期间、多拍连续 | payload稳定、只完成一次 |
| 复位 | 单域复位、两域复位、ACK在途 | 序列号/握手状态重建 |
| 故障 | 目标时钟停顿、ACK缺失、重复请求 | 超时可诊断、资源不被提前复用 |

功能仿真只能检验逻辑协议。同步器级数、ASYNC_REG属性、时钟组约束、总线偏斜和跨域路径还需Vivado CDC/时序报告核验。为修复时序而全局添加false_path会隐藏真实路径，例外需落到明确的同步结构。

## 来源与验证

本工程AXI快照、abort与跨域输出整组提交是提炼来源；归档保留实际RTL测试。通用检查器另外验证W先到、AW先到、背压稳定、提前B响应、重复R响应、复位清理和超时。

参考[Arm AXI规范](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)的独立通道和VALID/READY规则；脚本为独立实现。CDC硬件结论依赖目标设计，测试通过不覆盖模拟亚稳态概率。
