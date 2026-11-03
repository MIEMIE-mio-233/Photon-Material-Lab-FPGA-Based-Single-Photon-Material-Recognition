"""独立多点测距校准：绑定采集配置和本次启动，不绑定分类模型。"""
import copy
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import numpy as np

from acquisition_metadata import parse_distance
from model_registry import write_json
from ranging import FORMAT, validate


def boot_identity():
    path = Path('/proc/sys/kernel/random/boot_id')
    return path.read_text().strip() if path.is_file() else 'local-development'


def fit_live_profile(points):
    """直接用至少3个距离的实测峰位拟合，无需分类器或模型内原始曲线。"""
    if not points or any(p.get('frame_count') != 10 for p in points):
        raise ValueError('每个校准点必须有10个完整帧，请删除旧版不足10帧的点')
    signatures = {p.get('signature') for p in points}
    steps = {p.get('bin_width_ps') for p in points}
    if len(signatures) != 1 or not next(iter(signatures)) or len(steps) != 1:
        raise ValueError('校准点采集配置不同，请删除不匹配的点后重新采集')
    step = next(iter(steps))
    if isinstance(step, bool) or not isinstance(step, (float, int)) or not np.isfinite(step) or step <= 0:
        raise ValueError('校准点bin时间步长无效')
    values = [parse_distance(p['distance_cm']) for p in points]
    if None in values or len(set(values)) < 3:
        raise ValueError('多点拟合至少需要3个不同距离')
    distances = sorted(set(values))
    if distances[-1] - distances[0] < 5:
        raise ValueError('多点校准距离跨度至少5 cm')
    # 同距离的重复点等权汇总；单个点已是10帧逐帧选峰的中位数。
    x = np.asarray([np.median([p['return_bin'] for p, d0 in zip(points, values) if d0 == d])
                    for d in distances], dtype=float)
    y = np.asarray(distances, dtype=float)
    if not np.isfinite(x).all() or np.ptp(x) < 1:
        raise ValueError('不同距离的回波峰没有有效移动，请检查信号和接线')
    center = float(x.mean())
    coefficients = np.polyfit(x - center, y, 1)
    slope = float(coefficients[0])
    intercept = float(coefficients[1] - slope * center)
    # 用名义bin宽做宽松合理性检查，避免误填距离产生反向/异常斜率。
    nominal = 299792458 * float(step) * 1e-12 / 2 * 100
    if not np.isfinite(slope + intercept) or not .5 * nominal <= slope <= 2 * nominal:
        raise ValueError('校准斜率与名义bin时间步长差异过大，请检查距离、信号和选峰')
    residual = slope * x + intercept - y
    if np.max(abs(residual)) > min(2.25, float(np.ptp(y)) * .15):
        raise ValueError('多点残差过大，不能用直线解释，请复测后再应用')
    profile = dict(format=FORMAT, id=uuid.uuid4().hex[:12],
                   created_at=datetime.now(timezone.utc).isoformat(),
                   coordinate='absolute_return_bin', binding='acquisition', mode='multi',
                   cm_per_bin=slope, intercept_cm=intercept, bin_width_ps=float(step),
                   timing_signature=next(iter(signatures)),
                   min_cm=float(y.min()), max_cm=float(y.max()), distances_cm=distances,
                   points=copy.deepcopy(points), frames=sum(p['frame_count'] for p in points),
                   fit_mae_cm=float(np.mean(abs(residual))),
                   fit_max_error_cm=float(np.max(abs(residual))),
                   scope='session multi-point calibration; independent of classifier; fit residual is not ranging accuracy')
    return validate(profile)


def _independent_record(record):
    """旧模型编号只作来源追溯，不再作为应用校准的条件。"""
    result = copy.deepcopy(record)
    if 'model_id' in result:
        result['legacy_model_id'] = result.pop('model_id')
    return result


