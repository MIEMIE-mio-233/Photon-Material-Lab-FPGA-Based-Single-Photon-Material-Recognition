# 综合后、opt_design前执行；命令行构建与Vivado图形界面共用这一处准备工作。
set tdc_overlay_root [file normalize [file join [file dirname [info script]] .. ..]]
set tdc_core [get_cells -quiet u_top_tdc/u_time_merge]
if {![llength $tdc_core]} {error "Licensed TDC instance is missing"}
if {[get_property IS_BLACKBOX $tdc_core]} {
    read_checkpoint -cell u_top_tdc/u_time_merge [file join $tdc_overlay_root src netlist time_merge_eval.dcp]
}
# PS约100MHz与TDC 300MHz通过握手/AXI Clock Converter跨域。
set tdc_ps_clocks [get_clocks -quiet -of_objects [get_pins -hierarchical -quiet -filter {NAME =~ */pl_clk0}]]
set tdc_clock_pin [get_pins -quiet u_top_tdc/u0_clk/clk_out2]
set tdc_core_clocks [get_clocks -quiet -of_objects $tdc_clock_pin]
if {![llength $tdc_ps_clocks] || ![llength $tdc_core_clocks]} {error "Cannot identify PS/TDC clocks"}
set tdc_output_clocks [get_clocks -include_generated_clocks $tdc_core_clocks]
set_clock_groups -asynchronous -group $tdc_ps_clocks -group $tdc_output_clocks
# 阈值参数在请求至ACK期间保持；另约束同一总线各位的布线偏斜。
foreach channel {a b} {
    set from_cfg [get_cells -hier -filter "NAME =~ */threshold_control/cfg_${channel}_reg*"]
    set to_cfg [get_cells -hier -filter "NAME =~ */threshold_control/cfg_${channel}_meta_reg*"]
    set from_actual [get_cells -hier -filter "NAME =~ */threshold_control/applied_${channel}_reg*"]
    set to_actual [get_cells -hier -filter "NAME =~ */threshold_control/actual_${channel}_meta_reg*"]
    if {![llength $from_cfg] || ![llength $to_cfg] || ![llength $from_actual] || ![llength $to_actual]} {
        error "Threshold handshake registers missing for channel $channel"
    }
    set_bus_skew 8.0 -from $from_cfg -to $to_cfg
    set_bus_skew 10.0 -from $from_actual -to $to_actual
}
# 顶层端口接入后时钟net可能改名，因此按时钟IP输出pin取得实际网络。
if {[llength [get_debug_cores -quiet dbg_hub]]} {
    connect_debug_port dbg_hub/clk [get_nets -of_objects $tdc_clock_pin]
}
