// time_merge_eval_bb -- 评估版网表 IP 的综合期黑盒占位(端口与 DCP 顶层完全一致)
// 综合时保留为黑盒, 实现阶段由 time_merge_eval.dcp 经 opt 前置 hook 填充
//
// DCP 编译配置(完整版见 top_tdc.v 例化处注释 / doc/time_merge_ip_使用说明.md):
//   - DCP: USED_IN_SYNTHESIS=false + SCOPED_TO_CELLS={u_top_tdc/u_time_merge}
//   - impl_1 挂 STEPS.OPT_DESIGN.TCL.PRE=pre_opt_fill.tcl(read_checkpoint -cell)
//   - 禁止对延时线加 LOC(刚体宏必 place 失败); 通道顺序由外部接线标定
//   - 授权 DNA 固化于 DCP, 换芯片需重新生成网表
(* black_box *)
module time_merge_eval(
    input                               sys_rst                    ,// 复位, 高有效
    input                               sys_clk                    ,// 时钟 300MHz
    input                               tdc_meas_en                ,// 测量使能
    input                               calibra_en                 ,// 校准使能
    input                               calibra_sig                ,// 校准基准信号
    input              [   1:0]         measure_sig                ,// 测量信号输入
    output             [   1:0]         calibra_finish             ,// 校准完成标志
    output             [ 127:0]         tdc_time                   ,// 合并时间戳输出
    output             [   1:0]         tdc_time_vaild              // 时间戳有效
);
endmodule
