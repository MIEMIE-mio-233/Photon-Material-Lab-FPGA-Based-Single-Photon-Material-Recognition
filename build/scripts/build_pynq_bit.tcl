set root [file normalize [file join [file dirname [info script]] .. ..]]
open_project [file join $root build output vivado tdc_pynq.xpr]
if {[get_property PART [current_project]] ne "xczu4ev-sfvc784-1-i"} {error "Unexpected target part"}
set obsolete [get_files -quiet */ps_cdc.xdc]
if {[llength $obsolete]} {remove_files $obsolete}
add_files -fileset utils_1 -norecurse [file join $root build scripts prepare_pynq_impl.tcl]
set_property STEPS.OPT_DESIGN.TCL.PRE [file join $root build scripts prepare_pynq_impl.tcl] [get_runs impl_1]
# 使用同一Vivado进程进行全局综合与实现，保留TDC黑盒所需的固定层级。
# 原有clock/RAM等IP仍可复用已有检查点。
set_property generate_synth_checkpoint false [get_files */design_1.bd]
set_property generate_synth_checkpoint false [get_files */dac_clk_wiz.xci]
set work [file join $root build output vivado]
if {[info exists ::env(TDC_RESUME_POST_ROUTE)] && $::env(TDC_RESUME_POST_ROUTE)==1} {
    # 仅报告/导出脚本改动、RTL与约束完全不变时使用，避免重复布线。
    open_checkpoint [file join $work pynq_post_route.dcp]
} else {
    if {[info exists ::env(TDC_RESUME_POST_SYNTH)] && $::env(TDC_RESUME_POST_SYNTH)==1} {
        open_checkpoint [file join $work pynq_post_synth.dcp]
    } else {
        synth_design -top pynq_top -part xczu4ev-sfvc784-1-i -flatten_hierarchy none
        write_checkpoint -force [file join $work pynq_post_synth.dcp]
    }
    # 允许复用原工程同配置的IP缓存。
    # 干净构建不依赖原机器的IP缓存。
    source [file join $root build scripts prepare_pynq_impl.tcl]
    opt_design
    place_design
    phys_opt_design
    route_design
    write_checkpoint -force [file join $work pynq_post_route.dcp]
}
set out [file join $root board overlays]
set reports [file join $root build reports]
file mkdir $reports
report_timing_summary -file [file join $reports timing_summary.rpt]
set resource_text [report_utilization -return_string]
set resource_file [open [file join $reports utilization.rpt] w]
puts $resource_file $resource_text
close $resource_file
# 为TDC布局与后续扩展保留余量；超预算不生成/部署新bit。
foreach {name ceiling} {{CLB LUTs} 61488 {Block RAM Tile} 102 DSPs 86} {
    set pattern [format {^\| %s\s+\|\s+([0-9.]+)} $name]
    if {![regexp -line $pattern $resource_text -> used]} {error "Resource counter not found: $name"}
    if {$used > $ceiling} {error "Resource budget exceeded: $name=$used limit=$ceiling"}
}
report_cdc -details -file [file join $reports cdc.rpt]
set skew_report [report_bus_skew -return_string]
set skew_file [open [file join $reports bus_skew.rpt] w]
puts $skew_file $skew_report
close $skew_file
if {[string match "*VIOLATED*" $skew_report]} {error "CDC bus skew failed; do not deploy this bitstream"}
set paths [get_timing_paths -quiet -max_paths 1 -slack_lesser_than 0]
if {[llength $paths]} {error "Timing failed; do not deploy this bitstream"}
set hold_paths [get_timing_paths -quiet -delay_type min -max_paths 1 -slack_lesser_than 0]
if {[llength $hold_paths]} {error "Hold timing failed; do not deploy this bitstream"}
write_bitstream -force [file join $out tdc_pynq.bit]
# 2020.2导出到 sources_1/bd/design_1/，2025.2按源目录名导出为 sources_1/bd/bd/，按glob适配。
set hwh_candidates [glob -nocomplain [file join $root build output vivado tdc_pynq.gen sources_1 bd * hw_handoff design_1.hwh]]
if {![llength $hwh_candidates]} {error "HWH handoff not found under tdc_pynq.gen/sources_1/bd"}
file copy -force [lindex $hwh_candidates 0] [file join $out tdc_pynq.hwh]
puts "OVERLAY_READY: $out (not downloaded to board)"
exit
