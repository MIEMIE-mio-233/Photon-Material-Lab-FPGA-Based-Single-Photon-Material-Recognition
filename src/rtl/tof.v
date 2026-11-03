`timescale 1ns / 1ps

module tof
(
    input ps_local_mode, // PS模式直接导出快照，不等待PL网口取走FIFO
    input ps_mem_en, input [3:0] ps_mem_we, input [17:0] ps_mem_addr,
    input [31:0] ps_mem_din, output [31:0] ps_mem_dout,
    output snapshot_valid, output [15:0] snapshot_index, output [31:0] snapshot_count,
    input                               sys_rst                    ,
    input                               sys_clk                    ,
    input                               tof_en                     ,
    input              [  31:0]         trig_num                   ,//采集时长,触发数量
    input              [  15:0]         bin_num                    ,//BIN总数
    input              [  7 :0]         bin_width                  ,//BIN分辨率
    input              [  63:0]         timestamp1                 ,
    input                               timestamp1_vaild           ,
    input              [  63:0]         timestamp2                 ,
    input                               timestamp2_vaild           ,
    input                               rd_fifo_clk                ,
    input                               fifo_rd_en                 ,
    output             [   7:0]         fifo_dout                  ,
    output             [  13:0]         rd_data_count              ,
    output                              fifo_prog_empty            

);

reg                    [  63:0]         timestamp1_r1              ;
reg                                     timestamp1_vaild_r1        ;
reg                    [  63:0]         timestamp2_r1              ;
reg                                     timestamp2_vaild_r1        ;
reg                    [  63:0]         timestamp1_r2              ;
reg                    [  63:0]         timestamp2_r2              ;
reg                    [  63:0]         timestamp_diff             ;
reg                                     timestamp_diff_vaild       ;

//缓存前后两次时间戳数据
always@(posedge sys_clk) begin
    if(sys_rst) begin
        timestamp1_vaild_r1 <= 'd0;
        timestamp1_r1 <= 'd0;
        timestamp1_r2 <= 'd0;
    end
    else if(timestamp1_vaild) begin 
        timestamp1_vaild_r1 <= timestamp1_vaild;
        timestamp1_r1 <= timestamp1;
        timestamp1_r2 <= timestamp1_r1;
    end
    else begin
        timestamp1_vaild_r1 <= 'd0;
    end
end   
//缓存前后两次时间戳数据
always@(posedge sys_clk) begin
    if(sys_rst) begin
        timestamp2_vaild_r1 <= 'd0;
        timestamp2_r1 <= 'd0;
        timestamp2_r2 <= 'd0;
    end
    else if(timestamp2_vaild) begin 
        timestamp2_vaild_r1 <= timestamp2_vaild;
        timestamp2_r1 <= timestamp2;
        timestamp2_r2 <= timestamp2_r1;
    end
    else begin
        timestamp2_vaild_r1 <= 'd0;
    end
end   

wire                                    ram_wd_en                  ;
wire                                    ram_rd_en                  ;
wire                   [  31:0]         ram_wdata                  ;
wire                   [  31:0]         ram_rdata                  ;
wire                   [  15:0]         ram_waddr                  ;
wire                   [  15:0]         ram_raddr                  ;

reg                    [  31:0]         ram_wdata_r                ;
reg                                     ram_wd_en_r                ;
reg                    [  15:0]         ram_waddr_r                ;
reg                                     ram_rd_en_r                ;
reg                    [  31:0]         ram_rdata_r                ;
reg                    [  15:0]         ram_raddr_r                ;
reg                    [  15:0]         ram_raddr_r2               ;// 读地址延迟 2 拍
reg                                     ram_rd_en_r3               ;// 写回使能延迟 3 拍
reg                    [  15:0]         ram_raddr_r3               ;// 写回地址延迟 3 拍
reg                                     ram_rd_en_r2               ;

reg                    [  15:0]         wd_cnt                     ;
reg                    [  15:0]         rd_cnt                     ;
reg                    [  31:0]         trig_cnt                   ;

wire                                    fifo_prog_full             ;

//parameter define
    parameter                           IDLE        = 3'd0         ;//空闲
    parameter                           RST         = 3'd1         ;//复位 清空RAM内存数据
    parameter                           WAIT        = 3'd2         ;//等待一个时钟周期
    parameter                           START       = 3'd3         ;//开始统计码密度分布，边读边写RAM
    parameter                           DELAY       = 3'd4         ;//延时，等待最后一个数据写入完成
    parameter                           READ        = 3'd5         ;//读取RAM中存储的码密度数据
    parameter                           STOP        = 3'd6         ;//码密度校准结束

reg                    [   2:0]         state                      ;

reg                                     tof_en_r1                  ;// tof_en 同步寄存
always@(posedge sys_clk) begin
    if(sys_rst)
        tof_en_r1 <= 1'b0                                ;// 复位清零(消除仿真 X 初值)
    else
        tof_en_r1 <= tof_en                              ;
end
wire     tof_en_pos = tof_en&(~tof_en_r1);

reg                    [  2:0]         delay_cnt                   ;
//延时计数
always@(posedge sys_clk) begin
    if(sys_rst) begin
        delay_cnt <= 'd0;
    end
    else if(state == DELAY) begin
        delay_cnt <= delay_cnt + 1'b1;
    end
    else if(state == RST) begin
        delay_cnt <= 'd0;
    end
end  

always@(posedge sys_clk)
    if(sys_rst)
        state <= IDLE;                                                     
    else 
        case(state)
            IDLE :  if(tof_en_pos)                 //开始统计                      
                        state <= RST;
                    else                                        
                        state <= IDLE;
            RST :   if(ram_waddr_r == bin_num)    //复位，所有地址数据清零  上位机下发bin_num-1                                  
                        state <= WAIT;
                    else                                        
                        state <= RST;
            WAIT :  if(tof_en_pos)                 //新采集请求: 重新清零启动(修复二次采集 trig_cnt 残留)
                        state <= RST;
                    else if(timestamp2_vaild_r1 == 1'b1)//等待触发信号到来，开始计数
                        state <= START; 
                    else
                        state <= WAIT;
            START:  if(trig_cnt == trig_num)       //直方图统计，边读边写                      
                        state <= DELAY;
                    else                                        
                        state <= START;
            DELAY:  if(delay_cnt == 3'd3)          //延时，等待最后一个数据写入完成
                        state <= READ;
                    else                                        
                        state <= DELAY;
            READ :  if(rd_cnt == bin_num)          //读数据 上位机下发bin_num-1
                        state <= STOP;
                    else                                        
                        state <= READ;
            STOP :  state <= IDLE; 
            //如果状态机跳转到编码的状态之外也回到初始状态
            default : state <= IDLE;
        endcase

//触发计数
always@(posedge sys_clk) begin
    if(sys_rst) begin
        trig_cnt <= 'd0;
    end
    else if((timestamp2_vaild_r1 == 1'b1)&&(state == START)) begin
        trig_cnt <= trig_cnt + 1'b1;
    end
    else if(tof_en_pos) begin
        trig_cnt <= 'd0;                            //新采集请求: 触发计数清零
    end
    else if(state == RST) begin
        trig_cnt <= 'd0;
    end
end  

//计算时间差值，通道一探测器，通道二触发通道
always@(posedge sys_clk) begin
    if(sys_rst) begin
        timestamp_diff <= 'd0;
        timestamp_diff_vaild <= 'd0;
    end
    else if(timestamp2_r1 == 0) begin
        timestamp_diff_vaild <= 1'b0;
    end
    else if((state == START)&&(timestamp1_vaild_r1==1'b1)) begin 
        if(timestamp1_r1 >= timestamp2_r1)
            timestamp_diff <= timestamp1_r1 - timestamp2_r1;    //当前周期数据
        else
            timestamp_diff <= timestamp1_r1 - timestamp2_r2;    //上一个时钟数据
        timestamp_diff_vaild <= 1'b1;
    end
    else begin
        timestamp_diff_vaild <= 1'b0;
    end
end   

//写数据计数
always@(posedge sys_clk) 
begin
    if(sys_rst) begin
        wd_cnt <= 'd0;
    end
    else if(ram_wd_en_r)begin
        wd_cnt <= wd_cnt + 1'b1;
    end
    else if((state == WAIT)) begin
        wd_cnt <= 'd0;
    end
    else if((state == STOP)) begin
        wd_cnt <= 'd0;
    end
end

//写RAM控制
always@(posedge sys_clk) 
begin
    if(tof_en_pos && state == IDLE) begin                    // 仅 IDLE 态响应启动, 防 RST 中途被打断致 waddr 跳变卡死
        ram_wd_en_r <= 1'd0;
        ram_waddr_r <= 10'd0;
    end
    else if(state == RST) begin //清空地址数据
        ram_wd_en_r <= 1'b1;
        ram_waddr_r <= wd_cnt;
    end
    // else if((state == START)&&(ram_rd_en_r == 1'b1)) begin //先读后写
    //     ram_wd_en_r <= 1'b1;
    //     ram_waddr_r <= ram_raddr_r;
    // end
    // else if((state == DELAY)&&(ram_rd_en_r == 1'b1)) begin //写最后一个数据
    //     ram_wd_en_r <= 1'b1;
    //     ram_waddr_r <= ram_raddr_r;
    // end
    else if((state == START)&&(ram_rd_en_r3 == 1'b1)) begin //先读后写(写回随数据流水第 3 拍)
        ram_wd_en_r <= 1'b1;
        ram_waddr_r <= ram_raddr_r3;
    end
    else if((state == DELAY)&&(ram_rd_en_r3 == 1'b1)) begin //写最后一个数据
        ram_wd_en_r <= 1'b1;
        ram_waddr_r <= ram_raddr_r3;
    end
    else if(state == STOP) begin //清零
        ram_waddr_r <= 'd0;
        ram_wd_en_r <= 1'd0;
    end
    else begin
        ram_wd_en_r <= 1'd0;
    end
end

//读数据计数
always@(posedge sys_clk) 
begin
    if(sys_rst) begin
        rd_cnt <= 'd0;
    end
    else if(state == RST)begin
        rd_cnt <= 'd0;
    end
    else if((state == READ)&&((!fifo_prog_full)||ps_local_mode)) begin
        rd_cnt <= rd_cnt + 1'b1;
    end
end

//读RAM控制
always@(posedge sys_clk) 
begin
    if(sys_rst) begin
        ram_rd_en_r <= 1'd0;
        ram_raddr_r <= 10'd0;
    end
    else if((state == READ)&&((!fifo_prog_full)||ps_local_mode)) begin   //连续从RAM中读数据写入FIFO，fifo_prog_full当fifo大于2045时候置高，低于1024时拉低。
        ram_rd_en_r <= 1'b1;
        ram_raddr_r <= rd_cnt;
    end
    else if(state == START)begin    //直方图先读后写数据
        ram_rd_en_r <= timestamp_diff_vaild;
        if((timestamp_diff[31:0]>>bin_width) > 16'hFFFF)
            ram_raddr_r <= 16'hFFFF;
        else 
            ram_raddr_r <= (timestamp_diff[31:0]>>bin_width);   //bin分辨率，地址
    end
    else begin
        ram_rd_en_r <= 1'd0;
    end
end

always@(posedge sys_clk) begin
    if(sys_rst) begin
        ram_rd_en_r2 <= 'd0;
        ram_raddr_r2 <= 'd0;
        ram_rdata_r  <= 'd0;
    end
    else begin
        ram_rd_en_r2 <= ram_rd_en_r;
        ram_raddr_r2 <= ram_raddr_r;
        ram_rdata_r  <= ram_rdata;
        ram_rd_en_r3 <= ram_rd_en_r2;               //写回流水第 3 拍(与 wdata_r 寄存副本对齐)
        ram_raddr_r3 <= ram_raddr_r2;
    end
end

always@(posedge sys_clk) begin
    if(sys_rst) begin
        ram_wdata_r <= 'd0;
    end
    else if(state == RST) begin
        ram_wdata_r <= 'd0;
    end
    else begin
        if(ram_rdata_r == 32'hFFFF_FFFF)               //改用寄存副本: BRAM CO+32bit 加法在 300MHz 下违例(WNS-0.2 根因)
            ram_wdata_r <= 32'hFFFF_FFFF;
        else
            ram_wdata_r <= ram_rdata_r + 1'b1;
    end
end

assign ram_rd_en = ram_rd_en_r;
assign ram_raddr = ram_raddr_r;
assign ram_wd_en = ram_wd_en_r;
assign ram_waddr = ram_waddr_r;
assign ram_wdata = ram_wdata_r;//(state == RST) ? 0 : ((ram_rdata == 32'hFFFF_FFFF) ? 32'hFFFF_FFFF : (ram_rdata + 1'b1)); //钳位

// 复用原有65536x32统计RAM，避免复制快照耗尽BRAM。
// 采集/出帧期间由TDC独占；完整帧完成后停在IDLE，PS与HLS经AXI读取。
// PS访问只使用对齐的32位整字操作，原RAM未启用逐字节写。
wire ps_memory_access = ps_local_mode && state==IDLE && !tof_en_pos;
assign ps_mem_dout = ram_rdata;
histog_ram u0_histog_ram (
    .clka                              (sys_clk                   ),// input wire clka
    .ena                               (ps_memory_access ? (ps_mem_en & (|ps_mem_we)) : ram_wd_en),// input wire ena
    .wea                               (1'b1                      ),// input wire [0 : 0] wea
    .addra                             (ps_memory_access ? ps_mem_addr[17:2] : ram_waddr),// input wire [9 : 0] addra
    .dina                              (ps_memory_access ? ps_mem_din : ram_wdata),// input wire [15 : 0] dina
    .clkb                              (sys_clk                   ),// input wire clkb
    .rstb                              (sys_rst|tof_en_pos        ),// input wire rstb
    .enb                               (ps_memory_access ? ps_mem_en : ram_rd_en),// input wire enb
    .addrb                             (ps_memory_access ? ps_mem_addr[17:2] : ram_raddr),// input wire [9 : 0] addrb
    .doutb                             (ram_rdata                 ),// output wire [15 : 0] doutb
    .rsta_busy                         (                          ),// output wire rsta_busy
    .rstb_busy                         (                          ) // output wire rstb_busy
);

wire                   [  63:0]         fifo_din                   ;
reg                    [  63:0]         fifo_din_r                 ;
wire                                    fifo_wr_en                 ;
reg                                     fifo_wr_en_r               ;
reg                                     fifo_wr_en_r2              ;
//写FIFO控制
always@(posedge sys_clk) begin
    if(sys_rst) begin
        fifo_wr_en_r <= 'd0;
    end
    else if((state == READ)||(state == STOP)) begin
        fifo_wr_en_r <= ram_rd_en;
    end
    else begin
        fifo_wr_en_r <= 'd0;
    end
end

always@(posedge sys_clk) fifo_wr_en_r2 <= fifo_wr_en_r;

reg                    [   15:0]         fifo_wr_cnt                ;

//写FIFO计数
always@(posedge sys_clk) 
begin
    if(sys_rst) begin
        fifo_wr_cnt <= 'd0;
    end
    else if(tof_en_pos) begin
        fifo_wr_cnt <= 'd0;
    end
    else if(fifo_wr_en_r) begin
        fifo_wr_cnt <= fifo_wr_cnt + 1'b1;
    end
end

always@(posedge sys_clk) fifo_din_r <= {16'hFFFF,fifo_wr_cnt[15:0],ram_rdata[31:0]};//加序号拼接

assign fifo_wr_en = fifo_wr_en_r2;
assign fifo_din = fifo_din_r;
// 复用已对齐的出帧数据：一个bin一次有效，不改变原统计逻辑。
assign snapshot_valid = fifo_wr_en;
assign snapshot_index = fifo_din_r[47:32];
assign snapshot_count = fifo_din_r[31:0]; 

wire                                    fifo_full                  ;
wire                                    fifo_empty                 ;
wire                                    fifo_rst                   ;

reg                    [   7:0]         tof_en_pos_d               ;
always@(posedge sys_clk) begin
    if(sys_rst)
        tof_en_pos_d <= 8'd0                             ;// 复位清零(消除仿真 X 初值)
    else
        tof_en_pos_d <= {tof_en_pos_d[6:0],tof_en_pos}   ;
end

assign fifo_rst = |tof_en_pos_d[7:0];   //扩展8个周期时长
//用同步复位，需要注意的是官方文档中建议复位信号至少要保持三个时钟周期（以慢时钟为准）的有效，
//且在复位后至少要经过三十个时钟周期（以慢时钟为准）后，才能对 FIFO 进行写数据操作。
tof_fifo tof_fifo (
    .rst                               (sys_rst|fifo_rst          ),// input wire rst
    .wr_clk                            (sys_clk                   ),// input wire wr_clk
    .rd_clk                            (rd_fifo_clk               ),// input wire rd_clk
    .din                               (fifo_din                  ),// input wire [31 : 0] din
    .wr_en                             (fifo_wr_en & ~ps_local_mode),// input wire wr_en
    .rd_en                             (fifo_rd_en                ),// input wire rd_en
    .dout                              (fifo_dout                 ),// output wire [7 : 0] dout
    .full                              (fifo_full                 ),// output wire full
    .prog_full                         (fifo_prog_full            ),// output wire almost_full
    .empty                             (fifo_empty                ),// output wire empty
    .rd_data_count                     (rd_data_count             ),// output wire [12 : 0] rd_data_count
    .prog_empty                        (fifo_prog_empty           ) // output wire prog_empty
);

reg                                     fifo_rd_en_r1,fifo_rd_en_r2;
wire                                    fifo_rd_en_neg             ;
always@(posedge sys_clk) fifo_rd_en_r1 <= fifo_rd_en;
always@(posedge sys_clk) fifo_rd_en_r2 <= fifo_rd_en_r1;
assign fifo_rd_en_neg = (~fifo_rd_en_r1)&fifo_rd_en_r2;

// reg                    [   15:0]         fifo_rd_cnt                ;

// always@(posedge sys_clk) 
// begin
//     if(sys_rst) begin
//         fifo_rd_cnt <= 'd0;
//     end
//     else if(tof_en_pos) begin
//         fifo_rd_cnt <= 'd0;
//     end
//     else if(fifo_rd_en_neg) begin
//         fifo_rd_cnt <= fifo_rd_cnt + 1'b1;
//     end
// end

reg                    [   15:0]         fifo_rd_cnt2                ;

always@(posedge rd_fifo_clk) 
begin
    if(sys_rst) begin
        fifo_rd_cnt2 <= 'd0;
    end
    else if(tof_en_pos) begin
        fifo_rd_cnt2 <= 'd0;
    end
    else if(fifo_rd_en) begin
        fifo_rd_cnt2 <= fifo_rd_cnt2 + 1'b1;
    end
end



// ila_tof2 ila_tof2 (
//     .clk                               (rd_fifo_clk               ),
//     .probe0                            (rd_data_count             ),
//     .probe1                            (fifo_prog_empty           ),
//     .probe2                            (fifo_rd_en                ),
//     .probe3                            (fifo_rd_cnt2              ),
//     .probe4                            (fifo_empty                ) 
// );

//ila_tof ila_tof (
//    .clk                               (sys_clk                   ),
//    .probe0                            (timestamp1_r1             ), 
//    .probe1                            (timestamp2_r1             ),
//    .probe2                            (timestamp2_r2             ), 
//    .probe3                            (timestamp_diff[31:0]      ),
//    .probe4                            (timestamp1_vaild_r1       ),
//    .probe5                            (timestamp_diff_vaild      ), 
//    .probe6                            (timestamp2_vaild_r1       ),
//    .probe7                            (trig_cnt                  ), 
//    .probe8                            (tof_en_pos                ),
//    .probe9                            (tof_en                    ),
//    .probe10                           (state                     ),
//    .probe11                           (rd_cnt                    ), 
//    .probe12                           (wd_cnt                    ),
//    .probe13                           (ram_raddr_r               ), 
//    .probe14                           (ram_waddr_r               ),
//    .probe15                           (ram_rd_en_r               ),
//    .probe16                           (ram_wd_en_r               ), 
//    .probe17                           (ps_memory_access ? ps_mem_din : ram_wdata),
//    .probe18                           (ram_rdata                 ),
//    .probe19                           (fifo_wr_en                ),
//    .probe20                           (fifo_prog_full            ),
//    .probe21                           (fifo_wr_cnt               ),
//    .probe22                           (trig_num                  ),
//    .probe23                           (bin_num                   ),
//    .probe24                           (bin_width                 ),
//    .probe25                           (ram_rd_en_r2              ),
//    .probe26                           (ram_raddr_r2              ),
//    .probe27                           (ram_rdata_r               ),
//    .probe28                           (fifo_fulll                )
//);


endmodule