# 在 Vitis HLS 2020.2 中运行：vitis_hls -f build_hls.tcl
set here [file dirname [file normalize [info script]]]
cd $here
open_project -reset [file join $here .. .. build output hls]
set_top tdc_accelerator
add_files [file join $here tdc_accelerator.cpp]
open_solution -reset solution1 -flow_target vivado
set_part {xczu4ev-sfvc784-1-i}
create_clock -period 10 -name default
config_interface -m_axi_addr64
csynth_design
export_design -format ip_catalog -vendor user.org -library hls -version 1.0
exit
