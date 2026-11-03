# 2025.2+目录不再允许创建旧版zynq_ultra_ps_e(如3.3)，而仓库未随附基础BD引用的
# PS实例XCI(src/bd/ip/)。在工作副本中重建XCI、烤入集成意图的PS配置，并把BD存储
# VLNV提升到当前目录版本；打开后的BD单元以XCI为准，随后脚本对单元的重复设置仅为幂等。
proc tdc_restore_base_bd {root} {
    set bd_file [file join $root src bd design_1.bd]
    if {![file exists $bd_file]} {return}
    set f [open $bd_file r]; fconfigure $f -translation binary; set json [read $f]; close $f
    set module design_1_zynq_ultra_ps_e_0_0
    if {[string first $module $json] < 0} {return}
    set xci_target [file join $root src bd ip $module "$module.xci"]
    if {[file exists $xci_target]} {return}
    create_ip -name zynq_ultra_ps_e -vendor xilinx.com -library ip -module_name $module
    set ip_obj [get_ips $module]
    # 3.5下打开的BD单元以XCI为准，事后对单元设置会被XCI还原，故在XCI内烤入集成意图配置。
    # 2020.2的SD1 MIO46..51路由在3.5合并为MIO39..51，与UART0 MIO42..43声明冲突；
    # 板卡外设由PYNQ镜像引导配置，overlay的hwh声明不参与硬件配置，故SD1不再声明。
    set_property -dict [list \
        CONFIG.PSU__FPGA_PL0_ENABLE {1} CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
        CONFIG.PSU__CRL_APB__PL0_REF_CTRL__SRCSEL {IOPLL} \
        CONFIG.PSU__NUM_FABRIC_RESETS {1} CONFIG.PSU__USE__FABRIC__RST {1} \
        CONFIG.PSU__USE__M_AXI_GP0 {1} CONFIG.PSU__MAXIGP0__DATA_WIDTH {32} \
        CONFIG.PSU__USE__M_AXI_GP2 {0} \
        CONFIG.PSU__USE__S_AXI_GP2 {1} CONFIG.PSU__SAXIGP2__DATA_WIDTH {64} \
        CONFIG.PSU__ENET3__PERIPHERAL__ENABLE {1} CONFIG.PSU__ENET3__PERIPHERAL__IO {MIO 64 .. 75} \
        CONFIG.PSU__ENET3__GRP_MDIO__ENABLE {1} CONFIG.PSU__ENET3__GRP_MDIO__IO {MIO 76 .. 77} \
        CONFIG.PSU__UART0__PERIPHERAL__ENABLE {1} CONFIG.PSU__UART0__PERIPHERAL__IO {MIO 42 .. 43} \
    ] $ip_obj
    generate_target all $ip_obj
    set gen [get_property IP_FILE $ip_obj]
    set vlnv_new [get_property IPDEF $ip_obj]
    file mkdir [file dirname $xci_target]
    file copy -force $gen $xci_target
    remove_files [get_files $gen]
    set vlnv_old "xilinx.com:ip:zynq_ultra_ps_e:3.3"
    if {$vlnv_old ne $vlnv_new && [string first $vlnv_old $json] >= 0} {
        set json [string map [list $vlnv_old $vlnv_new] $json]
        puts "TDC_BD_RESTORED: $module -> $vlnv_new"
    }
    set f [open $bd_file w]; fconfigure $f -translation binary; puts -nonewline $f $json; close $f
}
# 创建 PYNQ Overlay 工程及 BD，随后执行 build_pynq_bit.tcl。
set root [file normalize [file join [file dirname [info script]] .. ..]]
# 2020.2保持固定IP版本；2025.2入口按当前IP目录选择版本。
proc tdc_catalog_vlnv {requested} {
    if {[info exists ::tdc_modern_build] && $::tdc_modern_build} {
        return [tdc_latest_vlnv $requested]
    }
    return $requested
}
set part xczu4ev-sfvc784-1-i
set ipdir [file join $root build output hls solution1 impl ip]
if {![file exists [file join $ipdir component.xml]]} { error "Package HLS IP first (tools/package_hls.tcl)" }
file mkdir [file join $root build output]
create_project -force tdc_pynq [file join $root build output vivado] -part $part
set_property ip_repo_paths [list $ipdir] [current_project]
update_ip_catalog
# 只引用人工维护源码/IP定义，排除已有生成文件和旧wrapper。
set rtl [glob [file join $root src rtl *.v]]
set rtl [lsearch -all -inline -not -exact $rtl [file join $root src rtl design_1_wrapper.v]]
add_files $rtl
foreach sub {arp gmii_to_rgmii icmp udp} {
    add_files [glob [file join $root src rtl udp $sub *.v]]
}
add_files [glob [file join $root src rtl udp *.v]]
add_files [file join $root src rtl ps_bridge tdc_ps_bridge.v]
add_files [file join $root src rtl ps_bridge ps_output_control.v]
add_files [file join $root src rtl ps_bridge ps_threshold_control.v]
add_files [glob [file join $root src rtl dac *.v]]
foreach ip [glob [file join $root src vendor_ip * *.xci]] {
    # PYNQ分支只用AXI控制，不导入旧VIO及其约束；原prj工程仍保留。
    if {[file tail $ip] ne "time_merge_0.xci" && ![string match "vio*" [file tail $ip]]} { add_files $ip }
}
if {[info exists ::tdc_modern_build] && $::tdc_modern_build} {tdc_upgrade_sources $root}
# 调试时钟网在集成后可能被重命名，接入在综合后按时钟输出pin查询完成。
create_ip -name clk_wiz -vendor xilinx.com -library ip -module_name dac_clk_wiz
set_property -dict [list CONFIG.PRIM_SOURCE {Global_buffer} CONFIG.PRIM_IN_FREQ {300.000} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {125.000} CONFIG.USE_RESET {true} CONFIG.USE_LOCKED {true}] [get_ips dac_clk_wiz]
generate_target all [get_ips dac_clk_wiz]
set_property generate_synth_checkpoint false [get_files */dac_clk_wiz.xci]
set pin_file [file join $root build output vivado pynq_pins.xdc]
set f [open [file join $root src rtl pynq_pin.xdc] r]; fconfigure $f -encoding binary
set content [read $f]; close $f
set lines {}
foreach line [split $content "\n"] {
    if {![string match "connect_debug_port dbg_hub/clk*" $line] && ![string match "*get_debug_cores dbg_hub*" $line]} {lappend lines $line}
}
set f [open $pin_file w]; fconfigure $f -encoding binary; puts -nonewline $f [join $lines "\n"]; close $f
add_files -fileset constrs_1 $pin_file
if {[info exists ::tdc_modern_build] && $::tdc_modern_build} {tdc_restore_base_bd $root}
# import_files 把BD复制到生成目录，避免改动原工程的 design_1.bd。
import_files [file join $root src bd design_1.bd]
set bd [get_files */design_1.bd]
open_bd_design $bd
if {[info exists ::tdc_modern_build] && $::tdc_modern_build} {tdc_upgrade_base_bd $root}
set ps [get_bd_cells zynq_ultra_ps_e_0]
set ps_props [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__SRCSEL {IOPLL} \
    CONFIG.PSU__NUM_FABRIC_RESETS {1} CONFIG.PSU__USE__FABRIC__RST {1} \
    CONFIG.PSU__USE__M_AXI_GP0 {1} CONFIG.PSU__MAXIGP0__DATA_WIDTH {32} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} CONFIG.PSU__SAXIGP2__DATA_WIDTH {64} \
    CONFIG.PSU__ENET3__PERIPHERAL__ENABLE {1} CONFIG.PSU__ENET3__PERIPHERAL__IO {MIO 64 .. 75} \
    CONFIG.PSU__ENET3__GRP_MDIO__ENABLE {1} CONFIG.PSU__ENET3__GRP_MDIO__IO {MIO 76 .. 77} \
    CONFIG.PSU__UART0__PERIPHERAL__ENABLE {1} CONFIG.PSU__UART0__PERIPHERAL__IO {MIO 42 .. 43} \
]
if {![info exists ::tdc_modern_build] || !$::tdc_modern_build} {
    # 2020.2按原板卡配置声明SD1；3.5目录无法无冲突表达，见tdc_restore_base_bd注释。
    lappend ps_props \
        CONFIG.PSU__SD1__PERIPHERAL__ENABLE {1} CONFIG.PSU__SD1__PERIPHERAL__IO {MIO 46 .. 51} \
        CONFIG.PSU__SD1__GRP_CD__ENABLE {1} CONFIG.PSU__SD1__GRP_CD__IO {MIO 45}
}
set_property -dict $ps_props $ps
create_bd_cell -type module -reference tdc_ps_bridge capture
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {user.org:hls:tdc_accelerator:1.0}] accelerator
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:axi_bram_ctrl:4.1}] histogram
set_property -dict [list CONFIG.DATA_WIDTH {32} CONFIG.SINGLE_PORT_BRAM {1}] [get_bd_cells histogram]
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:axi_clock_converter:2.1}] hist_clock_bridge
# 将AXI事务从PS时钟域转换到TDC时钟域，直接读取原统计RAM，省去一份BRAM。
set_property CONFIG.ACLK_ASYNC {1} [get_bd_cells hist_clock_bridge]
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:smartconnect:1.0}] control_bus
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {3}] [get_bd_cells control_bus]
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:smartconnect:1.0}] ddr_bus
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells ddr_bus]
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:proc_sys_reset:5.0}] ps_reset
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:xlconstant:1.1}] const_one
set_property CONFIG.CONST_VAL {1} [get_bd_cells const_one]
set clk_fanout [list [get_bd_pins $ps/maxihpm0_fpd_aclk] [get_bd_pins $ps/saxihp0_fpd_aclk] \
 [get_bd_pins capture/s_axi_aclk] [get_bd_pins accelerator/ap_clk] \
 [get_bd_pins hist_clock_bridge/s_axi_aclk] [get_bd_pins control_bus/aclk] \
 [get_bd_pins ddr_bus/aclk] [get_bd_pins ps_reset/slowest_sync_clk]]
