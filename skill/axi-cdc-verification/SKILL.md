---
name: axi-cdc-verification
description: 为AXI4-Lite寄存器桥和跨时钟配置提交建立事务、背压、复位、超时测试，检查逐拍握手记录与CDC结构证据；适用于RTL控制接口验证。
---
# AXI与跨时钟控制验证

先取得寄存器语义、时钟/复位关系和完成事件。将AXI事务正确性、目标域配置原子性、复位恢复分为独立验证目标。

- AW与W独立握手，分别覆盖AW先到、W先到、同拍到达。B响应在两者均被接受后产生；AR/R另设队列。
- VALID等待READY期间，载荷和VALID保持稳定。插入连续背压，检查重复响应、丢响应及多笔在途事务。
- 检查WSTRB、只读寄存器、读清零、副作用端口、未映射地址和对齐错误的设计语义。通用协议检查器不替代寄存器记分板。
- 跨域多位配置采用稳定数据保持＋请求/应答，或异步FIFO。单独同步每一位不能保证同一版本的配置。
- 在请求前、在途和应答前分别复位；失去应答时进入受控故障态。超时只代表软件等待结束。

[check_axil_trace.py](scripts/check_axil_trace.py)读取完整AXI4-Lite逐拍JSON，可用于任何数据寄存器外设：

```bash
python scripts/check_axil_trace.py trace.json --max-pending 4 --max-age 1000 --output /tmp/axi_result.json
```

采样定义、CDC测试矩阵和故障定位见[验证规范](references/verification.md)。实际桥接测试见[RTL归档](../../sim/results/rtl_20261103/summary.json)。[自测](../verify_extended.py)使用非TDC控制外设轨迹。
