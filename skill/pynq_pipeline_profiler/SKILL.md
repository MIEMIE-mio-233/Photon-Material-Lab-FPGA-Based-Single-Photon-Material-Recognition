---
name: pynq-pipeline-profiler
description: 分段测量PYNQ数据采集、搬运、存储、计算和展示，以同输入同模型同范围比较性能并核验格式转换。
---

# PYNQ流水线分段计时

定义各阶段起止事件，再测量采集、读取、保存、模型准备、计算和显示。单机使用time.perf_counter，网页前端使用自身时钟，跨设备传输采用明确的往返或同步测量方法。

## 记录与配对

[profile_pipeline.py](scripts/profile_pipeline.py)提供StageTimer和summarize。阶段互斥，total包含阶段间开销；重叠流水线另记录时间轴。

```bash
python scripts/profile_pipeline.py summarize records.json --baseline ps --candidate pl --report summary.json
```

比较键为case、input_sha256、model_id和scope，相同键配对。预热单列，稳定运行记录样本数、中位数、P95、最小及最大值。P95采用线性插值，小样本用作描述。加速比为相同计时范围的基线中位数除以候选中位数。

PL启动至PS观察done包含MMIO、调度与轮询，硬件周期以RTL计数器或工具报告单列。异步任务等待约定完成事件后结束计时。

## 格式与展示优化

文本解析占主要时间时，采集保存NPY、下载导出CSV。转换比较dtype、shape和全部计数；绘图降采样保留峰值及位置。轮询频率、增量记录和缓存长度根据数据速率设置。

真实累积下限由触发数与有效速率决定。存储测试注明flush、fsync及OS缓存条件，结果标为应用层时长。工具在临时子目录工作。

灰度像素存储示例及记录格式见[测量方法](references/measurement.md)，实测案例见[验证记录](references/validated-cases.md)，模型就绪与展示计时见[事件定义](references/model_ready_and_display.md)。

## 状态与目录请求定位

仪器后台已完成帧而界面延迟时，分别测状态、目录和波形API。使用[profile_http.py](scripts/profile_http.py)只读记录HTTP往返、响应字节数与预热，输出放在工程外。目录请求明显较慢时，检查采集进度是否触发全量列表，以及目录扫描锁是否阻塞状态；采用变化单元缓存与已发布摘要后，复测数据一致性和状态并发。案例与限制见[验证记录](references/validated-cases.md)。
