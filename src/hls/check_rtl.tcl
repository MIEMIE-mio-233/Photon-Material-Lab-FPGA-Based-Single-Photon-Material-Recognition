set here [file dirname [file normalize [info script]]]
cd $here
set root [file normalize [file join $here .. ..]]
set ::env(TDC_TEST_DATA_DIR) [file join $root sim hls]
open_project [file join $here .. .. build output hls]
open_solution solution1
add_files -tb [file join $root sim hls check_rtl.cpp]
csim_design
cosim_design -rtl verilog -tool xsim -trace_level none
exit
