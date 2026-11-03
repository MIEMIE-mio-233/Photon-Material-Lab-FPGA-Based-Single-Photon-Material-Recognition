# 板端部署

## 环境

目标为MPSoC-P4 XCZU4EV-SFVC784-1-I，PYNQ2.7、aarch64和Python3.8.2。镜像提供NumPy1.20.3、SciPy1.3.3、Matplotlib3.1.2、Flask2.0.1及ipykernel5.5.5；随附wheel补充scikit-learn0.24.2、joblib1.1.1和threadpoolctl3.1.0。

## 硬件接口

引脚以src/rtl/pynq_pin.xdc为准：测量LVDS使用C1/B1，外部参考使用B3/A3。双路高速DAC采用10位、3.3 V数字接口，模拟电压由模块量程和负载决定；前端阈值由独立DAC设置。

| 对象 | 地址或版本 |
| --- | --- |
| 直方图RAM | 0xA0000000 |
| 控制桥 | 0xA0040000；版本5 |
| HLS核 | 0xA0050000 |
| 结果协议 | 版本3；88个double槽 |
| 模型输入 | 九维统计特征，CNN另有256点局部波形 |

部署时核对overlays/overlay_contract.json、src/ps/pl_runtime.py及RTL寄存器定义。

## 启动与输出

安装后先运行网页和PS识别，再按需加载Overlay。加载或恢复默认后，输出保持关闭；默认配置为内部参考、100 kHz、激光相位0 ns及高电平5000 ns、探测相位9000 ns及有效时长2000 ns、高电平正向码1023、比较阈值0.300 V。接管已加载Overlay时保留当前输出状态。采集任务和持续输出分别启停。

## 模型更新

类别数、节点量、输入形状及特征契约满足核限制时，更新模型只需装载参数。改变算子或特征时同步更新HLS、Python、测试和Overlay。树核最多64类、128树、16384节点；MLP/CNN共享2048个double参数缓存，特征经过float32边界。

网页面向受控实验局域网部署，服务端口8080。网络地址、ARP、VNC和防火墙沿用目标环境配置。
