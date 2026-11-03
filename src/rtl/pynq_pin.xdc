# ============================================================
# PIN.xdc -- zu4_tdc 顶层约束(ATK DFZU2EG/ZU4EV, xczu4ev-sfvc784-1-i)
# 分组: 时钟 | TDC输入 | 复位/LED | 以太网 | 时钟组 | debug hub
# 注意: time_merge 为网表交付 IP(黑盒+DCP), 延时线为 1080 实例刚体
#       布局宏, 禁止对其加 LOC 锚点(刚体平移必 place 失败), 由 placer
#       自由放置; 两通道顺序(ch1/K14 触发先到)由外部接线/信号源延迟标定
#       (判据: 直方图峰在小值区=正确, 峰在 ~1us 回卷=顺序颠倒)
# ============================================================

# ---------------- 时钟输入(100MHz 差分, MMCM 倍频 300MHz TDC 主时钟) ----------------
create_clock -period 10.000 -name sys_clk_p [get_ports sys_clk_p]
set_property PACKAGE_PIN  AE5 [get_ports sys_clk_p]
set_property PACKAGE_PIN  AF5 [get_ports sys_clk_n]
set_property IOSTANDARD DIFF_HSTL_I_12 [get_ports sys_clk_p]
set_property IOSTANDARD DIFF_HSTL_I_12 [get_ports sys_clk_n]

# ---------------- 比较器前端 LVDS 输入（J1，BANK66） ----------------
# ch0：C1/B1=J1-36/34；ch1：B3/A3=J1-32/30，触发须先到。
set_property -dict {PACKAGE_PIN C1 IOSTANDARD LVDS DIFF_TERM_ADV TERM_100} [get_ports {tdc_hit_p[0]}]
set_property -dict {PACKAGE_PIN B1 IOSTANDARD LVDS DIFF_TERM_ADV TERM_100} [get_ports {tdc_hit_n[0]}]
set_property -dict {PACKAGE_PIN B3 IOSTANDARD LVDS DIFF_TERM_ADV TERM_100} [get_ports {tdc_hit_p[1]}]
set_property -dict {PACKAGE_PIN A3 IOSTANDARD LVDS DIFF_TERM_ADV TERM_100} [get_ports {tdc_hit_n[1]}]
# TLV5618 阈值 DAC，默认两路比较门限0.300V（码1174），不是高速波形 DAC。
set_property -dict {PACKAGE_PIN A2 IOSTANDARD LVCMOS18} [get_ports threshold_din]
set_property -dict {PACKAGE_PIN A1 IOSTANDARD LVCMOS18} [get_ports threshold_sclk]
set_property -dict {PACKAGE_PIN B4 IOSTANDARD LVCMOS18} [get_ports threshold_cs_n]

# ---------------- 复位与指示灯(LVCMOS33) ----------------
set_property -dict {PACKAGE_PIN AH11 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]
set_property -dict {PACKAGE_PIN AE10 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN AF10 IOSTANDARD LVCMOS33} [get_ports {led[1]}]

# ---------------- 以太网 RGMII(LVCMOS18, 125MHz) ----------------
create_clock -period 8.000 -name eth_rxc [get_ports eth_rxc]
# eth_rxc 走非专用时钟引脚, 豁免专用时钟布线检查(IOBank 内 BUFG 路由)
set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets eth_rxc_IBUF_inst/O]
# 接收
set_property -dict {PACKAGE_PIN E5 IOSTANDARD LVCMOS18} [get_ports eth_rxc]
set_property -dict {PACKAGE_PIN D5 IOSTANDARD LVCMOS18} [get_ports eth_rx_ctl]
set_property -dict {PACKAGE_PIN G6 IOSTANDARD LVCMOS18} [get_ports {eth_rxd[0]}]
set_property -dict {PACKAGE_PIN F6 IOSTANDARD LVCMOS18} [get_ports {eth_rxd[1]}]
set_property -dict {PACKAGE_PIN G8 IOSTANDARD LVCMOS18} [get_ports {eth_rxd[2]}]
set_property -dict {PACKAGE_PIN F7 IOSTANDARD LVCMOS18} [get_ports {eth_rxd[3]}]
# 发送
set_property -dict {PACKAGE_PIN D6 IOSTANDARD LVCMOS18} [get_ports eth_txc]
set_property -dict {PACKAGE_PIN F8 IOSTANDARD LVCMOS18} [get_ports eth_tx_ctl]
set_property -dict {PACKAGE_PIN D7 IOSTANDARD LVCMOS18} [get_ports {eth_txd[0]}]
set_property -dict {PACKAGE_PIN E8 IOSTANDARD LVCMOS18} [get_ports {eth_txd[1]}]
set_property -dict {PACKAGE_PIN E9 IOSTANDARD LVCMOS18} [get_ports {eth_txd[2]}]
set_property -dict {PACKAGE_PIN D9 IOSTANDARD LVCMOS18} [get_ports {eth_txd[3]}]

