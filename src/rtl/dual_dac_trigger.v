`timescale 1ns/1ps
// ATK-MO5651D：两路 10 位 3PD5651E 并行接口。
// FPGA 上升沿更新数据，外送时钟反相，DAC 在半周期后采样。
// DAC1高电平触发；DAC2低电平开启探测，逻辑窗口1映射到模拟低电平。
// 关闭输出后仍送时钟：DAC1保持低电平，DAC2保持高电平以关闭探测。
module dual_dac_trigger(
    input clk, input rst, input laser_trigger, input receiver_gate,
    input [9:0] dac1_low, input [9:0] dac1_high,
    input [9:0] dac2_low, input [9:0] dac2_high,
    output dac1_clk, output reg [9:0] dac1_data = 10'd512,
    output dac2_clk, output reg [9:0] dac2_data = 10'd102,
    output reg reference_trigger = 1'b0
);
    reg laser_sample = 0;
    // XDC 将数据寄存器放入 I/O，以缩短并固定数据到引脚的延迟。
    always @(posedge clk) begin
        if (rst) begin
            dac1_data <= 10'd512;
            dac2_data <= 10'd102;
            laser_sample <= 0;
        end else begin
            dac1_data <= laser_trigger ? dac1_high : dac1_low;
            dac2_data <= receiver_gate ? dac2_low : dac2_high;
            laser_sample <= laser_trigger;
        end
    end
    // 对齐外送 DAC 时钟上升沿，但不含 DAC/运放/线缆/激光器的模拟延迟。
    // 因此内部参考启用后仍需重新标定测距零点和特征窗口。
    always @(negedge clk) begin
        if (rst) reference_trigger <= 0;
        else reference_trigger <= laser_sample;
    end
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS"), .SRVAL(1'b0)) u_dac1_clock(
        .C(clk), .D1(1'b0), .D2(1'b1), .SR(rst), .Q(dac1_clk));
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS"), .SRVAL(1'b0)) u_dac2_clock(
        .C(clk), .D1(1'b0), .D2(1'b1), .SR(rst), .Q(dac2_clk));
endmodule
