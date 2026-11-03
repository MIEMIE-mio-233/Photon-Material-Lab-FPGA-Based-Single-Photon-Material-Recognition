`timescale 1ns / 1ps

// 双路周期窗口：delay是相对周期起点的相位，width是窗口持续拍数。
// 两个参数均小于period，但delay+width可以跨周期；逻辑1表示窗口有效。
// DAC2的低有效电平转换由dual_dac_trigger完成，不在通用发生器中反相。
module internal_trigger_gen #(
    parameter [31:0] DEFAULT_PERIOD = 32'd3000,
    parameter [31:0] DEFAULT_LASER_DELAY = 32'd0,
    parameter [31:0] DEFAULT_LASER_WIDTH = 32'd1500,
    parameter [31:0] DEFAULT_RECEIVER_DELAY = 32'd240,
    parameter [31:0] DEFAULT_RECEIVER_WIDTH = 32'd2400
)(
    input wire clk, input wire rst, input wire enable, input wire apply_toggle,
    input wire [31:0] cfg_period, cfg_laser_delay, cfg_laser_width,
    input wire [31:0] cfg_receiver_delay, cfg_receiver_width,
    output reg laser_trigger, output reg receiver_gate,
    output reg running, output reg config_error, output reg applied_toggle,
    output reg [31:0] active_period, active_laser_delay, active_laser_width,
    output reg [31:0] active_receiver_delay, active_receiver_width
);
    reg [31:0] phase_count;
    reg apply_seen, pending_valid, epoch_started;
    reg [31:0] pending_period, pending_laser_delay, pending_laser_width;
    reg [31:0] pending_receiver_delay, pending_receiver_width;

    // 使用33位终点，避免接近32位上限时delay+width溢出。
    // 仅加减和比较，不引入除法/取模运算硬件。
    function window_active;
        input [31:0] phase, delay_ticks, width_ticks, period_ticks;
        reg [32:0] end_ticks;
        begin
            end_ticks = {1'b0,delay_ticks} + {1'b0,width_ticks};
            if (end_ticks <= {1'b0,period_ticks})
                window_active = phase >= delay_ticks && {1'b0,phase} < end_ticks;
            else
                window_active = phase >= delay_ticks ||
                                {1'b0,phase} < end_ticks - {1'b0,period_ticks};
        end
    endfunction

    wire cfg_valid = cfg_period >= 2 &&
                     cfg_laser_width >= 1 && cfg_receiver_width >= 1 &&
                     cfg_laser_width < cfg_period && cfg_receiver_width < cfg_period &&
                     cfg_laser_delay < cfg_period && cfg_receiver_delay < cfg_period;
    wire new_request = apply_toggle != apply_seen;
    wire cycle_end = phase_count == active_period - 1;
    wire commit = pending_valid && !new_request && (!enable || cycle_end);

    always @(posedge clk) begin
        if (rst) begin
            phase_count <= 0; apply_seen <= 0; pending_valid <= 0; epoch_started <= 0;
            pending_period <= DEFAULT_PERIOD;
            pending_laser_delay <= DEFAULT_LASER_DELAY;
            pending_laser_width <= DEFAULT_LASER_WIDTH;
            pending_receiver_delay <= DEFAULT_RECEIVER_DELAY;
            pending_receiver_width <= DEFAULT_RECEIVER_WIDTH;
            active_period <= DEFAULT_PERIOD;
            active_laser_delay <= DEFAULT_LASER_DELAY;
            active_laser_width <= DEFAULT_LASER_WIDTH;
            active_receiver_delay <= DEFAULT_RECEIVER_DELAY;
            active_receiver_width <= DEFAULT_RECEIVER_WIDTH;
            laser_trigger <= 0; receiver_gate <= 0; running <= 0;
            config_error <= 0; applied_toggle <= 0;
        end else begin
            if (new_request) begin
                apply_seen <= apply_toggle;
                if (cfg_valid) begin
                    pending_period <= cfg_period;
                    pending_laser_delay <= cfg_laser_delay;
                    pending_laser_width <= cfg_laser_width;
                    pending_receiver_delay <= cfg_receiver_delay;
                    pending_receiver_width <= cfg_receiver_width;
                    pending_valid <= 1; config_error <= 0;
                end else begin
                    pending_valid <= 0; config_error <= 1;
                end
            end
            if (commit) begin
                active_period <= pending_period;
                active_laser_delay <= pending_laser_delay;
                active_laser_width <= pending_laser_width;
                active_receiver_delay <= pending_receiver_delay;
                active_receiver_width <= pending_receiver_width;
                pending_valid <= 0; applied_toggle <= ~applied_toggle;
            end
            if (!enable) begin
                phase_count <= 0; epoch_started <= 0;
                laser_trigger <= 0; receiver_gate <= 0; running <= 0;
            end else begin
                // 启用/换参数后的首周期不输出“上一周期的尾巴”，
                // 等待各自起点再开始首个完整窗口，避免凭空产生截短触发。
                laser_trigger <= window_active(phase_count, active_laser_delay,
                                               active_laser_width, active_period) &&
                                 (epoch_started || phase_count >= active_laser_delay);
                receiver_gate <= window_active(phase_count, active_receiver_delay,
                                               active_receiver_width, active_period) &&
                                 (epoch_started || phase_count >= active_receiver_delay);
                phase_count <= cycle_end ? 0 : phase_count + 1;
                if (cycle_end) epoch_started <= !commit;
                running <= 1;
            end
        end
    end

    // synthesis translate_off
    initial begin
        if (DEFAULT_PERIOD < 2 || DEFAULT_LASER_WIDTH < 1 || DEFAULT_RECEIVER_WIDTH < 1 ||
            DEFAULT_LASER_WIDTH >= DEFAULT_PERIOD || DEFAULT_RECEIVER_WIDTH >= DEFAULT_PERIOD ||
            DEFAULT_LASER_DELAY >= DEFAULT_PERIOD || DEFAULT_RECEIVER_DELAY >= DEFAULT_PERIOD)
            $fatal(1, "Invalid periodic window defaults");
    end
    // synthesis translate_on
endmodule
