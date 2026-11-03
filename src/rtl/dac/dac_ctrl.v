`timescale 1ns / 1ps

// Module: dac_ctrl -- TLV5618 两路阈值控制器（用户参考设计原版 + 本工程接口适配层）
// 时钟：i_clk 50 MHz（soc_clk_50m = CFGMCLK 域）。复位：i_rst_n 低有效（板上复位）。
// 换算链（数值换算在上位机，本模块只搬 12 位码值）：Vdac = code x 1mV；
//   Vth = 2 x Vdac - 2.048V => code = (Vth_mV + 2048)/2。上电默认 0.3V = 0x496（2026-10-21 起）。
// 核心状态机与数据通路是用户参考设计原版（板上验证过），**不得重排时序**：
//   SCLK 空闲低、CS 下降沿同拍出首位、DIN 与 SCLK 上升沿同拍建立、下降沿锁存——
//   自制时序重排版三轮板测写不进 B 路（OUTB 钉死上电值），整组换回原版后才通
//   （PROJECT_RECORD S11）。
// 发送结构：每次更新连发两字 {4'hc, A 路新值} + {4'h4, B 路现值}（末字更新 B 输出）；
//   上电 INI_VALUE 先发一对默认值。
// 适配层（外壳）：toggle 两级同步 + 边沿检测 + 复位消隐 15 拍（仿 tdc_cmd_cdc）；
//   dac_update 相对更新沿延迟 3 拍——码值落地后参考状态机的 r1/r2 采样链 + 锁存
//   共需 3 拍才看到新值，不延迟会把旧码发出去。

module dac_ctrl
#(
    parameter integer C_SERIAL_DIV = 4, // 125MHz / (2*4) = 15.625MHz SPI
    parameter [11:0] C_DEF_CODE = 12'h496 // 上电默认码值，0x496 => 阈值 0.300V（2026-10-21 起）
)
(
    input                  i_clk      , // 50 MHz 外设域时钟（soc_clk_50m）
    input                  i_rst_n    , // 低有效异步复位（板上复位）
    input                  i_dac_tog  , // 300M 域参数更新 toggle（tdc_cmd_exec 翻转）
    input                  i_dac_ch   , // 目标 DAC 路：0=A 路、1=B 路（准静态，toggle 前已稳定）
    input  [11:0]          i_dac_code , // 目标 12 位码值（准静态，同上）
    output                 o_dac_din  , // DAC 串行数据（直连引脚）
    output                 o_dac_sclk , // DAC 串行时钟（直连引脚）
    output                 o_idle,     // SPI state machine idle after both words
    output                 o_dac_cs_n   // DAC 片选（直连引脚）
);

    //---- 参考设计信号名（sys_clk/sys_rst/通道1/2）到本工程接口的映射 ----//
    wire        sys_clk    = i_clk    ; // 50 MHz 外设域
    wire        sys_rst    = ~i_rst_n ; // 参考设计用高有效复位
    wire        dac_update ; // 更新使能（CDC 边沿脉冲，见下方适配层）
    wire [11:0] dac_ch1    ; // 通道 1（A 路）数据
    wire [11:0] dac_ch2    ; // 通道 2（B 路）数据

    //---- 适配层：码值寄存 + toggle CDC ----//
    reg  [11:0] code_a_r   ; // dac_ctrl.code_a_r：A 路码值，复位即默认
    reg  [11:0] code_b_r   ; // dac_ctrl.code_b_r：B 路码值，复位即默认
    reg         tog_s1     ; // dac_ctrl.tog_s1：toggle 第一级同步
    reg         tog_s2     ; // dac_ctrl.tog_s2：toggle 第二级同步
    reg         tog_ed     ; // dac_ctrl.tog_ed：寄存后的单拍更新脉冲
    reg  [3:0]  blank_r    ; // dac_ctrl.blank_r：复位释放消隐剩余拍数
    wire        blanking   ; // dac_ctrl.blanking：本拍处于消隐期

    localparam [3:0] C_BLANK = 4'd15; // 复位释放后的 CDC 消隐拍数（同 tdc_cmd_cdc）

    assign blanking   = (blank_r != 4'd0);
    assign dac_ch1    = code_a_r;
    assign dac_ch2    = code_b_r;

    // dac_update 相对 tog_ed 延迟 3 拍：码值在 tog_ed 拍落地，参考状态机的 r1/r2
    // 采样链 + WAIT_ILDE 锁存共需 3 拍才能看到新值——不延迟就会把旧码发出去
    // （tb 实测 word3 发成旧值的竞态）。
    reg        upd_d1  ; // dac_ctrl.upd_d1：更新沿延迟第 1 拍
    reg        upd_d2  ; // dac_ctrl.upd_d2：更新沿延迟第 2 拍
    reg        upd_d3  ; // dac_ctrl.upd_d3：更新沿延迟第 3 拍
    always @(posedge i_clk or negedge i_rst_n) begin
        if (i_rst_n == 1'b0) begin
            upd_d1 <= 1'b0;
            upd_d2 <= 1'b0;
            upd_d3 <= 1'b0;
        end else begin
            upd_d1 <= tog_ed;
            upd_d2 <= upd_d1;
            upd_d3 <= upd_d2;
        end
    end
    assign dac_update = upd_d3;

    always @(posedge i_clk or negedge i_rst_n) begin
        if (i_rst_n == 1'b0) begin
            code_a_r <= C_DEF_CODE;
            code_b_r <= C_DEF_CODE;
            tog_s1   <= 1'b0;
            tog_s2   <= 1'b0;
            tog_ed   <= 1'b0;
            blank_r  <= C_BLANK;
        end else begin
            tog_s1 <= i_dac_tog;
            tog_s2 <= tog_s1;
            tog_ed <= (blanking == 1'b1) ? 1'b0 : (tog_s1 ^ tog_s2);
            if (blank_r != 4'd0) begin
                blank_r <= blank_r - 4'd1;
            end else if (tog_ed == 1'b1) begin
                // 消隐结束后才落地码值：与更新沿同拍，参考状态机随后取缓存
                if (i_dac_ch == 1'b1) begin
                    code_b_r <= i_dac_code;
                end else begin
                    code_a_r <= i_dac_code;
                end
            end
        end
    end

    //---- 以下为用户参考设计原版（信号名照旧） ----//
    reg         dac_start   ; // 送 tlv5618 的单拍启动
    wire        dac_state   ; // tlv5618 忙闲电平（=CS_N）
    wire [15:0] dac_data    ; // 16 位发送字
    wire        set_done    ; // 一字传输完成

    reg  [11:0] dac_ch1_r1 ;//通道1数据
    reg  [11:0] dac_ch2_r1 ;//通道2数据
    reg  [11:0] dac_ch1_r2 ;//通道1数据
    reg  [11:0] dac_ch2_r2 ;//通道2数据

    always@(posedge sys_clk) dac_ch1_r1 <= dac_ch1;
    always@(posedge sys_clk) dac_ch1_r2 <= dac_ch1_r1;
    always@(posedge sys_clk) dac_ch2_r1 <= dac_ch2;
    always@(posedge sys_clk) dac_ch2_r2 <= dac_ch2_r1;

    reg        dac_update_r1                        ;
    reg        dac_update_r2                        ;
    wire       dac_update_pos = (~dac_update_r2)&dac_update_r1;
    always@(posedge sys_clk) dac_update_r1 <= dac_update;
    always@(posedge sys_clk) dac_update_r2 <= dac_update_r1;

    //parameter define
    localparam  WAIT_START  = 7'b0000001    ;
    localparam  WAIT_ILDE   = 7'b0000010    ;
    localparam  UPDATE_CH1  = 7'b0000100    ;
    localparam  WAIT_END    = 7'b0001000    ;
    localparam  UPDATE_CH2  = 7'b0010000    ;
    localparam  UPDATE_END  = 7'b0100000    ;
    localparam  INI_VALUE   = 7'b1000000    ;
    reg  [6:0]  state   =  INI_VALUE       ;
    assign o_idle = (state == WAIT_START) && !blanking;

    always@(posedge sys_clk)
        if(sys_rst)
            state <= INI_VALUE;
        else 
            case(state)
                INI_VALUE  :    state <= UPDATE_CH1;//更新初值

                WAIT_START  : if(dac_update_pos)    //等待开始更新数据
                                state <= WAIT_ILDE;
                            else
                                state <= WAIT_START;
                WAIT_ILDE :  if(dac_state)          //判断DAC状态是否空闲
                                state <= UPDATE_CH1;
                            else
                                state <= WAIT_ILDE;

                UPDATE_CH1 :    state <= WAIT_END;  //更新通道1数据

                WAIT_END :   if(set_done)           //等待通道1数据更新完成
                                state <= UPDATE_CH2;
                            else
                                state <= WAIT_END;
                UPDATE_CH2 :    state <= UPDATE_END;//更新通道2数据
                UPDATE_END : if(set_done)           //等待通道2数据更新完成
                                state <= WAIT_START;
                            else
                                state <= UPDATE_END;
                //如果状态机跳转到编码的状态之外也回到初始状态
                default : state <= WAIT_START;
            endcase

    reg  [11:0] dac_ch1_cache ;//通道1回读数据
    reg  [11:0] dac_ch2_cache ;//通道2回读数据
    reg         dac_ilde      ;//空闲状态

    always@(posedge sys_clk)
        if(sys_rst) begin
            dac_ch1_cache <= C_DEF_CODE;   //本工程：初值 = 上电默认码 0x496（原参考为 500）
            dac_ch2_cache <= C_DEF_CODE;
            dac_ilde <= 1'b0;
        end
        else begin
            if(state==WAIT_ILDE) begin      //更新缓存区
                dac_ch1_cache <= dac_ch1_r2;
                dac_ch2_cache <= dac_ch2_r2;
            end
            else if(state==INI_VALUE) begin //写入初值
                dac_ch1_cache <= C_DEF_CODE;
                dac_ch2_cache <= C_DEF_CODE;
            end
            if(state==WAIT_START)
                dac_ilde <= 1'b1;           //空闲状态反馈 1空闲
            else
                dac_ilde <= 1'b0;
        end

    reg  [15:0] dac_data_r  ;

    //通道1数据前缀4'hc,通道2数据前缀4'h4
    //第二段状态机，描述当前状态state和输入如何影响输出
    always@(posedge sys_clk)
    begin
        if(sys_rst) begin
            dac_start <= 1'b0;
            dac_data_r <= 'd0;
        end
        else begin
            if(state == UPDATE_CH1)    begin //更新数据
                dac_start <= 1'b1;
                dac_data_r <= {4'hc,dac_ch1_cache[11:0]};
            end
            else if(state == UPDATE_CH2)   begin //更新数据
                dac_start <= 1'b1;
                dac_data_r <= {4'h4,dac_ch2_cache[11:0]};
            end
            else
                dac_start <= 1'b0;
        end
    end

    assign dac_data = dac_data_r;

    // 实例：tlv5618
    // 作用：原版三线驱动（小梅哥），把 dac_data 按 CS 下降沿出首位、SCLK 上升沿
    //       建立/下降沿锁存的板上有效时序移出；DIV_PARAM=2 => SCLK = 50M/4 = 12.5 MHz
    tlv5618 #(
        .DIV_PARAM                   (C_SERIAL_DIV            )  // SCLK 12.5 MHz（快模式下器件上限 20 MHz 内）
    ) u_tlv5618 (
        .Clk                         (sys_clk                 ), // 50 MHz 外设域
        .Rst_n                       (~sys_rst                ), // 低有效复位
        .DAC_DATA                    (dac_data                ), // 16 位发送字
        .Start                       (dac_start               ), // 单拍启动
        .Set_Done                    (set_done                ), // 完成脉冲
        .DAC_CS_N                    (o_dac_cs_n              ), // 片选引脚
        .DAC_DIN                     (o_dac_din               ), // 数据引脚
        .DAC_SCLK                    (o_dac_sclk              ), // 时钟引脚
        .DAC_State                   (dac_state               )  // 忙闲电平（=CS_N，参考状态机消费）
    );

endmodule
