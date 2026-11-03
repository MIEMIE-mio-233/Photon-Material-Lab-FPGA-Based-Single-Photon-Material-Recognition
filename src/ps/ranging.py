"""PS侧经验测距标定。标定结果不是TDC物理精度的保证。"""
import uuid
from datetime import datetime, timezone
import numpy as np
from acquisition_metadata import parse_distance

FORMAT = 'tdc_ranging_linear_v1'


def fit_calibration(records):
    """先按采集批次等权，避免同批重复帧数量主导标定；使用后峰绝对bin。"""
    if len(records) < 6:
        raise ValueError('标定至少需要6帧、3个已知距离')
    grouped = {}
    for row in records:
        distance = parse_distance(row.get('distance_cm'))
        if distance is None:
            raise ValueError('所选标定批次存在未知距离')
        key = row['run_key']
        grouped.setdefault(key, []).append(row)
    points = []
    for key, rows in sorted(grouped.items()):
        distances = {float(r['distance_cm']) for r in rows}
        if len(distances) != 1:
            raise ValueError('同一批次的标定距离必须一致')
        points.append(dict(run_key=key, material=rows[0]['material'], distance_cm=distances.pop(),
                           echo_bin=float(np.median([r['return_bin'] for r in rows])), frames=len(rows)))
    distances = sorted(set(p['distance_cm'] for p in points))
    if len(distances) < 3:
        raise ValueError('经验标定至少选择3个不同距离；建议另采标准靶标')
    signatures = {r.get('timing_signature') for r in records if r.get('timing_signature')}
    if len(signatures) > 1:
        raise ValueError('标定批次的参考源、输出时序、幅值或阈值不一致')
    steps = {float(r['bin_width_ps']) for r in records}
    if len(steps) != 1:
        raise ValueError('标定批次的bin时间步长不一致')
    x = np.asarray([p['echo_bin'] for p in points]); y = np.asarray([p['distance_cm'] for p in points])
    def solve(a,b):
        center=float(np.mean(a));v=np.polyfit(a-center,b,1)
        return float(v[0]),float(v[1]-v[0]*center)
    slope, intercept = solve(x,y)
    if not np.isfinite(slope+intercept) or slope <= 0:
        raise ValueError('后峰未随距离稳定向后移动，请先检查数据和时间单位')
    residual = slope*x+intercept-y
    # 按整个材质留出，只有单种标准目标时明确没有跨材质验证。
    errors=[];materials=sorted(set(p['material'] for p in points))
    if len(materials)>1:
        for material in materials:
            train=np.asarray([p['material']!=material for p in points])
            if len(set(y[train]))<2:continue
            a,b=solve(x[train],y[train]);errors.extend((a*x[~train]+b-y[~train]).tolist())
    return dict(format=FORMAT, id=uuid.uuid4().hex[:12], created_at=datetime.now(timezone.utc).isoformat(),
                coordinate='absolute_return_bin', cm_per_bin=slope, intercept_cm=intercept,
                bin_width_ps=steps.pop(), timing_signature=next(iter(signatures)) if signatures else None,
                min_cm=min(distances), max_cm=max(distances), distances_cm=distances,
                points=points, source_runs=sorted(grouped), frames=len(records),
                fit_mae_cm=float(np.mean(abs(residual))), fit_rmse_cm=float(np.sqrt(np.mean(residual**2))),
                leave_material_out_mae_cm=float(np.mean(abs(np.asarray(errors)))) if errors else None,
                scope='empirical session calibration; independent standard-target verification still required')


def validate(profile):
    if profile.get('format')!=FORMAT or profile.get('coordinate')!='absolute_return_bin':
        raise ValueError('不支持的测距标定格式')
    for key in ('cm_per_bin','intercept_cm','min_cm','max_cm','bin_width_ps'):
        if isinstance(profile.get(key),bool) or not np.isfinite(profile.get(key,float('nan'))):
            raise ValueError('标定参数损坏：'+key)
    if profile['cm_per_bin']<=0 or profile['min_cm']>=profile['max_cm']:
        raise ValueError('测距标定范围或方向无效')
    return profile


def estimate(profile, echo_bin, bin_width_ps=None, signature=None):
    validate(profile)
    if bin_width_ps is not None and float(bin_width_ps)!=profile['bin_width_ps']:
        raise ValueError('该帧bin时间步长与测距标定不匹配')
    if signature and profile.get('timing_signature') and signature!=profile['timing_signature']:
        raise ValueError('采集设置与测距关系不匹配，请按当前设置重新校准')
    value=float(echo_bin)*profile['cm_per_bin']+profile['intercept_cm']
    if not np.isfinite(value):raise ValueError('测距输入无效')
    return value


def profile_applies_to_model(profile, model_id):
    """新校准由所有分类器共用；历史帧的旧版校准仍遵守原模型绑定。"""
    return bool(profile) and (profile.get('binding') == 'acquisition'
                              or model_id is None or profile.get('model_id') == model_id)




