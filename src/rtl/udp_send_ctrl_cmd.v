module udp_send_ctrl_cmd
(
    input                               sys_rst                    ,
    input                               gmii_tx_clk                ,
    input                               tx_req                     ,
    output             [   7:0]         tx_data                    ,
    output reg                          tx_start_en                ,
    output reg         [  15:0]         tx_byte_num                ,

    input              [  13:0]         rd_data_count              ,
    input                               fifo_prog_empty            ,
    input              [   7:0]         fifo_dout                  ,
    output                              fifo_rd_en                 ,

    input                               cmd_rst                    ,//复位
    input                               cmd_start                  ,//开始
    input                               cmd_stop                   ,//结束
    input                               cmd_state                  ,//状态查询
    input                               cmd_config                 ,//参数配置
    input                               cmd_reply                  ,//指令回复
    input                               cmd_tof_en                 ,
    input              [8*22-1:0]       sys_state                   

    );

reg                    [  31:0]         time_1ms_cnt               ;
reg                                     time_1ms_vaild             ;
reg                                     tx_req_r1                  ;
reg                                     cmd_reply_r2               ;//指令信号
reg                                     cmd_reply_r1               ;

wire                                    cmd_reply_pos = (~cmd_reply_r2)&cmd_reply_r1;
wire                                    tx_req_neg = tx_req_r1&(~tx_req);

always @(posedge gmii_tx_clk) begin
    cmd_reply_r1 <= cmd_reply;
    cmd_reply_r2 <= cmd_reply_r1;
    tx_req_r1 <= tx_req;
end

// wire pkg_start_pos = (~pkg_start_r[3])&pkg_start_r[2];
// wire pkg_stop_pos = (~pkg_stop_r[3])&pkg_stop_r[2];

// always @(posedge gmii_tx_clk) begin
//     pkg_start_r[3:0] <= {pkg_start_r[2:0],pkg_start};
//     pkg_stop_r[3:0] <= {pkg_stop_r[2:0],pkg_stop};
// end

reg                    [  31:0]         time_cnt                   ;

always@(posedge gmii_tx_clk) begin
    if(sys_rst) begin
        time_cnt <= 'd0;
    end
    else if(tx_req) begin
        time_cnt <= 'd0;
    end
    else if(time_cnt == 125_000) begin
        time_cnt <= time_cnt;
    end
    else begin
        time_cnt <= time_cnt + 1'b1;
    end

end

//UDP发送数据控制
//parameter define
    parameter                           IDLE         = 4'b0001     ;
    parameter                           START_SEND   = 4'b0010     ;
    parameter                           SEND_TIME    = 4'b0100     ;
    parameter                           CMD_REPLY    = 4'b1000     ;
reg                    [   3:0]         state                      ;

always@(posedge gmii_tx_clk)
    if(sys_rst)
        state <= IDLE;                                                     
    else 
        case(state)
            IDLE :  
                    if(cmd_reply_pos)
                        state <= CMD_REPLY;
                    else if((~fifo_prog_empty)&&(time_cnt == 125_000))                                       
                        state <= START_SEND;
                    // else if(time_1ms_vaild)
                    //     state <= START_SEND;
                    else                                        
                        state <= IDLE;
            START_SEND : 
                        state <= SEND_TIME;
            SEND_TIME :  if(tx_req_neg)
                            state <= IDLE;
                        else
                            state <= SEND_TIME;
            CMD_REPLY : if(tx_req_neg)
                            state <= IDLE;
                        else
                            state <= CMD_REPLY;
            //如果状态机跳转到编码的状态之外也回到初始状态
            default : state <= IDLE;
        endcase

//定时1ms
// always @(posedge gmii_tx_clk) 
//     if(sys_rst) begin
//         time_1ms_cnt <= 32'b0;
//         time_1ms_vaild <= 1'b0;     
//     end
//     else if(state == START_SEND) begin //启动发送后定时清空
//         time_1ms_cnt <= 32'b0;
//         time_1ms_vaild <= 1'b0;
//     end
//     else if(time_1ms_cnt == 32'd124_999)begin //计时到1ms开始启动发送程序
//         time_1ms_vaild <= 1'b1;
//         time_1ms_cnt <= time_1ms_cnt;
//     end
//     else if(rd_data_count!=0) begin //fifo不为空开始计时
//         time_1ms_cnt <= time_1ms_cnt + 1'b1;
//         time_1ms_vaild <= 1'b0;   
//     end
//     else begin
//         time_1ms_cnt <= 32'b0;
//         time_1ms_vaild <= 1'b0;
//     end

