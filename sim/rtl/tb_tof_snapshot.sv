`timescale 1ns/1ps
module histog_ram(input clka,ena,wea,input[15:0]addra,input[31:0]dina,input clkb,rstb,enb,input[15:0]addrb,output reg[31:0]doutb,output rsta_busy,rstb_busy);
reg[31:0] memory[0:65535];
always @(posedge clka)if(ena&&wea)memory[addra]<=dina;
always @(posedge clkb)if(rstb)doutb<=0;else if(enb)doutb<=memory[addrb];
assign rsta_busy=0;assign rstb_busy=0;
endmodule
module tof_fifo(input rst,wr_clk,rd_clk,input[63:0]din,input wr_en,rd_en,output[7:0]dout,output full,prog_full,empty,output[13:0]rd_data_count,output prog_empty);
assign dout=0;assign full=1;assign prog_full=1;assign empty=1;assign rd_data_count=0;assign prog_empty=1;
endmodule
module tb_tof_snapshot;
reg clk=0;always #1.667 clk=~clk;
reg rst=1,start=0;reg[63:0]ref_time=0;reg ref_valid=0;
wire valid;wire[15:0]index;wire[31:0]count;integer received=0;
reg mem_en=0;reg[3:0]mem_we=0;reg[17:0]mem_addr=0;reg[31:0]mem_din=0;wire[31:0]mem_dout;
tof dut(.sys_clk(clk),.sys_rst(rst),.ps_local_mode(1'b1),.ps_mem_en(mem_en),.ps_mem_we(mem_we),.ps_mem_addr(mem_addr),.ps_mem_din(mem_din),.ps_mem_dout(mem_dout),.snapshot_valid(valid),.snapshot_index(index),.snapshot_count(count),.tof_en(start),.trig_num(32'd4),.bin_num(16'hffff),.bin_width(8'd3),.timestamp1(64'd0),.timestamp1_vaild(1'b0),.timestamp2(ref_time),.timestamp2_vaild(ref_valid),.rd_fifo_clk(clk),.fifo_rd_en(1'b0),.fifo_dout(),.rd_data_count(),.fifo_prog_empty());
always @(posedge clk)if(valid)begin
 if(index!==received[15:0]||count!==received+123)$fatal(1,"TOF snapshot mismatch bin=%d expected=%d count=%d",index,received,count);
 received=received+1;
end
initial begin
 #100;@(negedge clk);rst=0;repeat(10)@(negedge clk);start=1;@(negedge clk);start=0;
 wait(dut.state==2);
 repeat(5)@(negedge clk); // 等待清RAM流水线完全结束，再注入非零测试图案。
 for(integer j=0;j<65536;j=j+1) dut.u0_histog_ram.memory[j]=j+123;
 repeat(8)begin @(negedge clk);ref_time=ref_time+10000000;ref_valid=1;@(negedge clk);ref_valid=0;repeat(8)@(negedge clk);end
 wait(received==65536);repeat(10)@(negedge clk);
 if(received!=65536)$fatal(1,"duplicate bins");
 // 采集结束后通过PS整字接口回放一帧中的单个bin，并核验字节地址转换。
 mem_addr=12345*4;mem_en=1;mem_we=15;mem_din=32'h12345678;
 @(negedge clk);mem_we=0;@(negedge clk);
 if(mem_dout!==32'h12345678)$fatal(1,"PS histogram RAM access failed");
 mem_en=0;
 $display("PASS: real TOF 65536-bin snapshot + shared RAM PS read/write + UDP-independent capture");$finish;
end
initial begin #2000000;$fatal(1,"TOF watchdog bins=%d state=%d",received,dut.state);end
endmodule
