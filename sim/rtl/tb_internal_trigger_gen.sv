`timescale 1ns / 1ps

module tb_internal_trigger_gen;
    reg clk = 0;
    always #(5.0/3.0) clk = ~clk;
    reg rst = 1;
    reg enable = 0;
    reg apply_toggle = 0;
    reg [31:0] cfg_period = 3000;
    reg [31:0] cfg_laser_delay = 0;
    reg [31:0] cfg_laser_width = 1500;
    reg [31:0] cfg_receiver_delay = 240;
    reg [31:0] cfg_receiver_width = 2400;
    wire laser_trigger, receiver_gate, running, config_error, applied_toggle;
    wire [31:0] active_period, active_laser_delay, active_laser_width;
    wire [31:0] active_receiver_delay, active_receiver_width;

    internal_trigger_gen dut (.*);

    task tick;
        @(posedge clk); #0.1;
    endtask

    task check_output(input integer phase, input integer ld, input integer lw,
                      input integer rd, input integer rw);
        if (laser_trigger !== (phase >= ld && phase < ld+lw))
            $fatal(1, "Laser pulse mismatch at phase %0d", phase);
        if (receiver_gate !== (phase >= rd && phase < rd+rw))
            $fatal(1, "Receiver pulse mismatch at phase %0d", phase);
    endtask

    task check_periods(input integer p, input integer ld, input integer lw,
                       input integer rd, input integer rw, input integer count);
        integer i;
        for (i=0; i<p*count; i=i+1) begin
            tick();
            check_output(i%p, ld,lw,rd,rw);
            if (!running) $fatal(1, "Unexpected stopped generator");
        end
    endtask

    task stop_output;
        @(negedge clk); enable=0;
        tick();
        if (laser_trigger || receiver_gate || running)
            $fatal(1, "Disable did not clear both outputs");
    endtask

    task request_config(input reg [31:0] p,ld,lw,rd,rw);
        @(negedge clk);
        cfg_period=p;cfg_laser_delay=ld;cfg_laser_width=lw;
        cfg_receiver_delay=rd;cfg_receiver_width=rw;
        apply_toggle=~apply_toggle;
    endtask

    // 独立参考按绝对经过的拍数计算；首个窗口必须从delay开始，不能凭空输出尾巴。
    task check_wrap(input integer p,ld,lw,rd,rw);
        integer n; reg expected_laser,expected_receiver;
        stop_output(); request_config(p,ld,lw,rd,rw); repeat(3)tick();
        if(config_error)$fatal(1,"valid wrapping window rejected");
        @(negedge clk);enable=1;
        for(n=0;n<5*p;n=n+1)begin
            tick();
            expected_laser=n>=ld && ((n-ld)%p)<lw;
            expected_receiver=n>=rd && ((n-rd)%p)<rw;
            if(laser_trigger!==expected_laser || receiver_gate!==expected_receiver)
                $fatal(1,"wrap/startup mismatch t=%d p=%d",n,p);
        end
    endtask

    integer i;
    reg previous_applied;
    initial begin
        repeat(3) tick();
        if (laser_trigger || receiver_gate) $fatal(1,"Reset output not low");
        @(negedge clk); rst=0;
        repeat(2) tick();
        @(negedge clk); enable=1;

        // Confirm the photographed waveforms, including the 800ns relative delay.
        check_periods(3000,0,1500,240,2400,3);
        $display("PASS: default 100kHz, laser 5us, receiver delay 800ns / width 8us");

        // Update while the old pulse is high. The current cycle must finish unchanged.
        for (i=0;i<100;i=i+1) begin
            tick(); check_output(i,0,1500,240,2400);
        end
        previous_applied=applied_toggle;
        request_config(200,7,3,23,80);
        for (i=100;i<3000;i=i+1) begin
            tick();check_output(i,0,1500,240,2400);
            if (i<2999 && active_period!=3000)
                $fatal(1,"New configuration applied mid-cycle");
        end
        if (active_period!=200 || applied_toggle==previous_applied)
            $fatal(1,"Configuration did not commit at boundary");
        check_periods(200,7,3,23,80,3);
        $display("PASS: delayed 10ns laser pulse, both widths adjustable, atomic boundary update");

        // Invalid configuration: zero width and overflowing delay must be rejected.
        stop_output();
        previous_applied=applied_toggle;
        request_config(200,0,0,0,80);
        repeat(3) tick();
        if (!config_error || active_period!=200 || applied_toggle!=previous_applied)
            $fatal(1,"Zero width was accepted");
        request_config(200,32'hFFFFFFFF,3,0,80);
        repeat(3) tick();
        if (!config_error || active_laser_delay!=7)
            $fatal(1,"Overflowing delay was accepted");
        request_config(200,0,3,200,80);
        repeat(3) tick();
        if (!config_error || active_receiver_delay!=23)
            $fatal(1,"phase outside period was accepted");

        check_wrap(20,17,7,18,5);
        check_wrap(20,0,1,19,19);
        check_wrap(20,19,19,0,1);
        check_wrap(20,3,17,18,2); // 两个终点恰好落在周期边界
        if(!dut.window_active(0,32'hfffffff0,32'h20,32'hffffffff) ||
           !dut.window_active(16,32'hfffffff0,32'h20,32'hffffffff) ||
           dut.window_active(17,32'hfffffff0,32'h20,32'hffffffff))
            $fatal(1,"32-bit endpoint overflow");
        $display("PASS: wrapping windows, first complete pulse, boundary equality and 33-bit endpoint");
        stop_output();

        // Valid configuration while stopped, including toggling APPLY from 1 back to 0.
        request_config(2,0,1,1,1);
        repeat(3) tick();
        if (config_error || active_period!=2) $fatal(1,"Stopped update failed");
        @(negedge clk);enable=1;
        check_periods(2,0,1,1,1,4);
        stop_output();
        @(negedge clk);enable=1;
        tick();check_output(0,0,1,1,1);
        stop_output();
        $display("PASS: invalid input rejection, minimum widths, disable/restart");

        @(negedge clk);rst=1;
        tick();
        if (active_period!=3000 || laser_trigger || receiver_gate)
            $fatal(1,"Reset did not restore defaults");
        $display("ALL TESTS PASSED");
        $finish;
    end
    initial begin #100000; $fatal(1,"Test timeout"); end
endmodule
