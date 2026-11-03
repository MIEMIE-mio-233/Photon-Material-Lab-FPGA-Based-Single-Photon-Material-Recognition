`timescale 1ns/1ps
// 网页 DAC 输出控制寄存器（AXI 100MHz / 波形 125MHz / 参考选择 300MHz）：AXI域保存编辑值，提交后整组跨域，在周期边界生效。
// enable独立同步，因此连续输出不依赖TDC校准、采集启停或配置提交状态。
module ps_output_control(
    input axi_clk, input axi_resetn, input tdc_clk, input tdc_rst,
    input dac_clk, input dac_rst, input capture_busy, input threshold_ready,
    input write_fire, input [7:0] write_addr, input [31:0] write_data,
    input [3:0] write_strobe, input [7:0] read_addr,
    output reg [31:0] read_data,
    output laser_trigger, output receiver_gate,
    output reference_internal, output output_active,
    output [9:0] dac1_low, output [9:0] dac1_high,
    output [9:0] dac2_low, output [9:0] dac2_high
);
    reg enabled, request_toggle, busy, request_seen, result_pending;
    reg [31:0] period_cfg, laser_delay_cfg, laser_width_cfg, gate_delay_cfg, gate_width_cfg;
    reg [31:0] period_active, laser_delay_active, laser_width_active, gate_delay_active, gate_width_active;
    reg error_active;
    reg [31:0] sequence_count;
    reg ack_toggle, error_tdc;
    reg [31:0] period_result, laser_delay_result, laser_width_result, gate_delay_result, gate_width_result;
    wire running;
    wire reset_tdc;
    (* ASYNC_REG="TRUE" *) reg [1:0] ack_sync, running_sync, enabled_status_sync;
    assign output_active = enabled || enabled_status_sync[1];
    (* ASYNC_REG="TRUE" *) reg [1:0] enable_sync, reset_sync;
    (* ASYNC_REG="TRUE" *) reg [2:0] request_sync;
    reg ack_seen, pending_tdc, apply_toggle, applied_seen;
    wire applied_toggle, generator_error;
    wire [31:0] gen_period, gen_laser_delay, gen_laser_width, gen_gate_delay, gen_gate_width;
    reg [31:0] period_hold, laser_delay_hold, laser_width_hold, gate_delay_hold, gate_width_hold;

    // 3PD5651E 模块输出反相：名义 +/-5V 时 512 约为 0V，102 约为 +4V。
    // 这是原始码值，不是校准电压；必须以模块电位器及实际负载测量为准。
    reg reference_cfg;
    reg [31:0] dac1_levels_cfg, dac2_levels_cfg;
    (* ASYNC_REG="TRUE" *) reg [1:0] reference_sync, reference_status_sync, dac_ready_sync;
    (* ASYNC_REG="TRUE" *) reg [31:0] dac1_levels_meta, dac1_levels_dac;
    (* ASYNC_REG="TRUE" *) reg [31:0] dac2_levels_meta, dac2_levels_dac;
    (* ASYNC_REG="TRUE" *) reg [31:0] dac1_levels_back_meta, dac1_levels_back;
    (* ASYNC_REG="TRUE" *) reg [31:0] dac2_levels_back_meta, dac2_levels_back;
    assign reference_internal = reference_sync[1];
    assign dac1_low = dac1_levels_dac[9:0];
    assign dac1_high = dac1_levels_dac[25:16];
    assign dac2_low = dac2_levels_dac[9:0];
    assign dac2_high = dac2_levels_dac[25:16];
    always @(posedge tdc_clk) begin
        if (tdc_rst || !axi_resetn) reference_sync <= 0;
        else reference_sync <= {reference_sync[0], reference_cfg};
    end
    always @(posedge dac_clk) begin
        if (reset_tdc) begin
            dac1_levels_meta <= 32'h00660200; dac1_levels_dac <= 32'h00660200;
            dac2_levels_meta <= 32'h00660200; dac2_levels_dac <= 32'h00660200;
        end else begin
            dac1_levels_meta <= dac1_levels_cfg; dac1_levels_dac <= dac1_levels_meta;
            dac2_levels_meta <= dac2_levels_cfg; dac2_levels_dac <= dac2_levels_meta;
        end
    end
    function [31:0] merge_bytes;
        input [31:0] old_value,new_value; input [3:0] strobe;
        integer k;
        begin
            merge_bytes=old_value;
            for(k=0;k<4;k=k+1) if(strobe[k]) merge_bytes[k*8+:8]=new_value[k*8+:8];
        end
    endfunction

    always @(posedge axi_clk) begin
        if(!axi_resetn) begin
            enabled<=0; reference_cfg<=0; reference_status_sync<=0; dac_ready_sync<=0;
            dac1_levels_cfg<=32'h00660200; dac2_levels_cfg<=32'h00660200;
            dac1_levels_back_meta<=32'h00660200; dac1_levels_back<=32'h00660200;
            dac2_levels_back_meta<=32'h00660200; dac2_levels_back<=32'h00660200;
            request_toggle<=0; busy<=0; ack_sync<=0; ack_seen<=0;
            running_sync<=0; enabled_status_sync<=0; result_pending<=0;
            period_cfg<=1250; laser_delay_cfg<=0; laser_width_cfg<=625;
            gate_delay_cfg<=1100; gate_width_cfg<=250;
            period_active<=1250; laser_delay_active<=0; laser_width_active<=625;
            gate_delay_active<=1100; gate_width_active<=250;
            sequence_count<=0; error_active<=0;
        end else begin
            reference_status_sync <= {reference_status_sync[0], reference_sync[1]};
            dac_ready_sync <= {dac_ready_sync[0], !dac_rst};
            dac1_levels_back_meta<=dac1_levels_dac; dac1_levels_back<=dac1_levels_back_meta;
            dac2_levels_back_meta<=dac2_levels_dac; dac2_levels_back<=dac2_levels_back_meta;
            ack_sync<={ack_sync[0],ack_toggle};
            running_sync<={running_sync[0],running};
            enabled_status_sync<={enabled_status_sync[0],enable_sync[1]};
            if(ack_sync[1]!=ack_seen) begin ack_seen<=ack_sync[1];result_pending<=1;end
            // DAC域返回值在ACK后保持；再等一拍读取整组，避免多位数据撕裂。
            if(result_pending) begin
                result_pending<=0;busy<=0;error_active<=error_tdc;
                period_active<=period_result;laser_delay_active<=laser_delay_result;
                laser_width_active<=laser_width_result;gate_delay_active<=gate_delay_result;
                gate_width_active<=gate_width_result;sequence_count<=sequence_count+1;
            end
            if(write_fire) case(write_addr[7:2])
                6'h10: if(write_strobe[0]) begin
                    if (!write_data[0]) enabled<=0; // 关闭不受采集/提交状态限制
                    else if (threshold_ready && dac_ready_sync[1] && !busy && reference_cfg==reference_status_sync[1] &&
                        dac1_levels_cfg==dac1_levels_back && dac2_levels_cfg==dac2_levels_back) enabled<=1;
                end
                6'h11: if(write_strobe[0] && write_data[0] && !busy) begin
                    request_toggle<=~request_toggle;busy<=1;
                end
                6'h12: if(!busy) period_cfg<=merge_bytes(period_cfg,write_data,write_strobe);
                6'h13: if(!busy) laser_delay_cfg<=merge_bytes(laser_delay_cfg,write_data,write_strobe);
                6'h14: if(!busy) laser_width_cfg<=merge_bytes(laser_width_cfg,write_data,write_strobe);
                6'h15: if(!busy) gate_delay_cfg<=merge_bytes(gate_delay_cfg,write_data,write_strobe);
                6'h16: if(!busy) gate_width_cfg<=merge_bytes(gate_width_cfg,write_data,write_strobe);
                6'h1e: if(write_strobe[0] && !capture_busy && !enabled && !enabled_status_sync[1] && !busy)
                    reference_cfg<=write_data[0];
                6'h20: if(!capture_busy && !enabled && !enabled_status_sync[1] && !busy)
                    dac1_levels_cfg<=merge_bytes(dac1_levels_cfg,write_data,write_strobe) & 32'h03ff03ff;
                6'h21: if(!capture_busy && !enabled && !enabled_status_sync[1] && !busy)
                    dac2_levels_cfg<=merge_bytes(dac2_levels_cfg,write_data,write_strobe) & 32'h03ff03ff;
                default: begin end
            endcase
        end
    end
    always @(*) begin
        read_data=0;
        case(read_addr[7:2])
            6'h10: read_data={31'd0,enabled};
            6'h12: read_data=period_cfg;
            6'h13: read_data=laser_delay_cfg;
            6'h14: read_data=laser_width_cfg;
            6'h15: read_data=gate_delay_cfg;
            6'h16: read_data=gate_width_cfg;
            6'h17: read_data={28'd0,enabled_status_sync[1],error_active,busy,running_sync[1]};
            6'h18: read_data=period_active;
            6'h19: read_data=laser_delay_active;
            6'h1a: read_data=laser_width_active;
            6'h1b: read_data=gate_delay_active;
            6'h1c: read_data=gate_width_active;
            6'h1d: read_data=sequence_count;
            6'h1e: read_data={31'd0,reference_cfg};
            6'h1f: read_data={29'd0,(reference_cfg!=reference_status_sync[1]),dac_ready_sync[1],reference_status_sync[1]};
            6'h20: read_data=dac1_levels_cfg;
            6'h21: read_data=dac2_levels_cfg;
            6'h22: read_data=125000000; // 实际 DAC 时钟，也是脉冲参数的量化时钟
            6'h24: read_data=dac1_levels_back;
            6'h25: read_data=dac2_levels_back;
            default: begin end
        endcase
    end
    always @(posedge dac_clk or negedge axi_resetn) begin
        if(!axi_resetn) reset_sync<=0;
        else reset_sync<={reset_sync[0],1'b1};
    end
    assign reset_tdc=dac_rst || !reset_sync[1];
    // 校验在DAC域进行。非法提交也ACK，但保留上次生效参数。
    wire valid_cfg=period_cfg>=2 && laser_width_cfg>=1 && gate_width_cfg>=1 &&
        laser_width_cfg<period_cfg && gate_width_cfg<period_cfg &&
        laser_delay_cfg<period_cfg && gate_delay_cfg<period_cfg;
    always @(posedge dac_clk) begin
        if(reset_tdc) begin
            enable_sync<=0;request_sync<=0;request_seen<=0;pending_tdc<=0;
            ack_toggle<=0;apply_toggle<=0;applied_seen<=0;error_tdc<=0;
            period_hold<=1250;laser_delay_hold<=0;laser_width_hold<=625;
            gate_delay_hold<=1100;gate_width_hold<=250;
            period_result<=1250;laser_delay_result<=0;laser_width_result<=625;
            gate_delay_result<=1100;gate_width_result<=250;
        end else begin
            enable_sync<={enable_sync[0],enabled};
            request_sync<={request_sync[1:0],request_toggle};
            if(request_sync[2]!=request_seen) begin
                request_seen<=request_sync[2];
                if(valid_cfg) begin
                    period_hold<=period_cfg;laser_delay_hold<=laser_delay_cfg;
                    laser_width_hold<=laser_width_cfg;gate_delay_hold<=gate_delay_cfg;
                    gate_width_hold<=gate_width_cfg;apply_toggle<=~apply_toggle;
                    applied_seen<=applied_toggle;pending_tdc<=1;
                end else begin error_tdc<=1;ack_toggle<=~ack_toggle;end
            end
            if(pending_tdc && applied_toggle!=applied_seen) begin
                pending_tdc<=0;error_tdc<=generator_error;
                period_result<=gen_period;laser_delay_result<=gen_laser_delay;
                laser_width_result<=gen_laser_width;gate_delay_result<=gen_gate_delay;
                gate_width_result<=gen_gate_width;ack_toggle<=~ack_toggle;
            end
        end
    end
    internal_trigger_gen #(
        .DEFAULT_PERIOD(1250), .DEFAULT_LASER_DELAY(0), .DEFAULT_LASER_WIDTH(625),
        .DEFAULT_RECEIVER_DELAY(1100), .DEFAULT_RECEIVER_WIDTH(250)
    ) generator(
        .clk(dac_clk),.rst(reset_tdc),.enable(enable_sync[1]),.apply_toggle(apply_toggle),
        .cfg_period(period_hold),.cfg_laser_delay(laser_delay_hold),.cfg_laser_width(laser_width_hold),
        .cfg_receiver_delay(gate_delay_hold),.cfg_receiver_width(gate_width_hold),
        .laser_trigger(laser_trigger),.receiver_gate(receiver_gate),.running(running),
        .config_error(generator_error),.applied_toggle(applied_toggle),
        .active_period(gen_period),.active_laser_delay(gen_laser_delay),.active_laser_width(gen_laser_width),
        .active_receiver_delay(gen_gate_delay),.active_receiver_width(gen_gate_width)
    );
endmodule
