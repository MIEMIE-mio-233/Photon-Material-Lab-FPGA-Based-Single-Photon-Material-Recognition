set here [file dirname [file normalize [info script]]]
source [file join $here compat_2025_2.tcl]
tdc_require_2025_2
# 新工作目录从源码创建，不继承旧工具生成的综合或布线检查点。
unset -nocomplain ::env(TDC_RESUME_POST_SYNTH) ::env(TDC_RESUME_POST_ROUTE)
source [file join $here build_pynq_bit.tcl]
