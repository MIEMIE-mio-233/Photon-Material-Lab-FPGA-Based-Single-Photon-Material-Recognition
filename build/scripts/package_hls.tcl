# 2020.2 在 2022 年之后会产生超出32位整数的 core_revision。
# 仅修正本项目生成的打包脚本，不修改工具安装或系统时间。
set root [file normalize [file join [file dirname [info script]] .. ..]]
set ipdir [file join $root build output hls solution1 impl ip]
set f [open [file join $ipdir run_ippack.tcl] r]
set content [read $f]; close $f
if {![regsub {set Revision\s+"[0-9]+"} $content {set Revision "1"} content]} {
    error "Cannot locate generated core revision"
}
set patched [file join $ipdir run_ippack_fixed.tcl]
set f [open $patched w]; puts $f $content; close $f
cd $ipdir
source $patched
exit