# 3.5默认启用未使用的M_AXI_HPM0_LPD(已在XCI烤入关闭)；防御性覆盖其他版本暴露的LPD时钟。
set lpd_aclk [get_bd_pins -quiet $ps/maxihpm0_lpd_aclk]
if {[llength $lpd_aclk]} {lappend clk_fanout $lpd_aclk}
connect_bd_net [get_bd_pins $ps/pl_clk0] {*}$clk_fanout
connect_bd_net [get_bd_pins $ps/pl_resetn0] [get_bd_pins ps_reset/ext_reset_in]
connect_bd_net [get_bd_pins const_one/dout] [get_bd_pins ps_reset/dcm_locked]
connect_bd_net [get_bd_pins ps_reset/peripheral_aresetn] [get_bd_pins capture/s_axi_aresetn] \
 [get_bd_pins accelerator/ap_rst_n] [get_bd_pins hist_clock_bridge/s_axi_aresetn] \
 [get_bd_pins control_bus/aresetn] [get_bd_pins ddr_bus/aresetn]
connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_HPM0_FPD] [get_bd_intf_pins control_bus/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins accelerator/m_axi_histmem] [get_bd_intf_pins control_bus/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins control_bus/M00_AXI] [get_bd_intf_pins capture/S_AXI]
connect_bd_intf_net [get_bd_intf_pins control_bus/M01_AXI] [get_bd_intf_pins accelerator/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins control_bus/M02_AXI] [get_bd_intf_pins hist_clock_bridge/S_AXI]
connect_bd_intf_net [get_bd_intf_pins hist_clock_bridge/M_AXI] [get_bd_intf_pins histogram/S_AXI]
connect_bd_intf_net [get_bd_intf_pins accelerator/m_axi_modelmem] [get_bd_intf_pins ddr_bus/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins accelerator/m_axi_resultmem] [get_bd_intf_pins ddr_bus/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins ddr_bus/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP0_FPD]
create_bd_cell -type ip -vlnv [tdc_catalog_vlnv {xilinx.com:ip:proc_sys_reset:5.0}] tdc_axi_reset
connect_bd_net [get_bd_pins $ps/pl_resetn0] [get_bd_pins tdc_axi_reset/ext_reset_in]
connect_bd_net [get_bd_pins const_one/dout] [get_bd_pins tdc_axi_reset/dcm_locked]
connect_bd_net [get_bd_pins capture/tdc_clk] [get_bd_pins hist_clock_bridge/m_axi_aclk] \
 [get_bd_pins histogram/s_axi_aclk] [get_bd_pins tdc_axi_reset/slowest_sync_clk]