class LiveRangeCalibration:
    def __init__(self, folder, boot_id=None):
        self.lock = threading.RLock()
        self.root = Path(folder)
        self.boot_id = boot_id or boot_identity()
        self.state = self._empty()
        path = self.root / 'state.json'
        if path.is_file():
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved.get('boot_id') == self.boot_id:
                self.state = self._migrate(saved)

    def _empty(self):
        return dict(schema_version=2, boot_id=self.boot_id, points=[], profile=None)

    def _migrate(self, saved):
        if saved.get('schema_version') == 2:
            return saved
        state = self._empty()
        state['points'] = [_independent_record(p) for p in saved.get('points', [])]
        # 只沿用旧版最后启用的多点曲线，不在多个旧模型曲线中自动猜选。
        previous = saved.get('profiles', {}).get(saved.get('last_model_id'))
        if previous and previous.get('mode') == 'multi':
            profile = _independent_record(previous)
            profile['points'] = [_independent_record(p) for p in previous['points']]
            if (all(p.get('frame_count') == 10 for p in profile['points'])
                    and len({p['distance_cm'] for p in profile['points']}) >= 3):
                validate(profile)
                profile['binding'] = 'acquisition'
                state['profile'] = profile
        # 不改动峰位、系数及原始校准帧；部署备份保留完整旧版state。
        return state

    def serialized(method):
        @wraps(method)
        def run(self, *args, **kwargs):
            with self.lock:
                return method(self, *args, **kwargs)
        return run

    def summary(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def _save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self.root / 'state.json', self.state)

    @serialized
    def check_context(self, context):
        """采集前核对已有点，避免等10帧后才发现配置不兼容。"""
        if not context.get('signature') or not context.get('bin_width_ps'):
            raise ValueError('无法读取有效采集配置，请先加载本项目Overlay')
        if any(p.get('signature') != context['signature']
               or p.get('bin_width_ps') != context['bin_width_ps'] for p in self.state['points']):
            raise ValueError('已有点的采集配置不同，请删除不匹配的点后重新采集')
        if len(self.state['points']) >= 30:
            raise ValueError('最多30个点，请删除不需要的点')

    @serialized
    def capture_group(self, frames, distance_cm, context):
        """10个完整帧才提交一点；分类模型不参与采集、峰位统计或存储。"""
        distance = parse_distance(distance_cm)
        if distance is None or len(frames) != 10:
            raise ValueError('每个校准点必须有10个完整帧和实际距离')
        self.check_context(context)
        from train_material import locate_histogram
        peaks = [locate_histogram(frame)[2:] for frame in frames]
        point = dict(id=uuid.uuid4().hex[:12], distance_cm=distance,
                     reference_bin=float(np.median([p[0] for p in peaks])),
                     return_bin=float(np.median([p[1] for p in peaks])), frame_count=10,
                     reference_bins=[int(p[0]) for p in peaks], return_bins=[int(p[1]) for p in peaks],
                     signature=context['signature'], bin_width_ps=context['bin_width_ps'],
                     created_at=datetime.now(timezone.utc).isoformat())
        values = np.asarray(frames, dtype=np.uint32)
        self.root.mkdir(parents=True, exist_ok=True)
        frame = self.root / ('point_' + point['id'] + '.npz')
        np.savez_compressed(str(frame), counts=values)
        point.update(frame_file=frame.name, counts_sha256=hashlib.sha256(values.tobytes()).hexdigest())
        self.state['points'].append(point)
        self._save()
        return point

    @serialized
    def delete_point(self, point_id):
        selected = next((p for p in self.state['points'] if p['id'] == point_id), None)
        if selected is None:
            raise ValueError('该校准点不存在，请刷新页面')
        filename = selected.get('frame_file')
        if filename:
            path = self.root / filename
            if path.is_symlink():
                raise ValueError('校准点文件路径无效')
            path = path.resolve()
            path.relative_to(self.root.resolve())
            if path.parent != self.root.resolve():
                raise ValueError('校准点文件路径无效')
            if path.is_file():
                path.unlink()
        self.state['points'] = [p for p in self.state['points'] if p['id'] != point_id]
        profile = self.state['profile']
        if profile and any(p['id'] == point_id for p in profile['points']):
            self.state['profile'] = None
        self._save()
        return selected

    @serialized
    def apply_multi(self):
        profile = fit_live_profile(self.state['points'])
        self.state['profile'] = profile
        self._save()
        write_json(self.root / ('profile_' + profile['id'] + '.json'), profile)
        return profile

    def profile(self):
        with self.lock:
            return copy.deepcopy(self.state['profile'])

    @serialized
    def clear(self):
        self.state = self._empty()
        self._save()
