set here [file dirname [file normalize [info script]]]
source [file join $here compat_2025_2.tcl]
tdc_require_2025_2
set ::tdc_modern_build 1
source [file join $here create_pynq_project.tcl]
