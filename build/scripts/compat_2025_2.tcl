# Vivado 2025.2 的构建前检查与 IP 迁移。仅用于英文工作目录中的副本。
proc tdc_require_2025_2 {} {
    set actual [version -short]
    if {![regexp {^2025\.2($|[. ])} $actual]} {
        error "Vivado 2025.2 required; current version is $actual"
    }
    puts "TDC_TOOL_VERSION: $actual"
}

proc tdc_latest_vlnv {requested} {
    # get_ipdefs 默认查询当前目录推荐版本；保留 vendor/library/name。
    set stem [join [lrange [split $requested :] 0 2] :]
    set defs [get_ipdefs -quiet ${stem}:*]
    if {[llength $defs] != 1} {
        error "Expected one current IP definition for $stem; found: $defs"
    }
    set selected [get_property VLNV [lindex $defs 0]]
    puts "TDC_IP_SELECT: $requested -> $selected"
    return $selected
}

proc tdc_upgrade_sources {root} {
    set reports [file join $root build reports]
    file mkdir $reports
    report_ip_status -file [file join $reports source_ip_before.rpt]
    set ips [get_ips -quiet -all]
    if {[llength $ips]} {upgrade_ip $ips -log [file join $reports source_ip_upgrade.log]}
    # upgrade_ip 返回成功不代表每一个 IP 都升级成功，逐项检查锁定状态。
    foreach ip [get_ips -quiet -all] {
        if {[get_property IS_LOCKED $ip]} {error "Source IP remains locked: $ip"}
    }
    report_ip_status -file [file join $reports source_ip_after.rpt]
}

proc tdc_upgrade_base_bd {root} {
    # 基础 BD 只包含原板卡 PS 配置，升级后沿用 DDR/MIO 参数。
    # 升级失败时停止，不静默丢弃原参数。
    set cells [get_bd_cells -quiet -hierarchical -filter {TYPE == ip}]
    if {[llength $cells]} {upgrade_bd_cells $cells}
    save_bd_design
    report_ip_status -file [file join $root build reports bd_ip_after.rpt]
}
