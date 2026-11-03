`timescale 1ns/1ps
// PYNQ 版顶层：保持 TDC 黑盒层级 u_top_tdc/u_time_merge 不变。
// PS 的 DDR、MIO 由芯片硬连线连接，板外端口沿用原工程。
module pynq_top(
    input sys_clk_p, input sys_clk_n, input sys_rst_n,
    input [1:0] tdc_hit_p, input [1:0] tdc_hit_n,
    output threshold_din, output threshold_sclk, output threshold_cs_n,
    output dac1_clk, output [9:0] dac1_data,
    output dac2_clk, output [9:0] dac2_data,
    input eth_rxc, input eth_rx_ctl, input [3:0] eth_rxd,
    output eth_txc, output eth_tx_ctl, output [3:0] eth_txd,
    output [1:0] led
);
    wire ps_mode, ps_meas_en, ps_start, ps_abort, tdc_clk, tdc_rst, calibrated;
    wire ps_laser_trigger, ps_receiver_gate, ps_reference_internal;
    wire dac_clk, dac_locked, dac_rst, dac_reference;
    wire [9:0] ps_dac1_low, ps_dac1_high, ps_dac2_low, ps_dac2_high;
    wire [1:0] external_hit, selected_hit;
    // 比较器输出为 LVDS；在选择内外参考之前转换，保留事件到达时间。
    genvar channel;
    generate for (channel=0; channel<2; channel=channel+1) begin : frontend_inputs
        IBUFDS #(.IBUF_LOW_PWR("FALSE"), .IOSTANDARD("LVDS")) input_buffer(
            .I(tdc_hit_p[channel]), .IB(tdc_hit_n[channel]), .O(external_hit[channel]));
    end endgenerate
    wire hist_valid;
    wire [15:0] hist_index, ps_bin_num;
    wire [31:0] hist_count, ps_trig_num;
    wire [7:0] ps_bin_width;
    wire ps_mem_en;
    wire [3:0] ps_mem_we;
    wire [17:0] ps_mem_addr;
    wire [31:0] ps_mem_din, ps_mem_dout;
    // DAC 时钟来自板载晶振，与 PL 网口链路无关；TDC 仍为 300 MHz。
    dac_clk_wiz u_dac_clock(.clk_in1(tdc_clk), .reset(tdc_rst),
        .clk_out1(dac_clk), .locked(dac_locked));
    (* ASYNC_REG="TRUE" *) reg [2:0] dac_reset_sync = 3'b111;
    always @(posedge dac_clk or negedge dac_locked) begin
        if (!dac_locked) dac_reset_sync <= 3'b111;
        else dac_reset_sync <= {dac_reset_sync[1:0], 1'b0};
    end
    assign dac_rst = dac_reset_sync[2];
    dual_dac_trigger u_dac_outputs(
        .clk(dac_clk), .rst(dac_rst),
        .laser_trigger(ps_laser_trigger), .receiver_gate(ps_receiver_gate),
        .dac1_low(ps_dac1_low), .dac1_high(ps_dac1_high),
        .dac2_low(ps_dac2_low), .dac2_high(ps_dac2_high),
        .dac1_clk(dac1_clk), .dac1_data(dac1_data),
        .dac2_clk(dac2_clk), .dac2_data(dac2_data), .reference_trigger(dac_reference)
    );
    // [0] 为 C1/B1 测量通道；[1] 选择 B3/A3 外部参考或板内参考。
    tdc_reference_mux u_reference_mux(
        .external_reference(external_hit[1]), .internal_reference(dac_reference),
        .use_internal(ps_reference_internal), .detector_hit(external_hit[0]),
        .selected_hit(selected_hit)
    );
    top_tdc #(.ENABLE_PS(1)) u_top_tdc(
        .sys_clk_p(sys_clk_p), .sys_clk_n(sys_clk_n), .sys_rst_n(sys_rst_n),
        .tdc_hit(selected_hit), .laser_trigger_o(), .receiver_gate_o(),
        .eth_rxc(eth_rxc), .eth_rx_ctl(eth_rx_ctl), .eth_rxd(eth_rxd),
        .eth_txc(eth_txc), .eth_tx_ctl(eth_tx_ctl), .eth_txd(eth_txd), .led(led),
        .ps_mode(ps_mode), .ps_meas_en(ps_meas_en), .ps_start(ps_start), .ps_abort(ps_abort),
        .ps_laser_trigger(ps_laser_trigger),.ps_receiver_gate(ps_receiver_gate),
        .ps_trig_num(ps_trig_num), .ps_bin_num(ps_bin_num), .ps_bin_width(ps_bin_width),
        .ps_clock(tdc_clk), .ps_reset(tdc_rst), .ps_calibrated(calibrated),
        .ps_mem_en(ps_mem_en), .ps_mem_we(ps_mem_we), .ps_mem_addr(ps_mem_addr),
        .ps_mem_din(ps_mem_din), .ps_mem_dout(ps_mem_dout),
        .ps_hist_valid(hist_valid), .ps_hist_index(hist_index), .ps_hist_count(hist_count)
    );
    design_1 design_1_i(
        .threshold_din(threshold_din), .threshold_sclk(threshold_sclk), .threshold_cs_n(threshold_cs_n),
        .tdc_clk(tdc_clk), .tdc_rst(tdc_rst), .calibrated(calibrated),
        .dac_clk(dac_clk), .dac_rst(dac_rst),
        .ps_reference_internal(ps_reference_internal),
        .ps_dac1_low(ps_dac1_low), .ps_dac1_high(ps_dac1_high),
        .ps_dac2_low(ps_dac2_low), .ps_dac2_high(ps_dac2_high),
        .hist_valid(hist_valid), .hist_index(hist_index), .hist_count(hist_count),
        .ps_mode(ps_mode), .ps_meas_en(ps_meas_en), .ps_start(ps_start), .ps_abort(ps_abort),
        .ps_laser_trigger(ps_laser_trigger),.ps_receiver_gate(ps_receiver_gate),
        .ps_trig_num(ps_trig_num), .ps_bin_num(ps_bin_num), .ps_bin_width(ps_bin_width),
        .histogram_ram_en(ps_mem_en), .histogram_ram_we(ps_mem_we), .histogram_ram_addr(ps_mem_addr),
        .histogram_ram_din(ps_mem_din), .histogram_ram_dout(ps_mem_dout),
        .histogram_ram_clk(), .histogram_ram_rst()
    );
endmodule
