# 缓冲区状态与恢复

## 事件格式

JSON数组事件：alloc(buffer,coherent)、cpu_write(buffer)、flush(buffer)、start(reads,writes)、timeout、done、abort_ack、invalidate(buffer)、cpu_read(buffer)、free(buffer)。示例见[非TDC向量运算](../assets/vector_events.json)。当前检查器一次只允许一个任务，支持多个命名缓冲。cpu_write表示整个相关数据范围已初始化；局部写需扩展到区间级模型。

正常非一致路径：分配→输入写入→flush→start→done→输出invalidate→读取→释放。coherent=true时可省显式flush/invalidate，但仍必须遵守先写后启动、完成后读取和生命周期约束。

## 故障矩阵

| 现象 | 区分方法 | 处理 |
| --- | --- | --- |
| 第一次正确、重复后旧结果 | 保存每次输入哈希、任务序号与输出头 | 检查invalidate和是否读取上一任务 |
| 大地址才失败 | 对照64位物理地址与寄存器高字 | 统一地址宽度及HWH版本 |
| 小数据通过、大数据错尾 | 核对length单位、burst边界、容量 | 字节/元素换算及上限检查 |
| 超时后下一次崩溃 | 查未完成AXI事务和被释放buffer | 隔离故障任务，确认硬件停止 |
| 切模型随机错分类 | 记录模型版本与参数缓冲租用 | 模型替换和执行互斥 |

abort_ack之后部分输出视为无效，不作为正常结果读取。reset与abort_ack的语义需要实际硬件支持，不能仅由驱动构造成功事件。

## 双缓冲与跨板复用

扩展为双缓冲时给每个槽分配epoch和独立所有权，完成事件必须携带槽号/epoch；只有同一代任务完成才能重用。CMA容量按所有在途输入、输出、模型和对齐填充之和预算。先在单任务语义下确认正确，再加入流水；AXI DMA还需验证TLAST、接收启动顺序和长度。

提炼来自项目共享模型/直方图DDR、按需模型加载及超时控制观察。本技能新增离线状态检查器通过非TDC正反例测试；现有板端历史回放可作为接口工作实例。双缓冲属于迁移设计指导，本项目当前实现不据此宣称并行流水。

缓存操作定义参考[PYNQ allocate](https://pynq.readthedocs.io/en/latest/pynq_libraries/allocate.html)与[PYNQ 2.7 buffer API](https://pynq.readthedocs.io/en/v2.7.0/pynq_package/pynq.buffer.html)。
