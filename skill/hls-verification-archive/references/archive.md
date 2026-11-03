# 归档格式与完成判定

计划JSON含tool_version、scope、inputs（相对root的文件列表）和steps。每个step含name、argv数组、cwd、timeout_s、pass_regex数组、fail_regex数组、可选artifacts文件列表。命令按数组传参，无shell展开。工具需要批处理环境时，由已审查的启动器设置。

```json
{"tool_version":"test-runner 1", "scope":"software fixture",
 "inputs":["case.py"],"steps":[{"name":"case","argv":["python","case.py"],
 "cwd":".","timeout_s":30,"pass_regex":["^PASS: compared"],
 "fail_regex":["^FAIL:","^ERROR:"],"artifacts":[]}]}
```

runner输出result.json及每步日志，记录执行参数、时间、退出码、输入前后哈希和产物哈希。脚本只终止其启动进程；复杂厂商工具如派生额外进程，超时后按其进程树与工具恢复方式清理，再重新创建工作目录。

## 常见误判

- 批处理返回0但日志有Tcl错误：要求最终比较标志且错误匹配为空。
- C仿真PASS误当RTL通过：RTL必须有cosim PASS和相应报告，保存两层证据。
- 运行旧snapshot：把编译与仿真作为同一测试，源哈希和snapshot名称归档。
- 变更向量却沿用旧expected：固定向量字节哈希，独立生成黄金结果并声明生成器。
- 把HLS EstimatedClockPeriod当整板最高频率：最终结论使用完整约束下的布局布线报告。
- 只看到PASS而忽略原语告警：按未使用启动阶段、有效计算阶段分类，保留告警数量与上下文；结果正确性仍由完整输出比较判定。

来源：本项目旧仿真日志与新源码关联不充分，因此增加输入指纹、独立工作目录重跑和明确层级。2026-11-03完成四组当前RTL测试及共享/独立算子C仿真；归档结果详见sim索引。通用runner由故障注入测试验证，不宣称验证了任意厂商工程。

参考[AMD HLS示例库](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples)的源码、测试台与构建脚本组织方式。这里提供独立编写的证据收集器，未复制第三方实现。
