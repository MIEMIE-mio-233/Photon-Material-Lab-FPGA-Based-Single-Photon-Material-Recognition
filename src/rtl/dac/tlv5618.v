`timescale 1ns/1ns

// Module: tlv5618 -- TLV5618 DAC 三线串行驱动（原版，小梅哥）
// Clocks:  Clk (50 MHz 外设域)
// Resets:  Rst_n (async, active-low)
// Params:  DIV_PARAM=2  SCLK2X 分频（SCLK = Clk/(2*DIV_PARAM)，50M/4 = 12.5 MHz）
// Author:  小梅哥（原版 v1.1）；2026-09-26 并入本工程，仅去除 #1 仿真延迟
//          （综合语义不变），其余逐行保留——与用户已验证的 dac_ctrl 参考设计配对使用。
// 注：本驱动的时序形状（CS 下降沿同拍出首位、SCLK 空闲高电平、DIN 与 SCLK 上升沿
//     同拍建立、下降沿锁存）是板上实证有效的组合，不得再"优化"重排——
//     2026-09-25/26 两轮板测证明重排后 {0100} 字写不进 B 路。

module tlv5618(
	Clk,
	Rst_n,
	
	DAC_DATA,
	Start,
	Set_Done,
	
	DAC_CS_N,
	DAC_DIN,
	DAC_SCLK,
	DAC_State
);
	
	parameter fCLK = 50;
	parameter DIV_PARAM = 2;

	input Clk;
	input Rst_n;
	input [15:0]DAC_DATA;
	input Start;
	output reg Set_Done;
	
	output reg DAC_CS_N;
	output reg DAC_DIN;
	output reg DAC_SCLK;
	output DAC_State;
	
	assign DAC_State = DAC_CS_N;
	
	reg [15:0]r_DAC_DATA;
	
	reg [3:0]DIV_CNT;//分频计数器
	reg SCLK2X;//2倍SCLK的采样时钟
	
	reg [5:0]SCLK_GEN_CNT;//SCLK生成暨序列机计数器
	
	reg en;//转换使能信号
	
	wire trans_done; //转换序列完成标志信号
	
	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)
		en  <=  1'b0;
	else if(Start)
		en  <=  1'b1;
	else if(trans_done)
		en  <=  1'b0;
	else
		en  <=  en;

	//生成2倍SCLK使能时钟计数器
	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)
		DIV_CNT  <=  4'd0;
	else if(en)begin
		if(DIV_CNT == (DIV_PARAM - 1'b1))
			DIV_CNT  <=  4'd0;
		else 
			DIV_CNT  <=  DIV_CNT + 1'b1;
	end else	
		DIV_CNT  <=  4'd0;

	//生成2倍SCLK使能时钟计数器
	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)
		SCLK2X  <=  1'b0;
	else if(en && (DIV_CNT == (DIV_PARAM - 1'b1)))
		SCLK2X  <=  1'b1;
	else
		SCLK2X  <=  1'b0;
		
	//生成序列计数器
	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)
		SCLK_GEN_CNT  <=  6'd0;
	else if(SCLK2X && en)begin
		if(SCLK_GEN_CNT == 6'd33)
			SCLK_GEN_CNT  <=  6'd0;
		else
			SCLK_GEN_CNT  <=  SCLK_GEN_CNT + 1'd1;
	end else
		SCLK_GEN_CNT  <=  SCLK_GEN_CNT;

	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)
		r_DAC_DATA  <=  16'd0;
	else if(Start)//收到开始发送命令时，寄存DAC_DATA值	
		r_DAC_DATA  <=  DAC_DATA;
	else
		r_DAC_DATA  <=  r_DAC_DATA;
				
	//依次将数据移出到DAC芯片		
	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)begin
		DAC_DIN  <=  1'b1;
		DAC_SCLK  <=  1'b0;
		DAC_CS_N <= 1'b1;
	end else if(!Set_Done && SCLK2X) begin
		case(SCLK_GEN_CNT)
			0:
				begin
					DAC_CS_N <= 1'b0;
					DAC_DIN  <= r_DAC_DATA[15];
					DAC_SCLK  <=  1'b1;
				end
		
			1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31:
				begin
					DAC_SCLK  <=  1'b0;
				end
			
			2:  begin DAC_DIN  <= r_DAC_DATA[14]; DAC_SCLK  <= 1'b1; end
			4:  begin DAC_DIN  <= r_DAC_DATA[13]; DAC_SCLK  <= 1'b1; end
			6:  begin DAC_DIN  <= r_DAC_DATA[12]; DAC_SCLK  <= 1'b1; end
			8:  begin DAC_DIN  <= r_DAC_DATA[11]; DAC_SCLK  <= 1'b1; end			
			10: begin DAC_DIN  <= r_DAC_DATA[10]; DAC_SCLK  <= 1'b1; end
			12: begin DAC_DIN  <= r_DAC_DATA[9];  DAC_SCLK  <= 1'b1; end
			14: begin DAC_DIN  <= r_DAC_DATA[8];  DAC_SCLK  <= 1'b1; end
			16: begin DAC_DIN  <= r_DAC_DATA[7];  DAC_SCLK  <= 1'b1; end	
			18: begin DAC_DIN  <= r_DAC_DATA[6];  DAC_SCLK  <= 1'b1; end
			20: begin DAC_DIN  <= r_DAC_DATA[5];  DAC_SCLK  <= 1'b1; end				
			22: begin DAC_DIN  <= r_DAC_DATA[4];  DAC_SCLK  <= 1'b1; end
			24: begin DAC_DIN  <= r_DAC_DATA[3];  DAC_SCLK  <= 1'b1; end
			26: begin DAC_DIN  <= r_DAC_DATA[2];  DAC_SCLK  <= 1'b1; end
			28: begin DAC_DIN  <= r_DAC_DATA[1];  DAC_SCLK  <= 1'b1; end			
			30: begin DAC_DIN  <= r_DAC_DATA[0];  DAC_SCLK  <= 1'b1; end
			
			32: DAC_SCLK  <= 1'b1; 
			33: DAC_CS_N  <= 1'b1;
			default:;
		endcase
	end

	assign trans_done = (SCLK_GEN_CNT == 33) && SCLK2X;
	
	always@(posedge Clk or negedge Rst_n)
	if(!Rst_n)
		Set_Done <= 1'b0;
	else if(trans_done)
		Set_Done <= 1'b1;
	else
		Set_Done <= 1'b0;
	
endmodule
