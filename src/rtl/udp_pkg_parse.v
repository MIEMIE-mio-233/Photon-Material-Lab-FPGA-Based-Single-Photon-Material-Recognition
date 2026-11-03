module udp_pkg_parse(
    input                               clk                        ,//时钟信号
    input                               rst                        ,//复位信号，低电平有效
    input                               rec_en                     ,//GMII输入数据有效信号
    input              [   7:0]         rec_data                   ,//GMII输入数据
    output reg                          cmd_rst                    ,//复位
    output reg                          cmd_start                  ,//开始
    output reg                          cmd_stop                   ,//结束
    output reg                          cmd_state                  ,//状态查询
    output reg                          cmd_config                 ,//参数配置
    output reg                          cmd_tof_en                 ,//tof使能
    output reg         [  15:0]         cmd_dac1                   ,//DAC通道1电压设置
    output reg         [  15:0]         cmd_dac2                   ,//DAC通道2电压设置
    output reg                          cmd_match_mode             ,//符合计数模式
    output reg                          cmd_ext_clk                ,//外部参考时钟
    output reg         [  31:0]         cmd_trig_num               ,//tof 采集时长,触发数量
    output reg         [  15:0]         cmd_bin_num                ,//tof BIN总数
    output reg         [   7:0]         cmd_bin_width              ,//tof BIN分辨率
    output reg                          cmd_config_vaild           ,//参数有效信号
    output reg                          cmd_reply                   //指令回复
    );

localparam                              st_idle     = 8'd0         ;//初始状态
localparam                              st_pkg_head = 8'd1         ;//包头
localparam                              st_pkg_cmd  = 8'd2         ;//操作命令
localparam                              st_pkg_len  = 8'd3         ;//参数长度
localparam                              st_pkg_dac1 = 8'd4         ;//DAC通道1电压设置
localparam                              st_pkg_dac2 = 8'd5         ;//DAC通道1电压设置
localparam                              st_pkg_match= 8'd6         ;//符合计数模式
localparam                              st_pkg_clk  = 8'd7         ;//外部参考时钟
localparam                              st_pkg_trign= 8'd8         ;//DAC通道1电压设置
localparam                              st_pkg_binn = 8'd9         ;//符合计数模式
localparam                              st_pkg_binw = 8'd10        ;//外部参考时钟
localparam                              st_pkg_end  = 8'd11        ;//

reg                    [  15:0]         pkg_len                    ;//数据包长度
reg                    [   7:0]         cur_state                  ;
reg                    [   8:0]         next_state                 ;
reg                                     skip_en                    ;//控制状态跳转使能信号
reg                    [  15:0]         cnt                        ;//解析数据计数器
reg                    [   7:0]         pkg_xor                    ;//数据包校验
//*****************************************************
//**                    main code
//*****************************************************

//(三段式状态机)同步时序描述状态转移
always @(posedge clk) begin
    if(rst)
        cur_state <= st_idle;  
    else
        cur_state <= next_state;
end

