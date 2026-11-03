`timescale 1ns/1ps
module tb_ps_capture;
    reg s_axi_aclk=0, tdc_clk=0, dac_clk=0;
    always #4 dac_clk=~dac_clk;
    always #5 s_axi_aclk=~s_axi_aclk;
    always #1.667 tdc_clk=~tdc_clk;
    reg s_axi_aresetn=0, tdc_rst=1, dac_rst=1, calibrated=1;
    reg [7:0] s_axi_awaddr=0,s_axi_araddr=0;
    reg s_axi_awvalid=0,s_axi_wvalid=0,s_axi_arvalid=0;
    reg [31:0] s_axi_wdata=0;
    reg [3:0] s_axi_wstrb=15;
    wire s_axi_awready,s_axi_wready,s_axi_arready,s_axi_bvalid,s_axi_rvalid;
    wire [1:0] s_axi_bresp,s_axi_rresp;
    reg s_axi_bready=1,s_axi_rready=1;
    wire [31:0] s_axi_rdata;
    wire ps_mode,ps_meas_en,ps_start,ps_abort,mem_clk,mem_rst,mem_en;
    wire ps_laser_trigger,ps_receiver_gate,ps_reference_internal;
    wire threshold_din, threshold_sclk, threshold_cs_n;
    reg [15:0] spi_shift=0;
    reg [15:0] spi_words[0:31];
    integer spi_bits=0, spi_count=0;
    always @(negedge threshold_cs_n) spi_bits=0;
    always @(negedge threshold_sclk) if (!threshold_cs_n) begin
        spi_shift={spi_shift[14:0],threshold_din};
        if (spi_bits==15) begin spi_words[spi_count]=spi_shift; spi_count=spi_count+1; end
        spi_bits=spi_bits+1;
    end
    wire [9:0] ps_dac1_low,ps_dac1_high,ps_dac2_low,ps_dac2_high;
    wire [31:0] ps_trig_num,mem_addr,mem_din;
    wire [15:0] ps_bin_num;
    wire [7:0] ps_bin_width;
    wire [3:0] mem_we;
    reg hist_valid=0;
    reg [15:0] hist_index=0;
    reg [31:0] hist_count=0;
    tdc_ps_bridge dut(.*);
    integer writes=0;
    always @(posedge tdc_clk) if(mem_en) begin
        if(mem_addr !== writes*4 || mem_din !== writes+123 || mem_we!==15)
            $fatal(1,"snapshot address/data mismatch %d",writes);
        writes=writes+1;
    end
    task write_reg(input [7:0] addr,input [31:0] value);
        @(negedge s_axi_aclk); s_axi_awaddr=addr;s_axi_awvalid=1;
        do @(posedge s_axi_aclk); while(!s_axi_awready);
        @(negedge s_axi_aclk);s_axi_awvalid=0;
        repeat(3) @(negedge s_axi_aclk); // AW先到，W延后三拍。
        s_axi_wdata=value;s_axi_wvalid=1;
        do @(posedge s_axi_aclk); while(!s_axi_wready);
        @(negedge s_axi_aclk);s_axi_wvalid=0;
        wait(s_axi_bvalid); @(negedge s_axi_aclk);
    endtask
    task read_reg(input [7:0] addr,output [31:0] value);
        @(negedge s_axi_aclk);s_axi_araddr=addr;s_axi_arvalid=1;
        do @(posedge s_axi_aclk);while(!s_axi_arready);
        @(negedge s_axi_aclk);s_axi_arvalid=0;
        wait(s_axi_rvalid);value=s_axi_rdata;@(negedge s_axi_aclk);
    endtask
    integer i,laser_high,gate_high,last_laser_rise;reg[31:0] value;
    reg previous_laser,previous_gate;
    initial begin
        #100;s_axi_aresetn=1;tdc_rst=0;dac_rst=0;repeat(10)@(posedge s_axi_aclk);
        read_reg(0,value);if(value!==32'h54444331)$fatal(1,"bad ID");
        read_reg(4,value);if(value!==5)$fatal(1,"bad version");
        // 版本4：阈值上电默认300mV，两路完整发送后才可采集/开启输出。
        read_reg('hac,value);while(!value[1] || value[0])read_reg('hac,value);
        read_reg('hb0,value);if(value!==300)$fatal(1,"threshold A default");
        read_reg('hb4,value);if(value!==300)$fatal(1,"threshold B default");
        if(spi_count!=2 || spi_words[0]!==16'hc496 || spi_words[1]!==16'h4496)
            $fatal(1,"default SPI words %d %h %h",spi_count,spi_words[0],spi_words[1]);
        write_reg('ha0,150);write_reg('ha4,400);write_reg('ha8,1);
        read_reg('hb8,value);if(value!==0)$fatal(1,"threshold ACK before SPI completes");
        read_reg('hac,value);while(value[0])read_reg('hac,value);
        read_reg('hb8,value);if(value!==1)$fatal(1,"threshold update sequence");
        read_reg('hb0,value);if(value!==150)$fatal(1,"threshold A update");
        read_reg('hb4,value);if(value!==400)$fatal(1,"threshold B update");
        if(spi_count!=6 || spi_words[2]!==16'hc44b || spi_words[3]!==16'h4496 ||
           spi_words[4]!==16'hc44b || spi_words[5]!==16'h44c8)$fatal(1,"threshold SPI ordering/codes");
        write_reg('ha0,1002);write_reg('ha8,1);
        read_reg('hac,value);if(!value[2])$fatal(1,"out-of-range threshold accepted");
        read_reg('hb0,value);if(value!==150)$fatal(1,"invalid request changed threshold");
        write_reg('ha0,0);write_reg('ha4,1000);write_reg('ha8,1);
        read_reg('hac,value);while(value[0])read_reg('hac,value);
        read_reg('hbc,value);if(value!==32'h05f40400)$fatal(1,"0V and 1V conversion");
        write_reg('ha0,300);write_reg('ha4,300);write_reg('ha8,1);
        read_reg('hac,value);while(value[0])read_reg('hac,value);
        // 原有波形DAC、参考源和快照功能继续回归。

        read_reg('h88,value);if(value!==125000000)$fatal(1,"DAC clock register");
        read_reg('h7c,value);if(value!==2)$fatal(1,"reference default and DAC ready");
        if(ps_dac1_low!==512 || ps_dac1_high!==102 || ps_dac2_low!==512 || ps_dac2_high!==102)
            $fatal(1,"DAC defaults");
        write_reg('h78,1);repeat(12)@(posedge s_axi_aclk);
        read_reg('h7c,value);if(value!==3 || !ps_reference_internal)$fatal(1,"internal reference CDC");
        write_reg('h80,32'h00640201);repeat(12)@(posedge s_axi_aclk);
        read_reg('h90,value);if(value!==32'h00640201 || ps_dac1_low!==513 || ps_dac1_high!==100)
            $fatal(1,"DAC code CDC/readback");
        // 输出默认关闭；无需TDC校准即可设置并持续输出。
        calibrated=0;
        if(ps_laser_trigger || ps_receiver_gate)$fatal(1,"outputs must default OFF");
        write_reg('h48,30);write_reg('h4c,2);write_reg('h50,10);
        write_reg('h54,29);write_reg('h58,8);write_reg('h44,1); // v5跨周期探测窗口
        read_reg('h74,value);while(value==0)read_reg('h74,value);
        read_reg('h60,value);if(value!==30)$fatal(1,"output config CDC");
        write_reg('h40,1);
        write_reg('ha0,600);write_reg('ha8,1);
        read_reg('hb0,value);if(value!==300)$fatal(1,"threshold changed while outputs ON");
        write_reg('h78,0);write_reg('h80,0); // 运行中禁止改源及码值。
        read_reg('h78,value);if(value!==1)$fatal(1,"source changed while ON");
        read_reg('h80,value);if(value!==32'h00640201)$fatal(1,"levels changed while ON");
        repeat(20)@(negedge dac_clk);
        laser_high=0;gate_high=0;
        // 任意相位观察三个完整周期，每周期应分别有10/8拍高电平。
        repeat(90)begin
            @(negedge dac_clk);laser_high+=ps_laser_trigger;gate_high+=ps_receiver_gate;
        end
        if(laser_high!=30 || gate_high!=24)$fatal(1,"wrong pulse widths %d %d",laser_high,gate_high);
        // 非法参数提交返回错误，保留已生效的周期和脉宽。
        write_reg('h50,30);write_reg('h44,1);
        read_reg('h74,value);while(value<2)read_reg('h74,value);
        read_reg('h5c,value);if(!value[2])$fatal(1,"invalid config accepted");
        read_reg('h68,value);if(value!==10)$fatal(1,"invalid config changed outputs");
        write_reg('h50,10);write_reg('h44,1);
        read_reg('h74,value);while(value<3)read_reg('h74,value);
        // 持续输出时修改整组参数，ACK后观察新周期和新脉宽。
        write_reg('h48,36);write_reg('h4c,3);write_reg('h50,6);
        write_reg('h54,18);write_reg('h58,9);write_reg('h44,1);
        read_reg('h74,value);while(value<4)read_reg('h74,value);
        read_reg('h60,value);if(value!==36)$fatal(1,"running config not committed");
        laser_high=0;gate_high=0;repeat(20)@(negedge dac_clk);
        previous_laser=ps_laser_trigger;previous_gate=ps_receiver_gate;last_laser_rise=-1;
        for(i=0;i<108;i=i+1)begin
            @(negedge dac_clk);laser_high+=ps_laser_trigger;gate_high+=ps_receiver_gate;
            if(ps_laser_trigger && !previous_laser)last_laser_rise=i;
            if(ps_receiver_gate && !previous_gate && last_laser_rise>=0 && i-last_laser_rise!=15)
                $fatal(1,"gate rising edge must follow laser by 15 cycles");
            previous_laser=ps_laser_trigger;previous_gate=ps_receiver_gate;
        end
        if(laser_high!=18 || gate_high!=27)$fatal(1,"running update pulse widths");
        calibrated=1;
        write_reg(12,1);write_reg(20,4);write_reg(16,1);
        wait(dut.active_tdc);@(negedge tdc_clk);
        if(ps_trig_num!==4 || ps_bin_num!==65535 || ps_bin_width!==3)$fatal(1,"bad config CDC");
        // 采集仍在进行时，独立关闭输出，避免被采集锁或完成状态阻挡。
        write_reg('h40,0);repeat(12)@(negedge tdc_clk);
        if(ps_laser_trigger || ps_receiver_gate || !dut.active_tdc)$fatal(1,"OFF must be independent of capture");
        write_reg('h78,0);write_reg('h84,0);
        write_reg('ha0,800);write_reg('ha8,1);
        read_reg('hb0,value);if(value!==300)$fatal(1,"threshold changed during capture");
        read_reg('h78,value);if(value!==1)$fatal(1,"source changed while capture busy");
        read_reg('h84,value);if(value!==32'h00660200)$fatal(1,"levels changed while capture busy");
        @(negedge tdc_clk);
        for(i=0;i<65536;i=i+1)begin
            hist_valid=1;hist_index=i;hist_count=i+123;@(negedge tdc_clk);
        end
        hist_valid=0;repeat(15)@(posedge s_axi_aclk);
        read_reg(8,value);if(value!==5 || writes!==65536)$fatal(1,"bad completion %h %d",value,writes);
        if(ps_meas_en!==0)$fatal(1,"measurement must stop when capture completes");
        read_reg(32,value);if(value!==1)$fatal(1,"sequence mismatch");
        read_reg(36,value);if(value!==65536)$fatal(1,"count mismatch");
        write_reg('h78,0);repeat(12)@(posedge s_axi_aclk);
        read_reg('h7c,value);if(value!==2 || ps_reference_internal)$fatal(1,"external reference CDC");
        // 第二次启动后终止：必须收到TDC域确认，不能继续写快照。
        write_reg(16,1);wait(dut.active_tdc);write_reg(16,2);repeat(20)@(posedge s_axi_aclk);
        read_reg(40,value);if(value!==2)$fatal(1,"abort mismatch");
        read_reg(8,value);if(value[1]!==0)$fatal(1,"abort busy");
        // 第三帧地址乱序：拒绝写入并报告错误，不把残帧当成有效帧。
        write_reg(16,1);wait(dut.active_tdc);@(negedge tdc_clk);hist_valid=1;hist_index=5;
        @(negedge tdc_clk);hist_valid=0;repeat(20)@(posedge s_axi_aclk);
        read_reg(40,value);if(value!==3)$fatal(1,"ordering check mismatch");
        $display("PASS: threshold defaults/SPI/boundaries/ACK/interlocks, AXI snapshot/CDC/abort, output controls");$finish;
    end
    initial begin #2000000;$fatal(1,"watchdog");end
endmodule
