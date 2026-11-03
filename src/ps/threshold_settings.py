"""比较器阈值的物理单位转换；独立于触发波形 DAC 的10位正向码。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

DEFAULT_V = Decimal("0.300")
MAX_V = Decimal("1.000")
FIELDS = ("threshold_a_v", "threshold_b_v")


def parse_thresholds(options):
    """返回两路整数 mV；按2mV就近量化，半步向上，拒绝非有限数和越界值。"""
    result = []
    for key in FIELDS:
        value = options.get(key, DEFAULT_V)
        try:
            if isinstance(value, bool):
                raise ValueError()
            voltage = Decimal(str(value))
            if not voltage.is_finite() or not 0 <= voltage <= MAX_V:
                raise ValueError()
            millivolts = int((voltage * 500).to_integral_value(rounding=ROUND_HALF_UP)) * 2
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("{} 必须是0～1.000 V之间的有效电压".format(key))
        result.append(millivolts)
    return result
