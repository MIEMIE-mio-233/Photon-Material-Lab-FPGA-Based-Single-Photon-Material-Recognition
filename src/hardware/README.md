# 双通道比较前端

[完整电路图](comparator_frontend_schematic.pdf)包含主板连接、TLV3801比较支路和LM27762供电电路，共五页。原图页中的器件型号、网络名称与版本标识予以保留。

- CH1和CH2对应两路事件输入，比较阈值由TLV5618与OPA2188电路产生。
- 当前工程测量输入为C1/B1，外部参考为B3/A3，具体逻辑端口与电气约束见[引脚约束](../rtl/pynq_pin.xdc)。
- 阈值配置通过[前端DAC驱动](../rtl/dac/dac_ctrl.v)和[PS阈值控制](../rtl/ps_bridge/ps_threshold_control.v)完成。
- 主板原理图还包含其他接口，实际使用范围以顶层连接和约束为准。

实物连接与文内电路局部见[技术图表索引](../../report/figure_index.md)。
