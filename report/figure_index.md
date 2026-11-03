# 技术图表

工程框图采用白底、圆角模块和虚线分区，按光学前端、PL与PS组织；数据通路使用短距离正交连接。SVG用于矢量编辑，PNG用于报告。

## 报告图表

| 图号与内容 | 图像 | 矢量文件 |
| --- | --- | --- |
| 图1-1 假目标欺骗与材质鉴别的现实需求 | [图像](figures/application_context.png) | — |
| 图1-2 软硬件协同设计与验证流程 | [图像](figures/design_flow.png) | [SVG](figures/design_flow.svg) |
| 图2-1 单光子测量与PS加PL识别总体架构 | [图像](figures/system_architecture_photos.jpg) | — |
| 图2-2 开发板与外围连接（左）及双通道比较前端（右） | [图像](figures/fpga_board_connections.png) | — |
| 图2-2 开发板与外围连接（左）及双通道比较前端（右） | [图像](figures/comparator_frontend.png) | — |
| 图2-3 比较前端主板电路局部 CH1与CH2及阈值产生 | [图像](figures/comparator_schematic_detail.png) | — |
| 图2-4 光学采集模块 正视与45°斜视 | [图像](figures/optical_module_front.jpg) | — |
| 图2-4 光学采集模块 正视与45°斜视 | [图像](figures/optical_module_oblique.jpg) | — |
| 图2-5 100 kHz触发与跨周期低有效探测窗口 | [图像](figures/default_timing.png) | [SVG](figures/default_timing.svg) |
| 图2-6 折叠插值与CARRY8双输出采样原理 | [图像](figures/tdc_folded_circuit.png) | [SVG](figures/tdc_folded_circuit.svg) |
| 图2-7 计数式编码的分组求和与流水寄存示意 | [图像](figures/tdc_encoder_pipeline.png) | [SVG](figures/tdc_encoder_pipeline.svg) |
| 图2-8 码密度校准的数据通路与工作阶段 | [图像](figures/tdc_calibration_flow.png) | [SVG](figures/tdc_calibration_flow.svg) |
| 图2-9 TOF配对与直方图读写流水 | [图像](figures/tof_rtl_datapath.png) | [SVG](figures/tof_rtl_datapath.svg) |
| 图2-10 PS与PL的AXI连接及共享RAM访问 | [图像](figures/frame_ownership.png) | [SVG](figures/frame_ownership.svg) |
| 图2-11 PL滑动窗口搜索与局部特征提取 | [图像](figures/feature_datapath.png) | [SVG](figures/feature_datapath.svg) |
| 图2-12 树模型与神经网络的共享存储和算子调度 | [图像](figures/shared_inference.png) | [SVG](figures/shared_inference.svg) |
| 图2-13 Fe样品真实直方图与后峰平滑局部图 | [图像](figures/real_histogram.png) | [SVG](figures/real_histogram.svg) |
| 图2-14 九维特征的波形定义与统计区间 | [图像](figures/nine_features.png) | [SVG](figures/nine_features.svg) |
| 图2-15 局部回波与统计特征融合的一维CNN | [图像](figures/cnn_structure.png) | [SVG](figures/cnn_structure.svg) |
| 图3-1 系统实物 正面与俯视 | [图像](figures/system_front_view.jpg) | — |
| 图3-1 系统实物 正面与俯视 | [图像](figures/system_top_view.jpg) | — |
| 图3-2 3D打印主体与顶盖 | [图像](figures/enclosure_body_cad.png) | — |
| 图3-2 3D打印主体与顶盖 | [图像](figures/enclosure_lid_cad.png) | — |
| 图3-3 采集任务与PS或PL推理选择 | [图像](figures/web_capture_controls.png) | — |
| 图3-4 单帧波形与材质识别结果 | [图像](figures/web_single_panel.png) | — |
| 图3-5 训练批次选择、模型参数配置与结果展示 | [图像](figures/web_training_panel.png) | — |
| 图3-6 多帧回波及关键特征对照 | [图像](figures/web_comparison_panel.png) | — |
| 图3-6（续） 四帧回波的独立坐标分图查看 | [图像](figures/web_comparison_separate.png) | — |
| 图3-7 固定距离识别实验使用的16种材料样品 | [图像](figures/material_samples_16.jpg) | — |
| 图3-8 三种模型的同批次留出混淆矩阵 | [图像](figures/model_confusions.png) | [SVG](figures/model_confusions.svg) |
| 图3-9 八类样品的实物、回波波形与识别结果（a—d） | [图像](figures/recognition_samples_01.png) | — |
| 图3-9（续） 八类样品的实物、回波波形与识别结果（e—h） | [图像](figures/recognition_samples_02.png) | — |
| 图3-10 纸板、塑料与合金飞机模型实物 | [图像](figures/aircraft_samples.png) | — |
| 图3-11 三类飞机模型的实物、真实回波与PL识别结果 | [图像](figures/aircraft_recognition.png) | — |
| 图3-12 三种飞机模型的回波叠加对比 | [图像](figures/aircraft_waveforms.png) | — |
| 图3-13 全PS与PS加PL计算路径 | [图像](figures/inference_paths.png) | [SVG](figures/inference_paths.svg) |
| 图3-14 历史模型分项计算耗时 | [图像](figures/latency_evidence.png) | [SVG](figures/latency_evidence.svg) |
| 图3-15 数据目录访问优化前后对比 | [图像](figures/catalog_optimization.png) | [SVG](figures/catalog_optimization.svg) |
| 图3-16 Zynq UltraScale+ MPSoC XCZU4EV资源使用比例 | [图像](figures/resource_usage.png) | [SVG](figures/resource_usage.svg) |

TDC相关研究见技术报告参考文献[1]。TOF、AXI与HLS数据通路对应当前工程。比较前端局部来自[完整电路图](../src/hardware/comparator_frontend_schematic.pdf)首页，与[主板原理图01](figures/comparator_schematic_01.jpg)内容对应。

历史推理计时见[板端回放记录](../sim/results/pl_history_parity.json)，真实采集与目录优化见[性能测试记录](../sim/results/capture_display_performance.json)。

## 演示文稿

[作品视频演示PPT](presentation.pptx)，按选题背景、创新设计、关键技术和成果展示组织。

## 补充图像

| 文件 | 图像 |
| --- | --- |
| aircraft_features | [图像](figures/aircraft_features.png) |
| web_training_configuration | [图像](figures/web_training_configuration.png) |
| web_training_results | [图像](figures/web_training_results.png) |
| comparator_schematic_01 | [图像](figures/comparator_schematic_01.jpg) |
| dataset_distribution | [图像](figures/dataset_distribution.png) |
| importance_and_loss | [图像](figures/importance_and_loss.png) |
| software_workflow | [图像](figures/software_workflow.png) |
| tdc_coarse_fine | [图像](figures/tdc_coarse_fine.png) |
| tdc_principle | [图像](figures/tdc_principle.png) · [SVG](figures/tdc_principle.svg) |
| web_calibration_panel | [图像](figures/web_calibration_panel.png) |
| web_model_panel | [图像](figures/web_model_panel.png) |
| web_output_panel | [图像](figures/web_output_panel.png) |

机械打印文件见[机械结构](../src/mechanical/README.md)。
