set root [file normalize [file join [file dirname [info script]] .. ..]]
set work [file join $root build trigger_sim]; file mkdir $work; cd $work
set platform_dir [expr {$::tcl_platform(platform) eq "windows" ? "win64.o" : "lnx64.o"}]
set suffix [expr {$::tcl_platform(platform) eq "windows" ? ".exe" : ""}]
set bin [file join $::env(XILINX_VIVADO) bin unwrapped $platform_dir]
puts [exec [file join $bin xvlog$suffix] -sv [file join $root src rtl internal_trigger_gen.v] [file join $root sim rtl tb_internal_trigger_gen.sv] 2>@1]
puts [exec [file join $bin xelab$suffix] tb_internal_trigger_gen -s tb_internal_trigger_gen 2>@1]
set output [exec [file join $bin xsim$suffix] tb_internal_trigger_gen -runall 2>@1]
puts $output
if {![string match "*ALL TESTS PASSED*" $output] || [string match "*Fatal:*" $output]} {error "Trigger simulation failed"}
exit
