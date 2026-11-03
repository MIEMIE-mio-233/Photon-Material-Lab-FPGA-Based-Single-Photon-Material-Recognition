set root [file normalize [file join [file dirname [info script]] .. ..]]
set work [file join $root build dac_sim]; file mkdir $work; cd $work
set platform_dir [expr {$::tcl_platform(platform) eq "windows" ? "win64.o" : "lnx64.o"}]
set suffix [expr {$::tcl_platform(platform) eq "windows" ? ".exe" : ""}]
set bin [file join $::env(XILINX_VIVADO) bin unwrapped $platform_dir]
puts [exec [file join $bin xvlog$suffix] -sv [file join $root src rtl dual_dac_trigger.v] [file join $root src rtl tdc_reference_mux.v] [file join $root sim rtl tb_dual_dac.sv] [file join $::env(XILINX_VIVADO) data verilog src glbl.v] 2>@1]
puts [exec [file join $bin xelab$suffix] -L unisims_ver tb_dual_dac glbl -s tb_dual_dac 2>@1]
set output [exec [file join $bin xsim$suffix] tb_dual_dac -runall 2>@1]
puts $output
if {![string match "*PASS:*" $output] || [string match "*Fatal:*" $output]} {error "Dual DAC simulation failed"}
exit
