# 第三方来源与许可

根目录MIT许可适用于本项目有权许可的集成、控制、算法、网页及整理脚本。第三方组件适用各自许可。

| 组件 | 来源与使用条件 |
| --- | --- |
| src/netlist/time_merge_eval.dcp | 厂家DNA绑定评估网表，已确认允许公开网表及生成bit；更换器件需取得对应授权 |
| board/overlays/tdc_pynq.bit | 含TDC网表的生成产物，沿用对应授权条件 |
| src/vendor_ip、src/bd及HWH | AMD工具/IP配置及生成内容，遵循原工具与IP条款 |
| UDP/接口RTL及TLV5618参考驱动 | 保留原有归属，TLV5618参考代码来自小梅哥工程 |
| src/hardware/comparator_frontend_schematic.pdf | 双通道比较前端电路资料，保留原始图页标识，作为接线与阈值电路参考 |
| src/ps/report_assets字体 | 保留ofl.txt及字体版权元数据 |
| board/wheels | 保留wheel内许可证及包元数据 |

折叠式TDC技术文献及相关系统文献按技术报告中的顺序编码格式引用。公开材料保留第三方合法署名，参赛者身份信息按匿名提交要求处理。

## 技能方法参考

新增技能参考开源[FPGA Development](https://github.com/magnus919/agent-skills/blob/main/fpga-development/SKILL.md)的分层验证组织思路，并结合AMD HLS示例、Arm AXI规范和PYNQ接口文档独立编写。具体链接列于各技能references目录；本次未纳入第三方技能代码或逐字正文。
