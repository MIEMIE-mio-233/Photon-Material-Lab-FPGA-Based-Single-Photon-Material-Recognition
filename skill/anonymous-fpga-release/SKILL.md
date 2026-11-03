---
name: anonymous-fpga-release
description: 整理匿名FPGA与PYNQ参赛仓库，核对依赖、路径、文档元数据、第三方许可及文件哈希。
---

# 匿名工程交付

阅读参赛通知、赛道指南及报告模板，记录依据的版本和日期。扫描件结合页面图像核对。

## 工程整理

盘点源码、运行服务与活动模型，按依赖保留RTL、IP配置、HLS、PS、网页、参数、向量和验证记录。将整理结果放入独立目录，核对路径、构建脚本及加载入口。原始帧和模型以哈希及同输入输出回归确认一致。

目录结构与文件名按赛道要求组织。干净环境构建作为单独验收步骤记录工具、依赖及结果。

## 许可与身份信息

网表、bit、IP配置、字体和wheel分别列明来源、许可及器件授权。保留合法第三方署名，根许可适用范围写入第三方说明。

匿名检查覆盖正文、路径、Word作者、修订、批注及外链。设备绑定标识可能位于不透明二进制，按授权条件保留产物，文本扫描范围在检查报告中列明。

[audit_release.py](scripts/audit_release.py)检查路径、显式禁词、DOCX元数据和可选SHA256清单。

```bash
python scripts/audit_release.py /path/to/repo --strict-names --deny-file /tmp/private_terms.json --manifest report/release_manifest.json --report /tmp/release_check.json
```

禁词文件为JSON字符串列表，保存在仓库外。退出码0通过、1发现问题、2输入无效；不支持的编码单列。工具使用Python3.9或更新版本，在电脑端执行。

## 报告与清单

官方模板控制章节和格式，数值按配置、实现报告、历史帧或光学测量分别注明来源。协作摘要和原始对话按实际材料类型标识。文档与图像更新后刷新文件清单，再核对路径与哈希。

当前依赖整理与验证见[实例](references/current_case.md)。
