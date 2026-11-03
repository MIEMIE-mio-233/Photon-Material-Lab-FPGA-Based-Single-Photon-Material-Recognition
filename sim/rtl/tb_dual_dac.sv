`timescale 1ns/1ps
// 校验真实ODDRE1模型：上升沿发数据，半拍后DAC采样，板内参考跟随采样沿。
module tb_dual_dac;
    reg clk=0, rst=1, laser_trigger=0, receiver_gate=0;
    always #4 clk=~clk;
    reg [9:0] dac1_low=512,dac1_high=174,dac2_low=500,dac2_high=200;
    wire dac1_clk,dac2_clk,reference_trigger;
    wire [9:0] dac1_data,dac2_data;
    reg external_reference=0,detector_hit=0,use_internal=0;
    wire [1:0] selected_hit;
    dual_dac_trigger dut(.*);
    tdc_reference_mux mux(.external_reference(external_reference),
        .internal_reference(reference_trigger),.use_internal(use_internal),
        .detector_hit(detector_hit),.selected_hit(selected_hit));
    integer samples=0, high_samples=0, high_before=0;
    reg expected_laser=0,expected_gate=0;
    always @(posedge clk) begin
        expected_laser=laser_trigger;
        expected_gate=receiver_gate;
    end
    time previous_rise=0, changed1=0, changed2=0;
    always @(dac1_data) changed1=$time;
    always @(dac2_data) changed2=$time;
    always @(posedge dac1_clk) if(!rst) begin
        #0.001;
        if(dac2_clk!==1 || clk!==0)$fatal(1,"forwarded clock polarity");
        if(previous_rise && $time-previous_rise!=8)$fatal(1,"125MHz period");
        if($time-changed1<4 || $time-changed2<4)$fatal(1,"data setup half-cycle");
        if(dac1_data!==(expected_laser ? dac1_high:dac1_low))$fatal(1,"DAC1 code");
        if(dac2_data!==(expected_gate ? dac2_low:dac2_high))$fatal(1,"DAC2 active-low code");
        if(reference_trigger!==expected_laser)$fatal(1,"reference alignment");
        previous_rise=$time;samples=samples+1;
        if(expected_laser) high_samples=high_samples+1;
    end
    initial begin
        #120;if(reference_trigger || dac1_data!==512 || dac2_data!==102)$fatal(1,"reset must inhibit detector");
        #2;rst=0;
        // 输入未重新定时，保留外部异步事件的边沿时刻。
        #1;external_reference=1;detector_hit=1;
        #0.001;if(selected_hit!==2'b11)$fatal(1,"external passthrough");
        #1;external_reference=0;
        #0.001;if(selected_hit!==2'b01)$fatal(1,"independent detector");
        use_internal=1;
        repeat(4)@(posedge clk);
        #1;laser_trigger=1;receiver_gate=1;
        repeat(3)@(posedge clk);
        #1;if(selected_hit!==2'b11)$fatal(1,"internal reference mux");
        laser_trigger=0;receiver_gate=0;
        repeat(4)@(posedge clk);
        #1;if(reference_trigger || dac1_data!==512 || dac2_data!==200)$fatal(1,"OFF must keep detector high/closed");
        if(samples<8)$fatal(1,"clock stopped when OFF");
        // 最窄一拍8ns的脉冲也必须恰好成为一个高码采样，不漏采也不拉长。
        high_before=high_samples;
        @(negedge clk);#1;laser_trigger=1;
        @(negedge clk);#1;laser_trigger=0;
        repeat(3)@(posedge clk);#1;
        if(high_samples-high_before!=1)$fatal(1,"one-cycle pulse lost or stretched");
        $display("PASS: dual DAC 125MHz, half-cycle setup, codes, OFF clock, internal/external reference");
        $finish;
    end
    initial begin #1000;$fatal(1,"watchdog");end
endmodule

