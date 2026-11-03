`timescale 1ns/1ps
// 参考源是事件信号，不驱动全局时钟树。
// 不重采样外部信号，保留真实到达时间；切换仅允许在停止采集时进行。
module tdc_reference_mux(
    input external_reference, input internal_reference, input use_internal,
    input detector_hit, output [1:0] selected_hit
);
    assign selected_hit[0] = detector_hit;
    assign selected_hit[1] = use_internal ? internal_reference : external_reference;
endmodule
