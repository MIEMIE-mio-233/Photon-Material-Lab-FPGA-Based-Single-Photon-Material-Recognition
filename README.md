# 火眼金睛 单光子检测与FPGA加速材质识别系统

基于Zynq UltraScale+ MPSoC XCZU4EV-SFVC784-1-I（MPSoC-P4）和PYNQ的端侧实验平台。PL完成时间采集、直方图统计、触发门控及特征分类计算，PS运行训练程序与网页服务。网页前端通过PS网口配置参数、管理数据和查看结果。

## 技术特点

- 单光子时间表征：从光子到达直方图提取强度、展宽与峰位时移，支持局部波形与统计特征融合。
- PL测量与推理：双通道TDC、TOF累积、共享直方图与分类核形成板内数据通路。
- 多模型资源复用：决策树和随机森林共用树遍历；MLP和CNN共用参数缓存及单实例乘加函数。模型参数通过DDR更新。
- 跨层协同：RTL负责事件与时序，HLS C++实现数值计算，Linux/PYNQ连接训练、硬件调用及HTML交互。
- 单芯片实验闭环：测量、识别、模型训练和数据管理在XCZU4EV的PL与PS协同完成，各模型共用数据集，仅当前模型参数驻留。

## 工程目录

| 目录 | 内容 |
| --- | --- |
| src/ | RTL、HLS、PS Python、HTML、IP配置、基础BD、TDC网表、比较前端电路图及机械打印模型 |
| sim/ | 测试台、HLS向量、软件检查入口及分层验证记录 |
| build/ | 构建脚本、综合实现与时序报告，output为生成目录 |
| board/ | bit/HWH、安装与核验入口、离线wheel |
| data/ | 88批次1580帧原始数据及随机森林、MLP、CNN参数 |
| skill/ | 10项可复用技能、辅助脚本及案例 |
| report/ | 技术报告、矢量图、工程协作记录及许可说明 |

仓库路径采用小写英文、数字、下划线和连字符，README.md与SKILL.md保留规范名称。第三方来源及授权见[许可说明](report/third_party_notices.md)。

## 板端运行

1. 使用适配XCZU4EV的PYNQ镜像启动板卡，确认PS网口连通。
2. 将仓库复制至板卡，例如/home/xilinx/photon_material_lab，执行`python3 board/verify_release.py`。
3. 执行`sudo bash board/install.sh`。目标环境为aarch64、Python3.8和PYNQ2.7；基础依赖见[板端说明](board/README.md)。
4. 网页前端访问`http://板卡IP:8080/`，使用历史数据与PS推理核验软件。
5. 加载Overlay后，核对参考源、DAC、低有效门控、阈值与TDC校准状态，再接入真实采集。
6. 对同一帧及同一模型比较PS/PL特征与类别分数。

安装默认目录为/home/xilinx/tdc_material，支持TDC_APP_DIR和TDC_ENV_DIR覆盖。dataset、models和overlays链接到仓库公共存储，网页保存、训练与删除直接作用于这些目录。安装目标应为空目录；已有内容先备份。

## 网页操作

- 参数与配置：参考源、周期输出、低有效探测窗口、DAC码值、前端阈值与多点测距。
- 采集与识别：单帧、批量或连续采集，可选保存，支持PS/PL与快捷模型切换。
- 数据与对比：按日期、材质、实物搜索批次，附加距离和光照筛选，最多四帧叠加或分图查看。
- 模型与训练：勾选训练批次，训练随机森林、决策树、MLP或CNN，管理版本与图表。

原始计数按批次保存，关闭保存时缓存最近四帧。训练筛选保留已有勾选，“仅选筛选结果”显式替换范围。所有模型引用公共数据集，当前活动参数按需驻留。

多点测距每点10帧，至少三个已知距离，支持单点删除。经验距离用于位置显示；固定15 cm识别使用峰位时移及其他统计特征。光照条件作为辅助实验记录。

## 检查与构建

在具备NumPy、SciPy、scikit-learn、joblib、Flask和Matplotlib的环境运行：

```bash
python sim/run_checks.py
python board/verify_release.py
```

前端检查使用Node.js，缺少时报告跳过。检查使用临时数据。各层测试及记录见[sim说明](sim/README.md)。

Vivado/Vitis Unified 2025.2一键入口见[2025.2构建说明](build/README_2025_2.md)，2020.2入口见[硬件构建说明](build/README.md)。新版入口在独立英文工作目录中构建，实编与板端验证状态以各版本说明为准。

源码构建使用Vivado/Vitis HLS 2020.2。将仓库放在纯英文路径，例如D:/work/photon_material_lab，工具加入PATH后依次执行：

```bash
vitis_hls -f src/hls/build_hls.tcl
vivado -mode batch -source build/scripts/package_hls.tcl
vivado -mode batch -source build/scripts/create_pynq_project.tcl
vivado -mode batch -source build/scripts/build_pynq_bit.tcl
```

HLS2020.2遇到core_revision日期溢出时，先确认综合及impl/ip脚本生成，再运行第二步修正工程内打包脚本。输出目录为build/output，Overlay位于board/overlays，报告位于build/reports。重新构建后更新bit/HWH、版本与哈希，并完成重定位后的干净环境构建验收。

## 数据与验证结果

数据集包含21种材质标签，每类当前一件实物。固定15 cm遮光子集使用640帧训练、160帧同批次留出，RF64、MLP和CNN诊断准确率分别为99.375%、99.375%和90.625%。

布线后资源为LUT44031/87840、寄存器51026/175680、BRAM82/128和DSP35/728。数值一致性、计时范围与约束检查详见[技术报告](report/technical_report.md)。技术报告收录系统实物、材质样品、三类飞机模型识别与波形对比；[视频演示PPT](report/presentation.pptx)概述系统原理和实现。

采集页按帧更新波形和识别结果。批次目录按清单增量缓存，状态轮询读取索引快照；数据与训练页面按需刷新列表。板端2920帧索引案例中，全量目录HTTP中位数由5423 ms降至194 ms，稳定整帧处理约1025 ms。测量范围与原始数值见[采集展示性能](sim/results/capture_display_performance.json)。

机械结构的主体与顶盖STL见[打印模型](src/mechanical/README.md)，对应模型图与实物照片收录于技术报告。

比较前端资料见[硬件说明](src/hardware/README.md)，含完整五页电路图；实物连接照片与电路局部见[图表索引](report/figure_index.md)。

## 优化与验证证据

[共享算子资源对比](report/resource_optimization.md)；[RTL及协同仿真归档](sim/README.md)；[14项可复用技能与验证](skill/README.md)。
