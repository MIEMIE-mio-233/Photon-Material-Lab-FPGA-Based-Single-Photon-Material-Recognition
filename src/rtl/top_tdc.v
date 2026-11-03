`timescale 1ns / 1ps

// Module: top_tdc -- 双通道 TDC 时间测量顶层, 集成时钟/测量/直方图/千兆网 UDP 上传
// Clocks: tdc_clk (300 MHz, 测量与控制主域) | clk_50m (50 MHz, 预留)
//         gmii_rx_clk/gmii_tx_clk (125 MHz, 以太网域) | soc_clk_50m (50 MHz, 片内振荡器)
// Resets: sys_rst (上电复位, 高有效, 由 clk_wiz locked 生成) | sys_rst_n (板卡按键复位, 以太网域)
// Params: 无 (通道数等参数在 time_merge_0 IP 配置中设定)
// Project integration source
//
// 内部层次:
//   时钟:   clk_wiz_0 (100M 差分入 -> 50M/300M) | STARTUPE3+BUFG (片内 50M, 校准基准)
//   测量:   time_merge_0 (自定义 IP: CARRY8 延时线细测量 + 码密度校准 + 粗细合并 + 芯片 DNA 授权)
//   直方图: tof (ch0-ch1 时间差直方图统计, trig_num 触发后经 FIFO 上传)
//   通信:   eth_udp_top (RGMII 千兆网) + udp_pkg_parse (命令解析) + udp_send_ctrl_cmd (数据/应答发送)
//
// 数据路径:
//   tdc_hit[1:0] -> time_merge_0 (DNA 授权门控 -> 粗细时间合并 tdc_time[127:0])
//   -> tof (ch0-ch1 差值直方图) -> tof_fifo -> udp_send_ctrl_cmd -> RGMII 上传
//   PC 命令: UDP 1234 -> udp_pkg_parse -> cmd_* -> start/config/tof_en

module top_tdc #(parameter ENABLE_PS = 1)(
    // 当前发布只提供PYNQ顶层；PL网口协议路径仍保留。
    input ps_mode, input ps_meas_en, input ps_start, input ps_abort,
    input ps_laser_trigger, input ps_receiver_gate,
    input [31:0] ps_trig_num, input [15:0] ps_bin_num, input [7:0] ps_bin_width,
    // AXI BRAM控制器在TDC时钟域访问原统计RAM；仅IDLE时交给PS。
    input ps_mem_en, input [3:0] ps_mem_we, input [17:0] ps_mem_addr,
    input [31:0] ps_mem_din, output [31:0] ps_mem_dout,
    output ps_clock, output ps_reset, output ps_calibrated,
    output ps_hist_valid, output [15:0] ps_hist_index, output [31:0] ps_hist_count,
    input                               sys_clk_p                  ,// 输入差分时钟正端 100MHz
    input                               sys_clk_n                  ,// 输入差分时钟负端 100MHz
    input                               sys_rst_n                  ,// 板卡复位按键, 低电平有效(仅用于以太网域)
    input              [   1:0]         tdc_hit                    ,// TDC 信号输入: [0]=C1/B1 测量通道 ch0, [1]=B3/A3 触发通道 ch1(需先到)
    output                              laser_trigger_o            ,// 内部CH1：激光器电触发，3.3V；默认100kHz/高5us
    output                              receiver_gate_o            ,// 内部CH2：接收器门控，3.3V；默认高8us/延迟800ns
    input                               eth_rxc                    ,// RGMII 接收时钟 125MHz
    input                               eth_rx_ctl                 ,// RGMII 接收数据有效
    input              [   3:0]         eth_rxd                    ,// RGMII 接收数据
    output                              eth_txc                    ,// RGMII 发送时钟 125MHz
    output                              eth_tx_ctl                 ,// RGMII 发送数据有效
    output             [   3:0]         eth_txd                    ,// RGMII 发送数据
    output             [   1:0]         led                         // 指示灯: [0]=时钟锁定, [1]=测量使能
);

// 时钟与复位
wire                                    tdc_clk                    ;// TDC 测量/控制主时钟 300MHz
wire                                    clk_50m                    ;// 时钟管理器输出 50MHz(预留)
wire                                    clk_300m                   ;// 时钟管理器输出 300MHz
wire                                    clk_locked                 ;// 时钟管理器锁定标志
wire                                    sys_locked                 ;// 系统时钟锁定(=clk_locked)
wire                                    sys_rst                    ;// 系统复位, 高有效(时钟未锁定即复位)

// UDP 命令(udp_pkg_parse 解析输出, gmii_rx_clk 域)
wire                                    cmd_rst                    ;// 命令: 复位
wire                                    cmd_start                  ;// 命令: 开始测量
wire                                    cmd_stop                   ;// 命令: 停止测量
wire                                    cmd_state                  ;// 命令: 状态查询
wire                                    cmd_config                 ;// 命令: 参数配置
wire                                    cmd_tof_en                 ;// 命令: tof 使能(单次采集触发)
wire                   [  15:0]         cmd_dac1                   ;// 参数: DAC 通道 1 电压(当前设计未使用)
wire                   [  15:0]         cmd_dac2                   ;// 参数: DAC 通道 2 电压(当前设计未使用)
wire                                    cmd_match_mode             ;// 参数: 符合计数模式(当前设计未使用)
wire                                    cmd_ext_clk                ;// 参数: 外部参考时钟(当前设计未使用)
wire                   [  31:0]         cmd_trig_num               ;// 参数: tof 触发数量
wire                   [  15:0]         cmd_bin_num                ;// 参数: tof BIN 总数-1
wire                   [   7:0]         cmd_bin_width              ;// 参数: BIN 宽度 = 2^n ps
wire                                    cmd_config_vaild           ;// 参数有效标志
wire                                    cmd_reply                  ;// 命令应答触发

wire                   [8*22-1:0]       sys_state                  ;// 系统状态字(当前未赋值, 应答中为 0)
wire                   [  47:0]         software_ver = 48'h2026_1010_1700;// 软件版本常量(预留)

// 实例: clk_wiz_0
// 作用: 将 100MHz 差分输入时钟倍频为 TDC 主时钟 300MHz 与预留 50MHz, 输出锁定标志
clk_wiz_0 u0_clk (
    .clk_out1                          (clk_50m                   ),// 输出时钟 1: 50MHz(预留)
    .clk_out2                          (clk_300m                  ),// 输出时钟 2: 300MHz(TDC 主时钟)
    .reset                             (1'b0                      ),// 复位: 不使用
    .locked                            (clk_locked                ),// 锁定标志
    .clk_in1_p                         (sys_clk_p                 ),// 差分输入正端
    .clk_in1_n                         (sys_clk_n                  ) // 差分输入负端
);

assign tdc_clk = clk_300m;// TDC 主时钟 = 300MHz
assign sys_locked = clk_locked;// 锁定标志直连
assign sys_rst = ~clk_locked;// 时钟未锁定期间保持复位

wire                                    soc_clk_50m                ;// 片内 50MHz 校准基准时钟

wire                                    CFGMCLK                    ;// 片内振荡器 50MHz 输出
wire                                    EOS_n                      ;// 配置完成标志(低电平阶段=启动中)

// 实例: STARTUPE3_inst
// 作用: UltraScale 片内配置振荡器与启动状态, CFGMCLK 50MHz 作校准基准, EOS 指示配置完成
STARTUPE3 #(
    .PROG_USR                          ("FALSE"                   ),// 用户时钟访问禁止
    .SIM_CCLK_FREQ                     (0.0                        ) // 仿真 CCLK 频率
)
STARTUPE3_inst (
    .CFGMCLK                           (CFGMCLK                   ),// 片内 50MHz 振荡器输出
    .EOS                               (EOS_n                     ),// 启动结束标志: 配置完成后由低变高
    .USRCCLKO                          (1'b0                      ),// 用户 CCLK 输出: 不使用
    .USRCCLKTS                         (1'b1                       ) // 用户 CCLK 三态: 保持释放
);

// 实例: BUFG_inst
// 作用: 片内 50MHz 振荡器经全局时钟缓冲后作为码密度校准基准信号
BUFG BUFG_inst (
    .O                                 (soc_clk_50m               ),// 输出: 校准基准时钟 50MHz
    .I                                 (CFGMCLK                    )  // 输入: 片内振荡器
);

// TDC 测量通道
localparam                              CH_NUM 		  = 2          ;// TDC 通道数(与 IP 配置一致)
wire                                    calibra_sig                ;// 校准基准信号(片内 50MHz)
wire                   [CH_NUM-1:0]     measure_sig                ;// 测量信号(送入延时线): [0]=ch0(C1/B1), [1]=ch1(B3/A3)
wire                   [CH_NUM-1:0]     calibra_finish             ;// 各通道码密度校准完成标志
wire                                    calibra_en                 ;// 校准使能
wire                                    tdc_meas_en                ;// 细时间测量使能(校准完成且已启动)
wire                   [64*CH_NUM-1:0]  tdc_time                   ;// 合并时间戳: 每 64 位 = 高 8 位通道号 + 低 56 位时间
wire                   [CH_NUM-1:0]     tdc_time_vaild             ;// 时间戳有效标志

assign calibra_sig = soc_clk_50m;// 校准基准 = 片内 50MHz
assign measure_sig = tdc_hit;// 测量信号 = 板卡输入(通道角色见 IP 使用说明)

// 实例: u_time_merge (自定义网表交付 IP, 详见 report/third_party_notices.md)
// 作用: 双通道粗细时间合并 TDC + 芯片 DNA 授权, 内含 CARRY8 延时线细测量/码密度校准;
//       未授权芯片(auth_ok=0)校准与测量全部停摆, 无任何数据输出
//
// ================= DCP 编译配置注意事项(缺一出错) =================
// 1. 本例化为网表交付: 声明由 rtl/time_merge_eval_bb.v(黑盒 stub)提供,
//    实现由 ip_repo/time_merge_1.1/deliver/time_merge_eval.dcp 提供;
//    DCP 为综合后网表, 不参与综合(综合期 IP 为黑盒), 在实现阶段填充
// 2. DCP 加入工程后必须设置(Tcl):
//      set_property USED_IN_SYNTHESIS false [get_files time_merge_eval.dcp]
//      set_property SCOPED_TO_CELLS {u_top_tdc/u_time_merge} [get_files time_merge_eval.dcp]
// 3. impl_1 必须挂 opt_design 前置 hook 做黑盒填充(Vivado 工程模式不自动拼接):
//      set_property STEPS.OPT_DESIGN.TCL.PRE {<工程根>/ip_repo/time_merge_1.1/deliver/pre_opt_fill.tcl} [get_runs impl_1]
//    hook 内容: read_checkpoint -cell u_top_tdc/u_time_merge <DCP绝对路径>
//    不挂 hook 症状: opt_design 报 [DRC INBB-3] Black Box Instances 错误
// 4. 延时线为 1080 实例刚体布局宏: 禁止在 XDC/hook 中对其加 LOC 锚点
//    (刚体平移必 place 失败 Place 30-1153), 由 placer 自由放置;
//    通道顺序(ch1/B3/A3 触发需先到)由外部接线/信号源延迟标定, 判据:
//    直方图峰在小值区=正确, 峰在 ~1us 回卷=顺序颠倒
// 5. DCP/hook 均为绝对路径: 工程挪目录或换机器后需重新设置上述属性与 hook 路径
// 6. 授权 DNA 已固化在网表内(槽位0=4002...2345, 槽位1=4000...8545);
//    更换授权芯片需提供新板 96bit DNA 重新生成 DCP
// 7. 接口: sys_clk 300MHz 单域; calibra_sig 需 50MHz 基准; 上电校准约 0.43s
//    (两通道信号需在位), 校准完成 tdc_time 方有输出
// ==================================================================
time_merge_eval u_time_merge(                                       //评估版网表交付: DCP 例化(授权 DNA 已固化)
    .sys_rst                           (sys_rst                   ),// 复位, 高有效
    .sys_clk                           (tdc_clk                   ),// 时钟 300MHz
    .tdc_meas_en                       (tdc_meas_en               ),// 测量使能
    .calibra_en                        (calibra_en                ),// 校准使能
    .calibra_sig                       (calibra_sig               ),// 校准基准信号
    .measure_sig                       (measure_sig               ),// 测量信号输入
    .calibra_finish                    (calibra_finish            ),// 校准完成标志
    .tdc_time                          (tdc_time                  ),// 合并时间戳输出
    .tdc_time_vaild                    (tdc_time_vaild             ) // 时间戳有效
);

// 校准启动延时: 上电后延时约 333us 再启动码密度校准, 等待时钟与模拟前端稳定
reg                    [  31:0]         start_cnt                  ;// 校准启动延时计数

always@(posedge tdc_clk)
begin
    if(sys_rst)
        start_cnt <= 'd0                                 ;// 复位清零
    else if(start_cnt == 32'd100000)
        start_cnt <= start_cnt                           ;// 计满保持(校准使能常高)
    else
        start_cnt <= start_cnt + 1'b1                    ;// 计数
end

// 测量启停控制: cmd_start 置位, cmd_stop/config/rst 清除
reg                                     tdc_work_state             ;// 测量工作状态(1=工作中)

always @(posedge tdc_clk)
    if(sys_rst)
        tdc_work_state <= 1'd0                           ;// 复位停止
    else if(cmd_start)
        tdc_work_state <= 1'd1                           ;// 启动测量
    else if(cmd_stop|cmd_config|cmd_rst)
        tdc_work_state <= 1'd0                            ;// 停止测量

assign calibra_en = (start_cnt == 32'd100000) ? 1'b1 : 1'b0;// 校准使能: 上电延时后常高(IP 内部另受授权门控)
wire local_ps_mode = ENABLE_PS ? ps_mode : 1'b0;
assign ps_clock = tdc_clk;
assign ps_reset = sys_rst;
assign ps_calibrated = &calibra_finish;
assign tdc_meas_en = calibra_finish[1]&calibra_finish[0]&(local_ps_mode ? ps_meas_en : tdc_work_state);// 测量使能: 双通道校准完成且工作中

assign led[0] = sys_locked&EOS_n;// LED0: 时钟锁定且配置完成
assign led[1] = tdc_meas_en;// LED1: 测量使能(校准完成且已启动)

// 当前PYNQ版本由AXI控制输出，内部/外部参考的选择在pynq_top完成。
// 删除旧VIO分支不改变已发布顶层ENABLE_PS=1的逻辑。
assign laser_trigger_o = ps_laser_trigger;
assign receiver_gate_o = ps_receiver_gate;

// 以太网接口信号(eth_udp_top 与命令/发送模块之间)
wire                                    gmii_tx_clk                ;// GMII 发送时钟 125MHz
wire                                    gmii_rx_clk                ;// GMII 接收时钟 125MHz
wire                                    rec_pkt_done               ;// 单包接收完成
wire                                    rec_en                     ;// 接收数据有效
wire                   [   7:0]         rec_data                   ;// 接收数据
wire                   [  15:0]         rec_byte_num               ;// 接收字节数
wire                                    tx_start_en                ;// 发送启动
wire                   [   7:0]         tx_data                    ;// 发送数据
wire                   [  15:0]         tx_byte_num                ;// 发送字节数
wire                                    tx_done                    ;// 发送完成
wire                                    tx_req                     ;// 发送读数据请求

// 实例: u_eth_udp_top
// 作用: RGMII 千兆网物理层协议栈(ARP/ICMP/UDP/GMII-RGMII 转换),
//       对外提供 UDP 命令接收通道与直方图数据发送通道
eth_udp_top u_eth_udp_top(
    .sys_rst_n                         (sys_rst_n                 ),// 复位, 低有效
    .eth_rxc                           (eth_rxc                   ),// RGMII 接收时钟
    .eth_rx_ctl                        (eth_rx_ctl                ),// RGMII 接收有效
    .eth_rxd                           (eth_rxd                   ),// RGMII 接收数据
    .eth_txc                           (eth_txc                   ),// RGMII 发送时钟
    .eth_tx_ctl                        (eth_tx_ctl                ),// RGMII 发送有效
    .eth_txd                           (eth_txd                   ),// RGMII 发送数据
    .gmii_rx_clk                       (gmii_rx_clk               ),// GMII 接收时钟
    .rec_pkt_done                      (rec_pkt_done              ),// 单包接收完成
    .rec_en                            (rec_en                    ),// 接收数据有效
    .rec_data                          (rec_data                  ),// 接收数据
    .rec_byte_num                      (rec_byte_num              ),// 接收字节数
    .gmii_tx_clk                       (gmii_tx_clk               ),// GMII 发送时钟
    .tx_start_en                       (tx_start_en               ),// 发送启动
    .tx_data                           (tx_data                   ),// 发送数据
    .tx_byte_num                       (tx_byte_num               ),// 发送字节数
    .tx_done                           (tx_done                   ),// 发送完成
    .tx_req                            (tx_req                     ) // 发送读数据请求
);

// tof 直方图 FIFO 读出侧信号(tof -> udp_send_ctrl_cmd)
wire                                    fifo_rd_en                 ;// FIFO 读使能
wire                   [   7:0]         fifo_dout                  ;// FIFO 读数据
wire                                    fifo_prog_empty            ;// FIFO 可编程空标志
wire                   [  13:0]         rd_data_count              ;// FIFO 读侧计数

// tof 参数命令(2 拍同步至 tdc_clk 域)
wire                                    tof_en                     ;// 采集启动(单次)
wire                   [  31:0]         trig_num                   ;// 触发数量
wire                   [  15:0]         bin_num                    ;// BIN 总数-1
wire                   [   7:0]         bin_width                  ;// BIN 宽度 = 2^n ps

reg                                     tof_en_r1                  ;// tof_en 同步寄存 1
reg                                     tof_en_r2                  ;// tof_en 同步寄存 2
reg                    [  31:0]         trig_num_r1                ;// trig_num 同步寄存 1
reg                    [  31:0]         trig_num_r2                ;// trig_num 同步寄存 2
reg                    [  15:0]         bin_num_r1                 ;// bin_num 同步寄存 1
reg                    [  15:0]         bin_num_r2                 ;// bin_num 同步寄存 2
reg                    [   7:0]         bin_width_r1               ;// bin_width 同步寄存 1
reg                    [   7:0]         bin_width_r2               ;// bin_width 同步寄存 2

// 命令参数 2 拍寄存同步至 tdc_clk 域
always@(posedge tdc_clk) begin
        tof_en_r1    <= cmd_tof_en   ;// tof 使能第 1 拍
        tof_en_r2    <= tof_en_r1   ;// tof 使能第 2 拍
        trig_num_r1  <= cmd_trig_num ;// 触发数量第 1 拍
        trig_num_r2  <= trig_num_r1 ;// 触发数量第 2 拍
        bin_num_r1   <= cmd_bin_num  ;// BIN 总数第 1 拍
        bin_num_r2   <= bin_num_r1  ;// BIN 总数第 2 拍
        bin_width_r1 <= cmd_bin_width;// BIN 宽度第 1 拍
        bin_width_r2 <= bin_width_r1;// BIN 宽度第 2 拍
end

assign tof_en    = local_ps_mode ? ps_start : tof_en_r2;
assign trig_num  = local_ps_mode ? ps_trig_num : trig_num_r2;
assign bin_num   = local_ps_mode ? ps_bin_num : bin_num_r2;
assign bin_width = local_ps_mode ? ps_bin_width : bin_width_r2;

// 实例: u_tof
// 作用: ch0-ch1 时间差直方图统计(65536bin), trig_num 个触发后按序读出至 FIFO;
//       注意配对语义为 ch0 减最近的 ch1, 要求触发通道(ch1)先到达
tof u_tof(
    .ps_local_mode(local_ps_mode),
    .ps_mem_en(ps_mem_en), .ps_mem_we(ps_mem_we), .ps_mem_addr(ps_mem_addr),
    .ps_mem_din(ps_mem_din), .ps_mem_dout(ps_mem_dout),
    .snapshot_valid(ps_hist_valid), .snapshot_index(ps_hist_index), .snapshot_count(ps_hist_count),
    .sys_rst                           (sys_rst | (local_ps_mode & ps_abort)),// 复位, 高有效
    .sys_clk                           (tdc_clk                   ),// 时钟 300MHz
    .tof_en                            (tof_en                    ),// 采集启动(单次)
    .trig_num                          (trig_num                  ),// 触发数量
    .bin_num                           (bin_num                   ),// BIN 总数-1
    .bin_width                         (bin_width                 ),// BIN 宽度 = 2^n ps
    .timestamp1                        ({8'd0,tdc_time[55:0]}     ),// 测量通道时间戳(ch0)
    .timestamp1_vaild                  (tdc_time_vaild[0]         ),// 测量通道有效
    .timestamp2                        ({8'd0,tdc_time[119:64]}   ),// 触发通道时间戳(ch1)
    .timestamp2_vaild                  (tdc_time_vaild[1]         ),// 触发通道有效
    .rd_fifo_clk                       (gmii_tx_clk               ),// FIFO 读侧时钟 125MHz
    .fifo_rd_en                        (fifo_rd_en                ),// FIFO 读使能
    .fifo_dout                         (fifo_dout                 ),// FIFO 读数据
    .rd_data_count                     (rd_data_count             ),// FIFO 读侧计数
    .fifo_prog_empty                   (fifo_prog_empty            ) // FIFO 可编程空标志
);

// 实例: u_udp_pkg_parse
// 作用: 解析 PC 下发的 UDP 命令载荷(55 AA cmd [参数] xor), 输出控制命令与 tof 参数
udp_pkg_parse u_udp_pkg_parse(
    .clk                               (gmii_rx_clk               ),// 时钟 125MHz
    .rst                               (sys_rst                   ),// 复位, 高有效
    .rec_en                            (rec_en                    ),// 接收数据有效
    .rec_data                          (rec_data                  ),// 接收数据
    .cmd_rst                           (cmd_rst                   ),// 命令: 复位
    .cmd_start                         (cmd_start                 ),// 命令: 开始
    .cmd_stop                          (cmd_stop                  ),// 命令: 停止
    .cmd_state                         (cmd_state                 ),// 命令: 状态查询
    .cmd_config                        (cmd_config                ),// 命令: 参数配置
    .cmd_tof_en                        (cmd_tof_en                ),// 命令: tof 使能
    .cmd_dac1                          (cmd_dac1                  ),// 参数: DAC1 电压(未使用)
    .cmd_dac2                          (cmd_dac2                  ),// 参数: DAC2 电压(未使用)
    .cmd_match_mode                    (cmd_match_mode            ),// 参数: 符合模式(未使用)
    .cmd_ext_clk                       (cmd_ext_clk               ),// 参数: 外部时钟(未使用)
    .cmd_trig_num                      (cmd_trig_num              ),// 参数: 触发数量
    .cmd_bin_num                       (cmd_bin_num               ),// 参数: BIN 总数
    .cmd_bin_width                     (cmd_bin_width             ),// 参数: BIN 宽度
    .cmd_config_vaild                  (cmd_config_vaild          ),// 参数有效标志
    .cmd_reply                         (cmd_reply                  ) // 命令应答触发
);

// 实例: u_udp_send_ctrl_cmd
// 作用: 直方图数据打包上传(1024B/包)与命令应答(28B, 含 22 字节系统状态字)
udp_send_ctrl_cmd u_udp_send_ctrl_cmd(
    .sys_rst                           (sys_rst                   ),// 复位, 高有效
    .gmii_tx_clk                       (gmii_tx_clk               ),// 时钟 125MHz
    .tx_req                            (tx_req                    ),// 发送读数据请求
    .tx_data                           (tx_data                   ),// 发送数据
    .tx_start_en                       (tx_start_en               ),// 发送启动
    .tx_byte_num                       (tx_byte_num               ),// 发送字节数
    .rd_data_count                     (rd_data_count             ),// FIFO 读侧计数
    .fifo_prog_empty                   (fifo_prog_empty           ),// FIFO 可编程空标志
    .fifo_dout                         (fifo_dout                 ),// FIFO 读数据
    .fifo_rd_en                        (fifo_rd_en                ),// FIFO 读使能
    .cmd_rst                           (cmd_rst                   ),// 命令: 复位
    .cmd_start                         (cmd_start                 ),// 命令: 开始
    .cmd_stop                          (cmd_stop                  ),// 命令: 停止
    .cmd_state                         (cmd_state                 ),// 命令: 状态查询
    .cmd_config                        (cmd_config                ),// 命令: 参数配置
    .cmd_reply                         (cmd_reply                 ),// 命令应答触发
    .cmd_tof_en                        (cmd_tof_en                ),// 命令: tof 使能
    .sys_state                         (sys_state                  ) // 系统状态字(未赋值, 应答为 0)
);

endmodule