connect_bd_net [get_bd_pins capture/tdc_rst] [get_bd_pins tdc_axi_reset/aux_reset_in]
connect_bd_net [get_bd_pins tdc_axi_reset/peripheral_aresetn] [get_bd_pins histogram/s_axi_aresetn] [get_bd_pins hist_clock_bridge/m_axi_aresetn]
make_bd_intf_pins_external [get_bd_intf_pins histogram/BRAM_PORTA]
set_property name histogram_ram [get_bd_intf_ports BRAM_PORTA_0]
set_property -dict [list CONFIG.MEM_SIZE {262144} CONFIG.MEM_WIDTH {32} \
 CONFIG.MEM_ECC {NONE} CONFIG.MASTER_TYPE {BRAM_CTRL} CONFIG.READ_WRITE_MODE {READ_WRITE} \
 CONFIG.READ_LATENCY {1}] [get_bd_intf_ports histogram_ram]
foreach {name direction width} {tdc_clk I 1 tdc_rst I 1 dac_clk I 1 dac_rst I 1 calibrated I 1 hist_valid I 1 hist_index I 16 hist_count I 32 ps_start O 1 ps_abort O 1 ps_mode O 1 ps_meas_en O 1 ps_laser_trigger O 1 ps_receiver_gate O 1 ps_reference_internal O 1 ps_dac1_low O 10 ps_dac1_high O 10 ps_dac2_low O 10 ps_dac2_high O 10 ps_trig_num O 32 ps_bin_num O 16 ps_bin_width O 8 threshold_din O 1 threshold_sclk O 1 threshold_cs_n O 1} {
    if {$name eq "tdc_clk" || $name eq "dac_clk"} {
        create_bd_port -dir I -type clk $name
        set_property CONFIG.FREQ_HZ [expr {$name eq "dac_clk" ? 125000000 : 300000000}] [get_bd_ports $name]
    } elseif {$name eq "tdc_rst" || $name eq "dac_rst"} {
        create_bd_port -dir I -type rst $name
        set_property CONFIG.POLARITY ACTIVE_HIGH [get_bd_ports $name]
    } elseif {$width==1} {
        create_bd_port -dir $direction $name
    } else {
        create_bd_port -dir $direction -from [expr {$width-1}] -to 0 $name
    }
    connect_bd_net [get_bd_ports $name] [get_bd_pins capture/$name]
}
set ps_space [get_bd_addr_spaces $ps/Data]
assign_bd_address -offset 0xA0000000 -range 0x40000 -target_address_space $ps_space [get_bd_addr_segs histogram/S_AXI/Mem0]
set bridge_segments [get_bd_addr_segs -of_objects [get_bd_intf_pins capture/S_AXI]]
puts "CAPTURE_SEGMENTS: $bridge_segments"
assign_bd_address -offset 0xA0040000 -range 0x10000 -target_address_space $ps_space $bridge_segments
assign_bd_address -offset 0xA0050000 -range 0x10000 -target_address_space $ps_space [get_bd_addr_segs accelerator/s_axi_control/Reg]
set hist_space [get_bd_addr_spaces -of_objects [get_bd_intf_pins accelerator/m_axi_histmem]]
assign_bd_address -offset 0xA0000000 -range 0x40000 -target_address_space $hist_space [get_bd_addr_segs histogram/S_AXI/Mem0]
exclude_bd_addr_seg -target_address_space $hist_space $bridge_segments
exclude_bd_addr_seg -target_address_space $hist_space [get_bd_addr_segs accelerator/s_axi_control/Reg]
foreach bus {modelmem resultmem} {
    set space [get_bd_addr_spaces -of_objects [get_bd_intf_pins accelerator/m_axi_$bus]]
    assign_bd_address -offset 0 -range 0x80000000 -target_address_space $space [get_bd_addr_segs $ps/SAXIGP2/HP0_DDR_LOW]
}
validate_bd_design
save_bd_design
generate_target all $bd
# 干净机器没有原工程的OOC缓存，显式生成随仓库提供的IP定义。
# BD内部的嵌套XCI只能由父BD生成，2025.2对此直接报错，故只生成顶层IP。
set top_xcis {}
foreach xci [get_files -quiet *.xci] {
    if {![string match "*sources_1/bd/*" $xci]} {lappend top_xcis $xci}
}
generate_target all $top_xcis
foreach ip_source $top_xcis {
    set_property generate_synth_checkpoint false $ip_source
}
set_property generate_synth_checkpoint false $bd
set_property top pynq_top [current_fileset]
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none [get_runs synth_1]
add_files -fileset utils_1 -norecurse [file join $root build scripts prepare_pynq_impl.tcl]
set_property STEPS.OPT_DESIGN.TCL.PRE [file join $root build scripts prepare_pynq_impl.tcl] [get_runs impl_1]
update_compile_order -fileset sources_1
puts "BD_READY: [get_property DIRECTORY [current_project]]"
exit
