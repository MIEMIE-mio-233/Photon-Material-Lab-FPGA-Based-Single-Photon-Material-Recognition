"""统计特征契约。旧8维模型可读取，新训练默认增加相对参考峰位这一维。"""
import numpy as np

LEGACY_VERSION = 'tdc_echo_v2_integer_windows'
FEATURE_VERSION = 'tdc_echo_v3_peak_shift'
LEGACY_NAMES = [
    'return_area_150_over_reference', 'return_area_350_over_reference',
    'return_peak_over_reference', 'return_core_fraction', 'return_tail_over_head',
    'return_width_half_max_bins', 'return_weighted_sigma_bins', 'return_peak_to_area',
]
FEATURE_NAMES = LEGACY_NAMES + ['return_peak_shift_bins']


def feature_count(metadata):
    """版本和顺序都必须匹配；不能将新9维参数装进旧8维槽位。"""
    version, names = metadata.get('feature_version'), metadata.get('feature_names')
    if version == FEATURE_VERSION and names == FEATURE_NAMES:
        return 9
    if version == LEGACY_VERSION and names == LEGACY_NAMES:
        return 8
    raise ValueError('模型特征版本或顺序不匹配，请重新训练或使用配套程序')


def model_features(features, metadata):
    """提取时第9维是原始回波峰bin；在模型边界减去该模型保存的公共基线。"""
    n = feature_count(metadata)
    result = np.asarray(features, dtype=np.float64)[..., :n].copy()
    if n == 9:
        baseline = float(metadata.get('timing_reference_bin', 0.0))
        if not np.isfinite(baseline):
            raise ValueError('时移参考峰位不是有限数值')
        result[..., 8] -= baseline
    return result


def reference_from_training(data, indices):
    """优先用训练折内15cm Fe的中位峰位；没有则保留绝对峰位，明确记录。

    不读取留出标签来调零，也不因缺少Fe而阻止用户训练其他材质。
    对固定基线做减法只是坐标平移；它不等于在线补偿每次上电的漂移。
    """
    refs = [data.features[i, 8] for i in indices
            if str(data.labels[i]).lower() == 'fe'
            and data.details[i][1].get('distance_cm') == 15.0]
    return (float(np.median(refs)), 'training_fe_15cm') if refs else (0.0, 'absolute_peak_fallback')
