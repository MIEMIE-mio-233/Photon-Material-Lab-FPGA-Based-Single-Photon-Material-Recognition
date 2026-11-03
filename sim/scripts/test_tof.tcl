set root [file normalize [file join [file dirname [info script]] .. ..]]
set work [file join $root build tof_sim]; file mkdir $work; cd $work
set platform_dir [expr {$::tcl_platform(platform) eq "windows" ? "win64.o" : "lnx64.o"}]
set suffix [expr {$::tcl_platform(platform) eq "windows" ? ".exe" : ""}]
set bin [file join $::env(XILINX_VIVADO) bin unwrapped $platform_dir]
puts [exec [file join $bin xvlog$suffix] -sv [file join $root src rtl tof.v] [file join $root sim rtl tb_tof_snapshot.sv] 2>@1]
puts [exec [file join $bin xelab$suffix] tb_tof_snapshot -s tb_tof_snapshot 2>@1]
set output [exec [file join $bin xsim$suffix] tb_tof_snapshot -runall 2>@1]
puts $output
if {![string match "*PASS:*" $output] || [string match "*Fatal:*" $output]} {error "TOF snapshot simulation failed"}
exit
