# Vitis Unified 2025.2：vitis-run --mode hls --tcl build_hls_2025_2.tcl
set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here .. ..]]
cd $here
set ::env(TDC_TEST_DATA_DIR) [file join $root sim hls]
open_project -reset [file join $root build output hls]
set_top tdc_accelerator
add_files [file join $here tdc_accelerator.cpp]
add_files -tb [file join $root sim hls check_rtl.cpp]
open_solution -reset solution1 -flow_target vivado
set_part {xczu4ev-sfvc784-1-i}
create_clock -period 10 -name default
config_interface -m_axi_addr64
csim_design
csynth_design
if {[info exists ::env(TDC_HLS_COSIM)] && $::env(TDC_HLS_COSIM) eq "1"} {
    cosim_design -rtl verilog -tool xsim -trace_level none
}
# 使用新版原生打包，不调用2020.2的core_revision修正脚本。
export_design -format ip_catalog -vendor user.org -library hls -version 1.0
exit
