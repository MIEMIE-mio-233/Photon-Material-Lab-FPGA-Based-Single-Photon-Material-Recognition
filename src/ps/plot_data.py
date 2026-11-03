"""训练时保存轻量绘图快照；不导入 Matplotlib，不改变训练或推理参数。"""
from pathlib import Path
import json
import numpy as np


def holdout_diagnostics(model, X, labels, algorithm):
    """仅分析既有留出模型，不重新拟合、不用训练集准确率替代验证结果。"""
    if algorithm == 'random_forest':
        total = np.zeros((len(X), len(model.classes_)), dtype=float)
        individual, cumulative = [], []
        for tree in model.estimators_:
            scores = tree.predict_proba(X)
            total += scores
            individual.append(float(np.mean(model.classes_[scores.argmax(axis=1)] == labels)))
            cumulative.append(float(np.mean(model.classes_[total.argmax(axis=1)] == labels)))
        return dict(scope='holdout',samples=len(labels),tree_accuracy=individual,cumulative_accuracy=cumulative)
    return dict(scope='holdout',samples=len(labels))


def save_plot_data(model_path, report, X, labels, details, read_frame,
                   smooth_histogram, read_raw_frame, prefer_raw=False):
    """只保留8维特征和每类一个峰区示例；后续绘图不依赖公共批次仍然存在。"""
    model_path = Path(model_path)
    arrays = dict(features=np.asarray(X,dtype=np.float64),labels=np.asarray(labels,dtype=str))
    meta = dict(schema_version=1,model_id=report['model_id'],classes=list(report['class_names']),examples=[])
    for index,name in enumerate(meta['classes']):
        path,row,detail = next(item for item in details if item[1]['material_id']==name)
        raw = path.parents[1]/row.get('raw_path','')
        if prefer_raw and raw.is_file():
            raw.resolve().relative_to(path.parents[1].resolve())
            _,signal = read_raw_frame(raw,int(row['bin_num']))
        else:
            _,signal = read_frame(path)
        smooth,_ = smooth_histogram(signal)
        example = dict(material=name,reference_bin=int(detail['reference_bin']),return_bin=int(detail['return_bin']))
        for part,center,radius in [('reference',example['reference_bin'],350),('return',example['return_bin'],600)]:
            positions = np.arange(max(0,center-radius),min(len(signal),center+radius+1))
            key = '{}_{}'.format(part,index)
            arrays[key+'_x'] = positions.astype(np.int32)
            arrays[key+'_raw'] = np.asarray(signal[positions],dtype=np.float64)
            arrays[key+'_smooth'] = np.asarray(smooth[positions],dtype=np.float64)
        meta['examples'].append(example)
    # 不使用object数组或pickle；版本归档后同模型的图始终使用这一份数据。
    np.savez_compressed(str(model_path.with_suffix('.plot_data.npz')),**arrays)
    model_path.with_suffix('.plot_meta.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