# ---------------- 跨时钟域(eth_rxc 与 TDC 300MHz 数据经 CDC, 异步声明) ----------------
set_clock_groups -asynchronous -group [get_clocks eth_rxc] -group [get_clocks -of_objects [get_pins u_top_tdc/u0_clk/inst/mmcme4_adv_inst/CLKOUT1]]

# ---------------- debug hub(ILA 调试, 时钟=TDC 300MHz) ----------------
set_property C_CLK_INPUT_FREQ_HZ 300000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
set_property C_USER_SCAN_CHAIN 1 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets u_top_tdc/tdc_clk]

# ---------------- 双路 DAC（数字接口 3.3V，采样时钟 125MHz） ----------------
# 按 3PD5651E 数据手册设置 setup=2ns、hold=1.5ns，另留0.5ns板级偏斜。
# FPGA在上升沿更新数据，DAC时钟反相；外部器件在半拍后采样。
set_property -dict {PACKAGE_PIN D10 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports dac1_clk]
set_property -dict {PACKAGE_PIN A12 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[0]}]
set_property -dict {PACKAGE_PIN D12 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[1]}]
set_property -dict {PACKAGE_PIN A11 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[2]}]
set_property -dict {PACKAGE_PIN C12 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[3]}]
set_property -dict {PACKAGE_PIN C11 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[4]}]
set_property -dict {PACKAGE_PIN B11 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[5]}]
set_property -dict {PACKAGE_PIN B10 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[6]}]
set_property -dict {PACKAGE_PIN A10 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[7]}]
set_property -dict {PACKAGE_PIN E10 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[8]}]
set_property -dict {PACKAGE_PIN E12 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac1_data[9]}]
create_generated_clock -name dac1_forward -source [get_pins u_dac_outputs/u_dac1_clock/C] -divide_by 1 -invert [get_ports dac1_clk]
set_output_delay -clock dac1_forward -max 2.500 [get_ports {dac1_data[*]}]
set_output_delay -clock dac1_forward -min -2.000 [get_ports {dac1_data[*]}]
set_property -dict {PACKAGE_PIN B15 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports dac2_clk]
set_property -dict {PACKAGE_PIN F13 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[0]}]
set_property -dict {PACKAGE_PIN E15 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[1]}]
set_property -dict {PACKAGE_PIN D15 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[2]}]
set_property -dict {PACKAGE_PIN E14 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[3]}]
set_property -dict {PACKAGE_PIN D14 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[4]}]
set_property -dict {PACKAGE_PIN E13 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[5]}]
set_property -dict {PACKAGE_PIN B13 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[6]}]
set_property -dict {PACKAGE_PIN C14 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[7]}]
set_property -dict {PACKAGE_PIN A13 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[8]}]
set_property -dict {PACKAGE_PIN C13 IOSTANDARD LVCMOS33 DRIVE 8 SLEW FAST} [get_ports {dac2_data[9]}]
create_generated_clock -name dac2_forward -source [get_pins u_dac_outputs/u_dac2_clock/C] -divide_by 1 -invert [get_ports dac2_clk]
set_output_delay -clock dac2_forward -max 2.500 [get_ports {dac2_data[*]}]
set_output_delay -clock dac2_forward -min -2.000 [get_ports {dac2_data[*]}]
set_property IOB TRUE [get_cells -hier -filter {NAME =~ u_dac_outputs/dac?_data_reg*}]

