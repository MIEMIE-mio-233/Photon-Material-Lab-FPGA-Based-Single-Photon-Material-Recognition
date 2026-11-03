"""网页物理单位与125MHz DAC寄存器的转换，不依赖PYNQ硬件。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CLOCK_HZ = 125000000
INTERFACE_VERSION = 5
TIMING_SCHEMA = "active_windows_v1"
LEVEL_FIELDS = ("dac1_low", "dac1_high", "dac2_low", "dac2_high")
# 网页正向高电平码1023对应原始码0；实际最大电压由DAC模块决定。
LEVEL_DEFAULTS = dict(zip(LEVEL_FIELDS, (512, 0, 512, 0)))
REFERENCE_DEFAULT = "internal"
FIELDS = ("frequency_khz", "laser_delay_ns", "laser_width_ns", "gate_delay_ns", "gate_width_ns")
DEFAULTS = dict(zip(FIELDS, (100, 0, 5000, 9000, 2000)))


def actual_settings(cycles):
    """返回硬件实际参数；最小时间步长为8ns。"""
    period, laser_delay, laser_width, gate_delay, gate_width = cycles
    tick_ns = 1e9 / CLOCK_HZ
    return dict(zip(FIELDS, (CLOCK_HZ / 1000.0 / period, laser_delay * tick_ns,
                            laser_width * tick_ns, gate_delay * tick_ns, gate_width * tick_ns)))


def parse_settings(options):
    """相位在[0,周期)内，持续时长在(0,周期)内；窗口末尾允许跨周期。"""
    values = []
    for key in FIELDS:
        value = options.get(key, DEFAULTS[key])
        try:
            if isinstance(value, bool):
                raise ValueError()
            value = Decimal(str(value))
            if not value.is_finite() or value < 0 or (key == "frequency_khz" and value == 0):
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValueError("{} 必须是有效的{}数值".format(key, "正" if key == "frequency_khz" else "非负"))
        values.append(value)
    quantized = [(Decimal(CLOCK_HZ) / 1000 / values[0]).to_integral_value(rounding=ROUND_HALF_UP)]
    quantized.extend((value * Decimal(CLOCK_HZ) / Decimal(1000000000)).to_integral_value(rounding=ROUND_HALF_UP) for value in values[1:])
    if any(value > 0xffffffff for value in quantized):
        raise ValueError("频率或延迟超出32位硬件计数范围")
    cycles = [int(value) for value in quantized]
    period, ld, lw, gd, gw = cycles
    if any(value > 0xffffffff for value in cycles) or period < 2:
        raise ValueError("频率或延迟超出32位硬件计数范围")
    if not 1 <= lw < period or not 1 <= gw < period:
        raise ValueError("两路脉宽至少为一拍（8ns），且必须小于周期")
    if ld >= period or gd >= period:
        raise ValueError("两路开启相位必须小于周期；开启相位加时长可以跨周期")
    return cycles


def window_summary(cycles):
    """给网页返回实际有效窗口；仅描述数字时序，不冒充实测出光/响应延迟。"""
    period, ld, lw, gd, gw = cycles
    result = {"period_ns": period * 8, "origin": "period_start"}
    for name, start, width, active, idle in (("laser",ld,lw,"high","low"),
                                              ("gate",gd,gw,"low","high")):
        end = start + width
        segments = [[start, min(end, period)]]
        if end > period: segments = [[0, end-period]] + segments
        result[name] = dict(active_level=active, idle_level=idle, wraps_cycle=end>period,
                            start_ns=start*8, duration_ns=width*8, end_phase_ns=(end%period)*8,
                            segments_ns=[[a*8,b*8] for a,b in segments])
    return result


def parse_levels(options, current=None):
    """码值0–1023；不把3.3V数字IO电压误当成模拟输出电压。"""
    result = {}
    defaults = LEVEL_DEFAULTS if current is None else current
    for key in LEVEL_FIELDS:
        value = options.get(key, defaults[key])
        try:
            number = Decimal(str(value))
            if isinstance(value, bool) or not number.is_finite() or number != int(number) or not 0 <= number <= 1023:
                raise ValueError()
        except (InvalidOperation, ValueError, OverflowError):
            raise ValueError("{} 必须是0–1023的整数码值".format(key))
        result[key] = int(number)
    return result
