set root [file normalize [file join [file dirname [info script]] .. ..]]
set work [file join $root build bridge_sim]
file mkdir $work
cd $work
set platform_dir [expr {$::tcl_platform(platform) eq "windows" ? "win64.o" : "lnx64.o"}]
set suffix [expr {$::tcl_platform(platform) eq "windows" ? ".exe" : ""}]
set bin [file join $::env(XILINX_VIVADO) bin unwrapped $platform_dir]
puts [exec [file join $bin xvlog$suffix] -sv [file join $root src rtl internal_trigger_gen.v] [file join $root src rtl dac tlv5618.v] [file join $root src rtl dac dac_ctrl.v] [file join $root src rtl ps_bridge ps_threshold_control.v] [file join $root src rtl ps_bridge ps_output_control.v] [file join $root src rtl ps_bridge tdc_ps_bridge.v] [file join $root sim rtl tb_ps_capture.sv] 2>@1]
puts [exec [file join $bin xelab$suffix] tb_ps_capture -s tb_ps_capture 2>@1]
set output [exec [file join $bin xsim$suffix] tb_ps_capture -runall 2>@1]
puts $output
if {![string match "*PASS:*" $output] || [string match "*Fatal:*" $output]} { error "Bridge simulation failed" }
exit
