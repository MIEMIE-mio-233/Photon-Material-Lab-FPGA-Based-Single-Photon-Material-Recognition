# TDC 随机森林迁移：2026-10-13 实测案例

源环境：电脑 Python 3.12.4 / sklearn 1.4.2；目标：BX71 PYNQ 2.4 / Python 3.6.5 / sklearn 0.19.1。数据共 13 类/130 帧，每类 1 件实物、10 帧。默认森林 32 棵、最大深度 8、8 个特征、n_jobs=1；配置取自当时模型及资源条件。

## 特征契约和修复

直方图前面窄而高的峰为参考/干扰峰，实际回波在较晚窗口；按参考峰排除前峰后再搜回波。选峰结合参考位置限定搜索窗。

原特征函数用 SciPy 浮点滑动平均。跨旧版环境对同一帧 PMMA 的半高宽出现 73 与 72 bin 的差异，半高阈值落在浮点边界。修复后版本 tdc_echo_v2_integer_windows：

- uint32 计数，41 点 nearest 边缘补齐；uint64 前缀和求整数窗口和，再除 41 得平滑高度。
- 峰位对整数窗口和求 argmax；半高比较使用 2 * local_sum >= peak_sum。
- 宽度沿用原局部窗口内所有满足半高条件点的首尾跨度定义，按原窗口定义保持一致。
- 其余归一化、面积和加权形状定义保持一致；更改后两端重新训练并同步特征版本。

这条整数策略适合整数直方图，需要根据窗口长度/累计长度核对 uint64 范围；其他信号需按数据类型选择累计策略。实测 130 帧两端特征最大浮点误差 2.842170943040401e-14，整数宽度和峰位一致。

## 旧环境兼容

项目针对 Python 3.6/NumPy 1.13/Matplotlib 2.1：移除 dataclass/list[T] 和 Path.is_relative_to；文件路径传 str；排序用 mergesort；绘图使用旧版刻度与布局 API。兼容修改依据上述运行时API。

训练读取 dataset/run_*/manifest.csv 的有效完整帧。板端 prefer-raw 从对应 28 字节头加 8 字节/bin 的 .dat 读取，并核验长度、标记、bin 连续性、bin 数和总计数；该布局为本案例TDC传输协议。

## 应用入口

电脑保留 models/material_model.joblib 命名并新增 portable.json、report.json；一键训练自动同时更新。one-click 启动器和 MATLAB 共用 python_executable.txt，带空格路径引用完整。

predict_material.py 保留连续输入和 --json：material、reference_bin、return_bin、class_scores，并增加 model_type/model_id/backend。实际MATLAB -batch离线调用通过。

## 证据与限制

- 电脑原生与便携推理比对真实和阈值附近特征共 1100 组，分数最大误差 0。
- 板端原生与便携分数误差 0；电脑同一模型在板端使用便携 JSON，130 帧标签一致。
- 每类末尾 2 帧留出，共 26 帧，准确率 100%；各类为同一实物连续帧，结果为重复测量诊断。
- 完成板端训练、内核导入及PC/MATLAB离线调用。

原始数据见 validation-20261013.json。技能辅助脚本还用其他特征维度与类别的人工数据验证导出/推理通用性，记录为合成数据软件测试。
