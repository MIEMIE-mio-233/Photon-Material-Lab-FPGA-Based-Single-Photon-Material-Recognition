"""采集元数据v2：实物身份与距离分开；背景不属于材质类别。"""
import hashlib
import json
from decimal import Decimal, InvalidOperation

SCHEMA_VERSION = 2
SAMPLE_KINDS = ('material', 'blocked_background', 'empty_background')
ILLUMINATIONS = {'shielded':'遮光', 'partial':'半遮光', 'exposed':'暴露'}


def illumination(value):
    """旧数据没有光照标记时保持未知；不能根据日期猜测实验条件。"""
    if value is None or value=='':return None
    if value not in ILLUMINATIONS:raise ValueError('采集类型应为遮光、半遮光或暴露')
    return value


def parse_distance(value):
    """未知距离用None，绝不能将空值当作0cm参与标定。"""
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
        if isinstance(value, bool) or not number.is_finite() or not Decimal('0.01') <= number <= 10000:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise ValueError('距离应为0.01–10000 cm的有效数值，未知可留空')
    return float(number)


def sample_kind(row):
    kind = row.get('sample_kind')
    if str(row.get('material_id',row.get('material',''))).lower()=='bgm':
        return 'empty_background' if kind=='empty_background' else 'blocked_background'
    if kind in SAMPLE_KINDS:
        return kind
    return 'blocked_background' if str(row.get('material_id', row.get('material', ''))).lower() == 'bgm' else 'material'


def material_row(row):
    from data_catalog import has_material_label
    return sample_kind(row) == 'material' and has_material_label(row.get('material_id', row.get('material')))


def timing_signature(config):
    """只描述影响当前标定的设置；不把状态、序号、当前模型混入签名。"""
    output = config.get('output_settings') or {}
    if not output.get('actual') or not output.get('levels'):
        return None
    values = dict(bin_num=config.get('bin_num'), bin_width=config.get('bin_width'),
                  timing=output['actual'], levels=output['levels'], reference=output.get('reference_source'),
                  thresholds={k: output.get('thresholds', {}).get(k) for k in ('threshold_a_v','threshold_b_v')})
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',',':')).encode()).hexdigest()