//发送使能
always @(posedge gmii_tx_clk) begin
    if(sys_rst)
        tx_start_en <= 1'b0;
    else begin
        if(state == START_SEND) 
            tx_start_en <= 1'b1;
        else if(state == CMD_REPLY)
            tx_start_en <= 1'b1;
        else
            tx_start_en <= 1'b0;
    end
end

reg                    [   7:0]         pkg_tx_xor                 ;
reg                    [   7:0]         reply_data                 ;
reg                    [   7:0]         reply_data_r1              ;
reg                    [   7:0]         tx_cnt                     ;

always @(posedge gmii_tx_clk)  reply_data_r1 <= reply_data;
assign tx_data = (state == CMD_REPLY) ? reply_data_r1 : fifo_dout;

assign fifo_rd_en = (state == CMD_REPLY) ? 1'b0 : tx_req;

//更新发送字节数
always @(posedge gmii_tx_clk) begin
    if(sys_rst)
        tx_byte_num <= 16'd0;
    else begin
        if(state == CMD_REPLY) 
            tx_byte_num <= 16'd28;
        else if(state == START_SEND)
            tx_byte_num <= 16'd1024;//{2'b0,rd_data_count};
    end
end

//指令应答和状态查询
always @(posedge gmii_tx_clk) begin
    if(sys_rst) begin
        pkg_tx_xor <= 8'h00;
        reply_data <= 8'd0;
        tx_cnt <= 8'd0;
    end
    else begin
        if(tx_req&(state==CMD_REPLY)) begin
            tx_cnt <= tx_cnt + 1'b1;
            pkg_tx_xor <= pkg_tx_xor ^ reply_data ;
        end
        else begin
            tx_cnt <= 8'd0;
            pkg_tx_xor <= 8'd0;
        end
        case(tx_cnt + tx_req) 
            8'd0 : reply_data <= 8'h55;
            8'd1 : reply_data <= 8'haa;
            8'd2 : reply_data <= {2'b0,cmd_tof_en,cmd_config,cmd_state,cmd_stop,cmd_start,cmd_rst};
            8'd3 : reply_data <= 8'd22;
            8'd4 : reply_data <= 8'd0;
            8'd5 : reply_data <= sys_state[(22*8-1)-:8]; 
            8'd6 : reply_data <= sys_state[(21*8-1)-:8]; 
            8'd7 : reply_data <= sys_state[(20*8-1)-:8]; 
            8'd8 : reply_data <= sys_state[(19*8-1)-:8]; 
            8'd9 : reply_data <= sys_state[(18*8-1)-:8];
            8'd10: reply_data <= sys_state[(17*8-1)-:8]; 
            8'd11: reply_data <= sys_state[(16*8-1)-:8];
            8'd12: reply_data <= sys_state[(15*8-1)-:8];
            8'd13: reply_data <= sys_state[(14*8-1)-:8];
            8'd14: reply_data <= sys_state[(13*8-1)-:8];
            8'd15: reply_data <= sys_state[(12*8-1)-:8]; 
            8'd16: reply_data <= sys_state[(11*8-1)-:8];
            8'd17: reply_data <= sys_state[(10*8-1)-:8];
            8'd18: reply_data <= sys_state[(9 *8-1)-:8];
            8'd19: reply_data <= sys_state[(8 *8-1)-:8];
            8'd20: reply_data <= sys_state[(7 *8-1)-:8];
            8'd21: reply_data <= sys_state[(6 *8-1)-:8];
            8'd22: reply_data <= sys_state[(5 *8-1)-:8];
            8'd23: reply_data <= sys_state[(4 *8-1)-:8];
            8'd24: reply_data <= sys_state[(3 *8-1)-:8];
            8'd25: reply_data <= sys_state[(2 *8-1)-:8];
            8'd26: reply_data <= sys_state[(1 *8-1)-:8];
            8'd27: reply_data <= pkg_tx_xor;
            default: reply_data <= 8'd0;
        endcase
    end
end

// ila_2 u2_ila (
//     .clk                               (gmii_tx_clk               ),
//     .probe0                            (tx_data                   ),
//     .probe1                            (tx_start_en               ),
//     .probe2                            (tx_byte_num               ),
//     .probe3                            (tx_req                    ),
//     .probe4                            (rd_data_count             ),
//     .probe5                            (fifo_prog_empty           ),
//     .probe6                            (fifo_dout                 ),
//     .probe7                            (fifo_rd_en                ),
//     .probe8                            (cmd_reply_pos             ),
//     .probe9                            (time_1ms_vaild            ),
//     .probe10                           (time_1ms_cnt              ) 
//     );

endmodule