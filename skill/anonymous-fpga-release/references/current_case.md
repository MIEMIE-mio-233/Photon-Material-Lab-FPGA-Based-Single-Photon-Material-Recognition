# 匿名工程发布案例

工程按src、sim、build、board、data、skill和report分类，包含运行源码、模型、数据及离线依赖。TDC网表与bit的公开许可按组件列于[第三方说明](../../../report/third_party_notices.md)。

发布前核对[文件清单](../../../report/release_manifest.json)，通过[完整性入口](../../../board/verify_release.py)验证哈希。数值验证见[HLS C++结果](../../../sim/results/cpp_parity.json)及[板端结果](../../../sim/results/pl_history_parity.json)。技术报告采用官方模板，图片与文档属性应覆盖身份信息检查。

audit_release.py提供禁词、Word属性、哈希与路径检查。检查报告保存在交付目录外；公开目录保留可复现的工程内容、技术文档及验证证据。