//组合逻辑判断状态转移条件
always @(*) begin
    next_state = st_idle;
    case(cur_state)
        st_idle : begin                                     //等待指令
            if(skip_en) 
                next_state = st_pkg_head;
            else
                next_state = st_idle;    
        end
        st_pkg_head : begin                                 //接收包头
            if(skip_en) 
                next_state = st_pkg_cmd;
            else if(!rec_en)
                next_state = st_idle;    
            else
                next_state = st_pkg_head;    
        end
        st_pkg_cmd : begin                                 //接收操作命令
            if(skip_en) 
                next_state = st_pkg_len;
            else if(!rec_en)
                next_state = st_idle;    
            else
                next_state = st_pkg_cmd;    
        end
        st_pkg_len : begin                                 //接收参数长度
            if(cmd_config == 1'b0)
                next_state = st_pkg_end;
            else if(skip_en)
                next_state = st_pkg_dac1;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_len;    
        end                
        st_pkg_dac1 : begin                                  //接收DAC1参数
            if(skip_en)
                next_state = st_pkg_dac2;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_dac1;    
        end   
        st_pkg_dac2 : begin                                  //接收DAC2参数
            if(skip_en)
                next_state = st_pkg_match;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_dac2;    
        end
        st_pkg_match : begin                                  //接收符合计数参数
            if(skip_en)
                next_state = st_pkg_clk;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_match;    
        end 
        st_pkg_clk : begin                                  //接收外部时钟参数
            if(skip_en)
                next_state = st_pkg_trign;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_clk;    
        end  
        st_pkg_trign : begin                                  //接收DAC2参数
            if(skip_en)
                next_state = st_pkg_binn;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_trign;    
        end
        st_pkg_binn : begin                                  //接收符合计数参数
            if(skip_en)
                next_state = st_pkg_binw;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_binn;    
        end 
        st_pkg_binw : begin                                  //接收外部时钟参数
            if(skip_en)
                next_state = st_pkg_end;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_binw;    
        end
        st_pkg_end : begin                                   //接收结束
            if(skip_en)
                next_state = st_idle;
            else if(!rec_en)
                next_state = st_idle;  
            else
                next_state = st_pkg_end;        
        end
        default : next_state = st_idle;
    endcase                                          
end    

//时序电路描述状态输出,解析以太网数据
always @(posedge clk ) begin
    if(rst) begin
        skip_en <= 1'b0;
        cnt <= 16'd0;
        pkg_len <= 16'd0;
        pkg_xor <= 8'd0;

        cmd_rst <= 1'b0;
        cmd_start <= 1'b0;
        cmd_stop <= 1'b0;
        cmd_state <= 1'b0;
        cmd_config <= 1'b0;
        cmd_tof_en <= 1'b0;
        cmd_dac1  <= 'd0;   
        cmd_dac2  <= 'd0;
        cmd_match_mode <= 1'b0;
        cmd_ext_clk   <= 1'b0;
        cmd_trig_num  <= 'd0;
        cmd_bin_num   <= 'd0;
        cmd_bin_width <= 'd0;
        cmd_reply <= 1'b0;
    end
    else begin
        skip_en <= 1'b0;
        case(next_state)
            st_idle : begin
                cnt <= 16'd0;
                cmd_reply <= 1'b0;
                cmd_tof_en <= 1'b0;
                if(rec_en) begin
                    if(rec_data == 8'h55)
                        skip_en <= 1'b1;
                end
            end
            st_pkg_head : begin
                if(rec_en) begin
                    if(rec_data == 8'haa)
                        skip_en <= 1'b1;
                end
            end
            st_pkg_cmd : begin
                if(rec_en) begin                        
                    skip_en   <= 1'b1;
                    cmd_rst   <= rec_data[0];//复位
                    cmd_start <= rec_data[1];//开始
                    cmd_stop  <= rec_data[2];//停止
                    cmd_state <= rec_data[3];//状态查询
                    cmd_config<= rec_data[4];//参数配置
                    cmd_tof_en<= rec_data[5];//参数配置
                    cmd_reply <= 1'b1;
                end  
            end
            st_pkg_len : begin
                if(rec_en) begin
                    cnt <= cnt + 1'b1;
                    pkg_len[15:0] <= {rec_data[7:0],pkg_len[15:8]}; //小端转大端
                    if(cnt == 16'd2 - 1) begin
                        skip_en <= 1'b1;
                        cnt <= 16'd0;
                    end
                end                 
            end   
            st_pkg_dac1 : begin
                if(rec_en) begin
                    cnt <= cnt + 1'b1;
                    cmd_dac1[15:0] <= {rec_data[7:0],cmd_dac1[15:8]}; //小端转大端
                    if(cnt == 16'd2 - 1) begin
                        skip_en <= 1'b1;
                        cnt <= 16'd0;
                    end
                end   
            end
            st_pkg_dac2 : begin
                if(rec_en) begin
                    cnt <= cnt + 1'b1;
                    cmd_dac2[15:0] <= {rec_data[7:0],cmd_dac2[15:8]}; //小端转大端
                    if(cnt == 16'd2 - 1) begin
                        skip_en <= 1'b1;
                        cnt <= 16'd0;
                    end
                end   
            end
            st_pkg_match : begin
                if(rec_en) begin                         
                    skip_en <= 1'b1;
                    cmd_match_mode <= rec_data[0];
                end  
            end
            st_pkg_clk : begin
                if(rec_en) begin                         
                    skip_en <= 1'b1; 
                    cmd_ext_clk <= rec_data[0];
                end  
            end
            st_pkg_trign : begin
                if(rec_en) begin
                    cnt <= cnt + 1'b1;
                    cmd_trig_num[31:0] <= {rec_data[7:0],cmd_trig_num[31:8]}; //小端转大端
                    if(cnt == 16'd4 - 1) begin
                        skip_en <= 1'b1;
                        cnt <= 16'd0;
                    end
                end   
            end
            st_pkg_binn : begin
                if(rec_en) begin
                    cnt <= cnt + 1'b1;
                    cmd_bin_num[15:0] <= {rec_data[7:0],cmd_bin_num[15:8]}; //小端转大端
                    if(cnt == 16'd2 - 1) begin
                        skip_en <= 1'b1;
                        cnt <= 16'd0;
                    end
                end   
            end
            st_pkg_binw : begin
                if(rec_en) begin
                    skip_en <= 1'b1; 
                    cmd_bin_width[7:0] <= rec_data[7:0]; //小端转大端
                end   
            end
            // st_pkg_data : begin                  
            //     if(rec_en) begin
            //         cnt <= cnt + 1'b1;
            //         pkg_data <= rec_data;
            //         pkg_data_vaild <= 1'b1;
            //         if(cnt == pkg_len - 1) begin
            //             skip_en <= 1'b1;
            //             cnt <= 16'd0;
            //         end
            //     end 
            // end    
            st_pkg_end : begin                               
                if(rec_en) begin
                    pkg_xor <= rec_data;
                    skip_en <= 1'b1;
                end 
            end    
            default : ;
        endcase                                                        
    end
end

always @(posedge clk) 
    if(rst) 
        cmd_config_vaild <= 1'b0;
    else if((~rec_en)&cmd_config)
        cmd_config_vaild <= 1'b1;
    else
        cmd_config_vaild <= 1'b0;


// ila_1 u1_ila (
//     .clk                               (clk                       ),
//     .probe0                            (cur_state                 ),
//     .probe1                            (next_state                ),
//     .probe2                            (skip_en                   ),
//     .probe3                            (cnt                       ),
//     .probe4                            (cmd_rst                   ),
//     .probe5                            (cmd_start                 ),
//     .probe6                            (cmd_stop                  ),
//     .probe7                            (cmd_state                 ),
//     .probe8                            (cmd_ext_clk               ),
//     .probe9                            (cmd_match_mode             ),
//     .probe10                           (cmd_config                ),
//     .probe11                           (cmd_dac1                  ),
//     .probe12                           (cmd_dac2                  ),
//     .probe13                           (rec_en                    ),
//     .probe14                           (rec_data                  ),
//     .probe15                           (cmd_dac_vaild             )
// );



endmodule