# 使用与计时契约

Python>=3.6；统计仅标准库，存储示例还需NumPy。在本技能目录运行：

```bash
python scripts/profile_pipeline.py storage-demo --repeats 5 --length 8192 --records demo_out/records.json --report demo_out/report.json
python scripts/profile_pipeline.py summarize demo_out/records.json --baseline csv --candidate npy --report demo_out/summary.json
```

示例输入为8192个uint16灰度像素。交替两种格式测试次序，第一轮标为warmup，检查dtype和完整值相同。--directory可选择目标文件系统已有目录，工具仅使用自己的临时子目录；--durable在写阶段增加flush和fsync。默认记录含格式化、解析及OS缓存的应用层读写时长，功能检查依据数值一致性。

records.json为记录列表，也接受每行一条JSON。每条包括：

```json
{"case":"sample_01","input_sha256":"0000000000000000000000000000000000000000000000000000000000000000","model_id":"model-v1","backend":"ps","scope":"counts_to_result","warmup":false,"total_ms":3.2,"stages_ms":{"prepare":0.2,"compute":3.0}}
```

示意哈希仅说明格式，实际应由输入字节与必要格式元数据产生，并在不同后端保持相同输入标识。时长使用有限非负毫秒数，bool为无效输入；阶段和超过总耗时会拒绝（仅留0.001ms舍入余量）。未配对的组单列；要求比较但没有任何同输入同范围组时返回2。

集成到自己的同步处理函数：

```python
from profile_pipeline import StageTimer
clock = StageTimer(case=case_id, input_sha256=input_hash, model_id=model_id,
                   backend="pl", scope="counts_to_result", warmup=first_run)
with clock.stage("prepare"):
    prepare_buffers()
with clock.stage("compute_observed"):
    start_ip_and_wait_done()
with clock.stage("decode"):
    result = read_result()
record = clock.finish()
```

把scripts加入自己的模块路径或复制该工具；不需要修改现有网页的硬件寄存器。跨机器网页前端计时单独保存，不并入另一个时钟的total。
