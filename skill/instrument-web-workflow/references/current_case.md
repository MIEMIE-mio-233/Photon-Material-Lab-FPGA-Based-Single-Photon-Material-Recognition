# 仪器网页案例

训练完成曾等待全部PNG，版本切换存在迟到响应，历史回放快于刷新，列表筛选与训练勾选相互影响。系统据此拆分模型归档、后台绘图及前端提交状态。

图表使用单绘图进程、有界队列及版本缓存。隔离130帧森林样例中，完整图表就绪为55.789 s，模型就绪为6.350 s，各测一次，分别对应不同完成事件。

批次列表共用筛选，勾选集合独立保留。采集页快捷启用模型，数据页最多四帧叠加或分图，附六项数值对照。

- [绘图队列](../../../src/ps/web/training_charts.py)、[网页](../../../src/ps/web/static/app.js)、[批次筛选](../../../src/ps/web/static/batch_picker.js)。
- [图表生命周期](../../../src/ps/tests/test_lazy_charts.py)、[响应缓存](../../../src/ps/tests/test_display_cache.js)、[模型选择](../../../src/ps/tests/test_model_manager.js)。
- [软件汇总](../../../sim/results/software_checks.json)及本地请求门控合成自测。

板端接口完成四帧历史对比，视觉预览使用同代码与真实帧快照。网页前端自动化超时记录与已完成接口检查分列。

采集展示与目录刷新独立调度。每帧结果发布不请求全量目录，保存改变数据后设置列表待刷新状态，数据页和训练页按需取得目录。异步目录请求完成后再次核对计数，保留请求期间发生的变化。后台状态使用已发布索引快照，清单扫描在独立任务中执行。验证见[前端策略](../../../src/ps/tests/test_capture_refresh.js)及[性能记录](../../../sim/results/capture_display_performance.json)。
