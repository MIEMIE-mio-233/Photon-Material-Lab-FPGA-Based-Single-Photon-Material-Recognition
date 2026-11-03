`timescale 1ns/1ps
// AXI-Lite 100MHz <-> TDC 300MHz 控制桥。多位配置先保持稳定，
// 再通过请求翻转位跨时钟；一帧完成前禁止修改配置，避免逐位同步撕裂。
module tdc_ps_bridge (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn, FREQ_HZ 99999001" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *) input s_axi_aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *) input s_axi_aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *) input [7:0] s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input [7:0] s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input s_axi_rready,
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 300000000" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 tdc_clk CLK" *) input tdc_clk,
    input tdc_rst, input calibrated,
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 125000000" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 dac_clk CLK" *) input dac_clk,
    input dac_rst,
    input hist_valid, input [15:0] hist_index, input [31:0] hist_count,
    output reg ps_start, output reg ps_abort,
    output ps_mode, output ps_meas_en,
    output ps_laser_trigger, output ps_receiver_gate, output ps_reference_internal,
    output [9:0] ps_dac1_low, output [9:0] ps_dac1_high,
    output [9:0] ps_dac2_low, output [9:0] ps_dac2_high,
    output threshold_din, output threshold_sclk, output threshold_cs_n,
    output reg [31:0] ps_trig_num,
    output reg [15:0] ps_bin_num,
    output reg [7:0] ps_bin_width,
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 300000000" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 mem_clk CLK" *) output mem_clk,
    output mem_rst, output mem_en,
    output [3:0] mem_we, output [31:0] mem_addr, output [31:0] mem_din
);
    reg mode, busy, complete;
    reg [31:0] cfg_trig, cfg_bins, cfg_width, error_code, frame_sequence;
    reg start_toggle, abort_toggle;
    reg aw_hold, w_hold;
    reg [7:0] aw_buffer;
    reg [31:0] w_buffer;
    reg [3:0] strobe_buffer;
    assign s_axi_awready = !aw_hold && !s_axi_bvalid;
    assign s_axi_wready = !w_hold && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;
    assign s_axi_bresp = 2'b00;
    assign s_axi_rresp = 2'b00;
    wire aw_take = s_axi_awvalid && s_axi_awready;
    wire w_take = s_axi_wvalid && s_axi_wready;
    wire write_fire = (aw_hold || aw_take) && (w_hold || w_take) && !s_axi_bvalid;
    wire [7:0] wr_addr = aw_hold ? aw_buffer : s_axi_awaddr;
    wire [31:0] wr_data = w_hold ? w_buffer : s_axi_wdata;
    wire [3:0] wr_strobe = w_hold ? strobe_buffer : s_axi_wstrb;
    wire [31:0] output_read_data;
    wire [31:0] threshold_read_data;
    wire threshold_ready, threshold_busy, output_active;
    ps_threshold_control threshold_control(
        .axi_clk(s_axi_aclk), .axi_resetn(s_axi_aresetn), .dac_clk(dac_clk), .dac_rst(dac_rst),
        .capture_busy(busy), .outputs_enabled(output_active),
        .write_fire(write_fire), .write_addr(wr_addr), .write_data(wr_data), .write_strobe(wr_strobe),
        .read_addr(s_axi_araddr), .read_data(threshold_read_data),
        .ready(threshold_ready), .busy(threshold_busy),
        .threshold_din(threshold_din), .threshold_sclk(threshold_sclk), .threshold_cs_n(threshold_cs_n)
    );
    ps_output_control output_control(
        .axi_clk(s_axi_aclk),.axi_resetn(s_axi_aresetn),.tdc_clk(tdc_clk),.tdc_rst(tdc_rst),
        .dac_clk(dac_clk),.dac_rst(dac_rst),.capture_busy(busy),.threshold_ready(threshold_ready),
        .write_fire(write_fire),.write_addr(wr_addr),.write_data(wr_data),.write_strobe(wr_strobe),
        .read_addr(s_axi_araddr),.read_data(output_read_data),
        .laser_trigger(ps_laser_trigger),.receiver_gate(ps_receiver_gate),
        .reference_internal(ps_reference_internal),.output_active(output_active),
        .dac1_low(ps_dac1_low),.dac1_high(ps_dac1_high),
        .dac2_low(ps_dac2_low),.dac2_high(ps_dac2_high)
    );
    function [31:0] merge_bytes;
        input [31:0] old_value, new_value; input [3:0] strobe;
        integer j;
        begin
            merge_bytes = old_value;
            for (j=0;j<4;j=j+1) if (strobe[j]) merge_bytes[j*8+:8]=new_value[j*8+:8];
        end
    endfunction

    reg active_tdc, done_toggle;
    reg [31:0] count_tdc, error_tdc;
    (* ASYNC_REG="TRUE" *) reg [1:0] done_sync, calibrated_sync;
    reg done_seen;
    // count_tdc/error_tdc 在完成翻转后保持，AXI 端额外等一拍再读取多位结果。
    reg result_pending;
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            mode<=0; busy<=0; complete<=0; cfg_trig<=100000;
            cfg_bins<=65536; cfg_width<=3; error_code<=0; frame_sequence<=0;
            start_toggle<=0; abort_toggle<=0; aw_hold<=0; w_hold<=0;
            s_axi_bvalid<=0; s_axi_rvalid<=0; s_axi_rdata<=0;
            done_sync<=0; done_seen<=0; calibrated_sync<=0; result_pending<=0;
        end else begin
            done_sync <= {done_sync[0],done_toggle};
            calibrated_sync <= {calibrated_sync[0],calibrated};
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
            if (aw_take) begin aw_hold<=1; aw_buffer<=s_axi_awaddr; end
            if (w_take) begin w_hold<=1; w_buffer<=s_axi_wdata; strobe_buffer<=s_axi_wstrb; end
            if (done_sync[1]!=done_seen) begin
                done_seen<=done_sync[1]; result_pending<=1;
            end
            if (result_pending) begin
                result_pending<=0; busy<=0; complete<=1; error_code<=error_tdc;
                if (error_tdc==0) frame_sequence<=frame_sequence+1;
            end
            if (write_fire) begin
                aw_hold<=0; w_hold<=0; s_axi_bvalid<=1;
                case (wr_addr[7:2])
                    6'h03: if (!busy && wr_strobe[0]) mode<=wr_data[0];
                    6'h04: if (wr_strobe[0]) begin
                        if (wr_data[1] && busy) abort_toggle<=~abort_toggle;
                        else if (wr_data[0] && !busy) begin
                            if (mode && cfg_trig!=0 && cfg_bins==65536 && cfg_width<=15 && calibrated_sync[1] && threshold_ready && !threshold_busy) begin
                                start_toggle<=~start_toggle; busy<=1; complete<=0; error_code<=0;
                            end else begin complete<=1; error_code<=1; end
                        end
                    end
                    6'h05: if (!busy) cfg_trig<=merge_bytes(cfg_trig,wr_data,wr_strobe);
                    6'h06: if (!busy) cfg_bins<=merge_bytes(cfg_bins,wr_data,wr_strobe);
                    6'h07: if (!busy) cfg_width<=merge_bytes(cfg_width,wr_data,wr_strobe);
                    default: begin end
                endcase
            end
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid<=1;
                case(s_axi_araddr[7:2])
                    6'h00: s_axi_rdata<=32'h54444331;
                    6'h01: s_axi_rdata<=5; // v5：跨周期窗口、DAC2低有效，关闭时保持高电平
                    6'h02: s_axi_rdata<={28'd0,(error_code!=0),complete,busy,calibrated_sync[1]};
                    6'h03: s_axi_rdata<={31'd0,mode};
                    6'h05: s_axi_rdata<=cfg_trig;
                    6'h06: s_axi_rdata<=cfg_bins;
                    6'h07: s_axi_rdata<=cfg_width;
                    6'h08: s_axi_rdata<=frame_sequence;
                    6'h09: s_axi_rdata<=busy ? 0 : count_tdc;
                    6'h0a: s_axi_rdata<=error_code;
                    default: s_axi_rdata<=s_axi_araddr>=8'ha0 ? threshold_read_data : output_read_data;
                endcase
            end
        end
    end

    (* ASYNC_REG="TRUE" *) reg [2:0] start_sync, abort_sync;
    (* ASYNC_REG="TRUE" *) reg [1:0] mode_sync, reset_sync;
    reg start_seen, abort_seen;
    // PS 复位异步进入、TDC 域同步退出；不能依赖另一网口的时钟。
    always @(posedge tdc_clk or negedge s_axi_aresetn) begin
        if (!s_axi_aresetn) reset_sync<=0;
        else reset_sync<={reset_sync[0],1'b1};
    end
    assign ps_mode = mode_sync[1];
    // PS接管RAM不等于启动光学采集；只有有效采集事务期间使能TDC。
    assign ps_meas_en = active_tdc;
    always @(posedge tdc_clk) begin
        if (tdc_rst || !reset_sync[1]) begin
            start_sync<=0; abort_sync<=0; mode_sync<=0; start_seen<=0; abort_seen<=0;
            active_tdc<=0; done_toggle<=0; count_tdc<=0; error_tdc<=0;
            ps_start<=0; ps_abort<=0; ps_trig_num<=100000; ps_bin_num<=16'hffff; ps_bin_width<=3;
        end else begin
            start_sync<={start_sync[1:0],start_toggle};
            abort_sync<={abort_sync[1:0],abort_toggle};
            mode_sync<={mode_sync[0],mode}; ps_start<=0; ps_abort<=0;
            if (abort_sync[2]!=abort_seen) begin
                abort_seen<=abort_sync[2]; active_tdc<=0; ps_abort<=1;
                error_tdc<=2; done_toggle<=~done_toggle;
            end else if (start_sync[2]!=start_seen) begin
                start_seen<=start_sync[2]; active_tdc<=1; count_tdc<=0; error_tdc<=0;
                ps_trig_num<=cfg_trig; ps_bin_num<=cfg_bins-1; ps_bin_width<=cfg_width;
                ps_start<=1;
            end else if (active_tdc && hist_valid) begin
                if (hist_index!=count_tdc[15:0]) begin
                    active_tdc<=0; ps_abort<=1; error_tdc<=3; done_toggle<=~done_toggle;
                end else begin
                    count_tdc<=count_tdc+1;
                    if (count_tdc==65535) begin active_tdc<=0; done_toggle<=~done_toggle; end
                end
            end
        end
    end
    assign mem_clk=tdc_clk;
    assign mem_rst=tdc_rst;
    assign mem_en=active_tdc && hist_valid && hist_index==count_tdc[15:0];
    assign mem_we=mem_en ? 4'hf : 4'h0;
    // AXI BRAM Controller 使用字节地址；直方图每 bin 为 uint32。
    assign mem_addr={14'd0,hist_index,2'b00};
    assign mem_din=hist_count;
endmodule
