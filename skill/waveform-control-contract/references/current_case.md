# 低有效门控案例

接收器在门控下降沿后开启、上升沿关闭。控制接口版本5以周期相位和有效时长描述窗口，DAC1高有效、DAC2低有效；输出停止后DAC1低、DAC2高。

125 MHz对应8 ns步长。周期10000 ns、开启相位9000 ns、有效时长2000 ns时，区间为[0,1000)与[9000,10000) ns。初次启用等待首个完整窗口起点。

双路高速DAC和前端阈值DAC分别控制。网页正向码与模块原始码互补，5000 ns为激光电触发高电平时长，实际光脉宽由光源响应测量。

- [周期发生器](../../../src/rtl/internal_trigger_gen.v)、[DAC](../../../src/rtl/dual_dac_trigger.v)、[跨域提交](../../../src/rtl/ps_bridge/ps_output_control.v)。
- [时序测试](../../../sim/rtl/tb_internal_trigger_gen.sv)、[参考选择与输出](../../../sim/rtl/tb_dual_dac.sv)。
- [软件互锁](../../../src/ps/tests/test_web_controls.py)、[网页窗口](../../../src/ps/tests/test_output_timing.js)。
- [产物元数据](../../../sim/results/overlay_check.json)。

数字区间、版本回读和模拟波形分别保存验证记录。目录重定位后的完整构建列入复现验收。
