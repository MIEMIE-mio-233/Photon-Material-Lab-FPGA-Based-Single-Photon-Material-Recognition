`timescale 1ns/1ps
// 比较器前端的慢速阈值设置，独立于产生触发/门控波形的两路高速 DAC。
// AXI 域保持整组 mV 参数直到 DAC 域返回 ACK；发送两路且等待模拟建立时间后确认。
module ps_threshold_control #(
    parameter integer SETTLE_CYCLES = 625 // 125MHz 下等待 5us，不能视为模拟电压回读。
)(
    input axi_clk, input axi_resetn, input dac_clk, input dac_rst,
    input capture_busy, input outputs_enabled,
    input write_fire, input [7:0] write_addr, input [31:0] write_data,
    input [3:0] write_strobe, input [7:0] read_addr,
    output reg [31:0] read_data,
    output ready, output busy,
    output threshold_din, output threshold_sclk, output threshold_cs_n
);
    localparam [15:0] DEFAULT_MV = 16'd300;
    reg [31:0] cfg_a, cfg_b, actual_a, actual_b, sequence_count;
    reg request_toggle, pending, result_wait, rejected;
    reg ack_toggle, boot_ready;
    reg [15:0] applied_a, applied_b;
    (* ASYNC_REG="TRUE" *) reg [1:0] ack_sync, boot_sync;
    (* ASYNC_REG="TRUE" *) reg [15:0] actual_a_meta, actual_a_sync;
    (* ASYNC_REG="TRUE" *) reg [15:0] actual_b_meta, actual_b_sync;
    assign busy = pending || !boot_sync[1];
    assign ready = boot_sync[1] && !pending;
    wire editable = !capture_busy && !outputs_enabled && !busy;
    wire [11:0] code_a_read = (actual_a + 32'd2048) >> 1;
    wire [11:0] code_b_read = (actual_b + 32'd2048) >> 1;

    function [31:0] merge_bytes;
        input [31:0] old_value, new_value; input [3:0] strobe;
        integer j;
        begin
            merge_bytes = old_value;
            for (j=0;j<4;j=j+1)
                if (strobe[j]) merge_bytes[j*8+:8] = new_value[j*8+:8];
        end
    endfunction

    always @(posedge axi_clk) begin
        if (!axi_resetn) begin
            cfg_a<=DEFAULT_MV; cfg_b<=DEFAULT_MV;
            actual_a<=DEFAULT_MV; actual_b<=DEFAULT_MV; sequence_count<=0;
            request_toggle<=0; pending<=0; result_wait<=0; rejected<=0;
            ack_sync<=0; boot_sync<=0;
            actual_a_meta<=DEFAULT_MV; actual_a_sync<=DEFAULT_MV;
            actual_b_meta<=DEFAULT_MV; actual_b_sync<=DEFAULT_MV;
        end else begin
            ack_sync<={ack_sync[0],ack_toggle};
            boot_sync<={boot_sync[0],boot_ready};
            actual_a_meta<=applied_a; actual_a_sync<=actual_a_meta;
            actual_b_meta<=applied_b; actual_b_sync<=actual_b_meta;
            if (pending && ack_sync[1]==request_toggle) result_wait<=1;
            // ACK 后额外等一拍，多位返回参数已稳定再更新 AXI 可见值。
            if (result_wait) begin
                actual_a<=actual_a_sync; actual_b<=actual_b_sync;
                sequence_count<=sequence_count+1; pending<=0; result_wait<=0;
            end
            if (write_fire) begin
                case (write_addr[7:2])
                    6'h28: if (editable) cfg_a<=merge_bytes(cfg_a,write_data,write_strobe);
                    6'h29: if (editable) cfg_b<=merge_bytes(cfg_b,write_data,write_strobe);
                    6'h2a: if (write_strobe[0] && write_data[0]) begin
                        // 阈值步进 2mV；零表示真实 0V，不沿用旧 UDP 的“保持”含义。
                        if (editable && cfg_a<=1000 && cfg_b<=1000 && !cfg_a[0] && !cfg_b[0]) begin
                            request_toggle<=~request_toggle; pending<=1; rejected<=0;
                        end else rejected<=1;
                    end
                    default: begin end
                endcase
            end
        end
    end
    always @(*) begin
        case (read_addr[7:2])
            6'h28: read_data=cfg_a;                    // 0xA0：编辑值 A，mV。
            6'h29: read_data=cfg_b;                    // 0xA4：编辑值 B，mV。
            6'h2b: read_data={29'd0,rejected,ready,busy};// 0xAC：拒绝/就绪/忙。
            6'h2c: read_data=actual_a;                 // 0xB0：已发送 A，mV。
            6'h2d: read_data=actual_b;                 // 0xB4：已发送 B，mV。
            6'h2e: read_data=sequence_count;           // 0xB8：完整更新序号。
            6'h2f: read_data={4'd0,code_b_read,4'd0,code_a_read};
            6'h30: read_data=32'h000203e8;             // 0xC0：步进2mV / 上限1000mV。
            6'h31: read_data=32'h4c564453;             // 0xC4：LVDS 输入版本标识。
            default: read_data=0;
        endcase
    end

    (* ASYNC_REG="TRUE" *) reg [2:0] request_sync;
    (* ASYNC_REG="TRUE" *) reg [1:0] reset_sync;
    (* ASYNC_REG="TRUE" *) reg [15:0] cfg_a_meta, cfg_a_sync;
    (* ASYNC_REG="TRUE" *) reg [15:0] cfg_b_meta, cfg_b_sync;
    wire reset_dac = dac_rst || !reset_sync[1];
    always @(posedge dac_clk or negedge axi_resetn) begin
        if (!axi_resetn) reset_sync<=0;
        else reset_sync<={reset_sync[0],1'b1};
    end
    // 数据总线保持至 ACK，toggle 延后到第三级才检测，不重采样 TDC 事件输入。
    always @(posedge dac_clk) begin
        if (reset_dac) begin
            request_sync<=0; cfg_a_meta<=DEFAULT_MV; cfg_a_sync<=DEFAULT_MV;
            cfg_b_meta<=DEFAULT_MV; cfg_b_sync<=DEFAULT_MV;
        end else begin
            request_sync<={request_sync[1:0],request_toggle};
            cfg_a_meta<=cfg_a[15:0]; cfg_a_sync<=cfg_a_meta;
            cfg_b_meta<=cfg_b[15:0]; cfg_b_sync<=cfg_b_meta;
        end
    end

    localparam BOOT=0, BOOT_SETTLE=1, IDLE=2, PREPARE_A=3, SEND_A=4,
               WAIT_A_BUSY=5, WAIT_A_DONE=6, PREPARE_B=7, SEND_B=8,
               WAIT_B_BUSY=9, WAIT_B_DONE=10, SETTLE=11;
    reg [3:0] state;
    reg [15:0] hold_a, hold_b;
    reg transaction_toggle, dac_toggle, dac_channel;
    reg [11:0] dac_code;
    reg [15:0] settle_count;
    wire dac_idle;
    dac_ctrl #(.C_DEF_CODE(12'd1174), .C_SERIAL_DIV(4)) threshold_dac(
        .i_clk(dac_clk), .i_rst_n(!reset_dac), .i_dac_tog(dac_toggle),
        .i_dac_ch(dac_channel), .i_dac_code(dac_code), .o_idle(dac_idle),
        .o_dac_din(threshold_din), .o_dac_sclk(threshold_sclk), .o_dac_cs_n(threshold_cs_n)
    );
    always @(posedge dac_clk) begin
        if (reset_dac) begin
            state<=BOOT; boot_ready<=0; ack_toggle<=0; transaction_toggle<=0;
            applied_a<=DEFAULT_MV; applied_b<=DEFAULT_MV;
            hold_a<=DEFAULT_MV; hold_b<=DEFAULT_MV;
            dac_toggle<=0; dac_channel<=0; dac_code<=1174; settle_count<=0;
        end else begin
            case (state)
                BOOT: if (dac_idle) begin settle_count<=SETTLE_CYCLES; state<=BOOT_SETTLE; end
                BOOT_SETTLE: if (settle_count==0) begin boot_ready<=1; state<=IDLE; end
                             else settle_count<=settle_count-1'b1;
                IDLE: if (request_sync[2]!=ack_toggle) begin
                    hold_a<=cfg_a_sync; hold_b<=cfg_b_sync;
                    transaction_toggle<=request_sync[2]; state<=PREPARE_A;
                end
                PREPARE_A: begin dac_channel<=0; dac_code<=(hold_a+16'd2048)>>1; state<=SEND_A; end
                SEND_A: begin dac_toggle<=~dac_toggle; state<=WAIT_A_BUSY; end
                WAIT_A_BUSY: if (!dac_idle) state<=WAIT_A_DONE;
                WAIT_A_DONE: if (dac_idle) state<=PREPARE_B;
                PREPARE_B: begin dac_channel<=1; dac_code<=(hold_b+16'd2048)>>1; state<=SEND_B; end
                SEND_B: begin dac_toggle<=~dac_toggle; state<=WAIT_B_BUSY; end
                WAIT_B_BUSY: if (!dac_idle) state<=WAIT_B_DONE;
                WAIT_B_DONE: if (dac_idle) begin settle_count<=SETTLE_CYCLES; state<=SETTLE; end
                SETTLE: if (settle_count==0) begin
                    applied_a<=hold_a; applied_b<=hold_b;
                    ack_toggle<=transaction_toggle; state<=IDLE;
                end else settle_count<=settle_count-1'b1;
                default: begin state<=BOOT; boot_ready<=0; end
            endcase
        end
    end
endmodule
