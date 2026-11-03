---
name: pynq-buffer-ownership
description: 检查PYNQ共享DDR缓冲的PS/PL所有权、缓存同步、地址宽度及超时恢复，定位旧结果、随机错帧和提前释放问题；可用于图像、FFT、推理等加速器。
---
# PYNQ共享DDR生命周期

先识别实际通路：AXI BRAM窗口、HP/HPC共享DDR或AXI DMA；记录PYNQ版本、buffer.coherent、物理地址宽度、dtype、字节序和长度单位。

- 用pynq.allocate分配设备可访问缓冲；普通NumPy地址不能直接当作AXI物理地址。
- PS写入非一致缓冲后flush，再写地址、长度并启动。64位指针按HWH/RTL核对高低寄存器，不按Python int大小猜偏移。
- PL访问期间，PS保持数据、地址和生命周期。输入、输出与模型缓冲按任务整体租用；切模型先等待当前任务完成。
- 确认硬件完成且事务结束后，非一致输出invalidate再读取。读取/清除完成位按实际寄存器副作用定义。
- 超时保留缓冲。需要abort ACK或确认复位/总线已排空后才能释放；仅取消Python future不能取消AXI访问。

离线检查使用[check_ownership.py](scripts/check_ownership.py)：

```bash
python scripts/check_ownership.py events.json --output /tmp/ownership.json
```

[状态与恢复规范](references/lifecycle.md)包含非TDC例子、故障矩阵与双缓冲迁移条件。它检验声明的事件顺序，真实平台缓存属性和完成语义须回读确认。[验证集](../verify_extended.py)覆盖遗漏flush/invalidate和超时后释放。
