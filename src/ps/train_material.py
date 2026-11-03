"""读取公共TDC数据集，训练RF、决策树、小型CNN或小型MLP并展示结果。

用法：python train_material.py
前面的窄高峰只作时间参考；分类特征取自后面的实际回波。
"""

import argparse
import csv
import json
import os
import time
import uuid
import gc
import warnings
from datetime import datetime, timezone
from collections import Counter, namedtuple
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, FunctionTransformer
from sklearn.inspection import permutation_importance
from sklearn.exceptions import ConvergenceWarning
from model_algorithms import ALGORITHMS, estimators
from dense_models import cast_features, export_dense, pack_dense


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = SCRIPT_DIR / "dataset"
DEFAULT_MODEL = SCRIPT_DIR / "models" / "material_model.joblib"

# 只在这里调整森林规模；类别数量和名称由数据集自动决定。
FOREST_TREES = 32
FOREST_MAX_DEPTH = 8
FOREST_MIN_SAMPLES_LEAF = 1
from feature_contract import FEATURE_VERSION, FEATURE_NAMES, reference_from_training

# 峰值搜索参数基于目前的采集条件；距离或硬件变化后，需要检查峰位图并调整。
SMOOTH_BINS = 41                 # 先做 41 bin 平滑，降低单 bin 噪声
REFERENCE_SEARCH_START = 512    # 前峰搜索起点
REFERENCE_SEARCH_END = 30000    # 前峰搜索终点
RETURN_MIN_OFFSET = 2000        # 后续回波至少比前峰晚 2000 bin
RETURN_MAX_OFFSET = 20000       # 后续回波最多比前峰晚 20000 bin
EXCLUDE_END_BINS = 1024         # 排除末端异常峰（当前数据末 bin 明显偏高）
MIN_RETURN_SMOOTHED_HEIGHT = 5.0  # 过弱的后峰直接报错，不勉强分类

# 特征名称和 extract_features() 中数组顺序必须一一对应；预测脚本会检查这一点。


# namedtuple 在旧 Python 中可直接使用，无需额外安装 dataclasses。
TrainingData = namedtuple("TrainingData", "features labels groups frame_numbers settings details")


def feature_settings():
    """模型保存完整的选峰规则，预测时检查，避免参数更改后悄悄错用旧模型。"""
    return {
        "smooth_bins": SMOOTH_BINS,
        "reference_search_start": REFERENCE_SEARCH_START,
        "reference_search_end": REFERENCE_SEARCH_END,
        "return_min_offset": RETURN_MIN_OFFSET,
        "return_max_offset": RETURN_MAX_OFFSET,
        "exclude_end_bins": EXCLUDE_END_BINS,
        "min_return_smoothed_height": MIN_RETURN_SMOOTHED_HEIGHT,
        "smoothing_method": "integer_window_sum_nearest",
    }


def read_frame(path: Path):
    """兼容旧CSV和新的uint32 NPY，二进制加载禁止pickle并限制尺寸。"""
    path = Path(path)
    if path.suffix.lower() == ".npy":
        if path.stat().st_size > 65536 * 4 + 4096:
            raise ValueError("NPY直方图文件过大：{}".format(path))
        counts = np.load(str(path), allow_pickle=False)
        if counts.ndim != 1 or not 30000 <= counts.size <= 65536 or counts.dtype != np.dtype("uint32"):
            raise ValueError("NPY应为30000至65536个uint32计数：{}".format(path))
        return np.arange(counts.size, dtype=np.int64), counts.astype(np.float64)
    data = np.loadtxt(str(path), delimiter=",", skiprows=1, dtype=np.int64, ndmin=2)
    if data.ndim != 2 or data.shape[1] != 2 or data.shape[0] < 30000:
        raise ValueError(f"Invalid TOF CSV shape: {path}: {data.shape}")
    bin_index, counts = data[:, 0], data[:, 1]
    if np.any(counts < 0):
        raise ValueError(f"Negative counts in {path}")
    if not np.all(np.mod(np.diff(bin_index), 65536) == 1):
        raise ValueError(f"Non-contiguous bin_index in {path}")
    return bin_index, counts.astype(np.float64)


def read_raw_frame(path, bin_num):
    """可选的快速二进制读取：只接受 batch 保存的带 28 字节头的单帧。"""
    raw = path.read_bytes()
    if len(raw) != 28 + 8 * bin_num:
        raise ValueError("原始帧长度不正确：{}".format(path))
    dtype = np.dtype([("marker", ">u2"), ("bin", ">u2"), ("count", ">u4")])
    records = np.frombuffer(raw, dtype=dtype, offset=28)
    if not np.all(records["marker"] == 65535):
        raise ValueError("原始帧记录标记不正确：{}".format(path))
    bins = records["bin"].astype(np.int64)
    if not np.all(np.mod(np.diff(bins), 65536) == 1):
        raise ValueError("原始帧 bin 不连续：{}".format(path))
    return bins, records["count"].astype(np.float64)


def _area(values: np.ndarray, center: int, radius: int) -> float:
    """计算峰中心左右 radius 个 bin 范围内的计数和。"""
    return float(values[center - radius : center + radius + 1].sum())


def smooth_histogram(counts):
    """41 点 nearest 平滑：整数滑动和跨平台一致，最终显示峰高时再除以 41。

    TDC 计数为 uint32，当前 65536 bin 的前缀和在 uint64 范围内。
    半高比较使用滑动和，避免不同 scipy 版本在临界点舍入出不同宽度。
    """
    values = np.asarray(counts)
    if SMOOTH_BINS < 1 or SMOOTH_BINS % 2 == 0:
        raise ValueError("平滑窗口必须为正奇数")
    if values.ndim != 1 or np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("直方图必须是一维、有限且非负的计数")
    if np.any(values > 4294967295) or np.any(values != np.floor(values)):
        raise ValueError("直方图应为 uint32 范围内的整数计数")
    radius = SMOOTH_BINS // 2
    padded = np.pad(values.astype(np.uint64), (radius, radius), mode="edge")
    prefix = np.concatenate((np.zeros(1, dtype=np.uint64), np.cumsum(padded, dtype=np.uint64)))
    sums = prefix[SMOOTH_BINS:] - prefix[:-SMOOTH_BINS]
    return sums.astype(np.float64) / SMOOTH_BINS, sums


def locate_histogram(counts: np.ndarray, precomputed=None):
    """定位前后峰并返回平滑数组；PS粗测距与8维特征提取共用规则。"""
    if counts.size < 30000:
        raise ValueError("Expected a full histogram with at least 30000 bins")

    # 前峰不属于目标反射，只用来确定后峰的搜索起点、做强度归一化。
    smoothed, window_sums = smooth_histogram(counts) if precomputed is None else precomputed
    ref_end = min(REFERENCE_SEARCH_END, counts.size - EXCLUDE_END_BINS)
    reference = int(np.argmax(window_sums[REFERENCE_SEARCH_START:ref_end]) + REFERENCE_SEARCH_START)
    return_start = reference + RETURN_MIN_OFFSET
    return_end = min(reference + RETURN_MAX_OFFSET, counts.size - EXCLUDE_END_BINS)
    if return_start + 700 >= return_end or reference < 400:
        raise ValueError("Histogram does not leave room for a later return peak")
    target = int(np.argmax(window_sums[return_start:return_end]) + return_start)
    if target < 400 or target + 700 >= counts.size:
        raise ValueError("Return peak too close to the histogram edge")
    if smoothed[target] < MIN_RETURN_SMOOTHED_HEIGHT:
        raise ValueError(f"Return peak too weak: smoothed height {smoothed[target]:.2f}")

    return smoothed, window_sums, reference, target


def extract_features(counts: np.ndarray):
    """提取固定8维特征；保持既有PS/PL数值定义。"""
    smoothed, window_sums, reference, target = locate_histogram(counts)

    # 后峰面积与前峰面积之比可减少激光功率波动的影响；
    # 面积、宽度、前后沿比例描述真实回波的形状。
    ref_area = _area(counts, reference, 150)
    if ref_area <= 0:
        raise ValueError("Reference peak has zero area")
    area_150 = _area(counts, target, 150)
    area_350 = _area(counts, target, 350)
    core = _area(counts, target, 50)
    head = float(counts[target - 250 : target - 50].sum())
    tail = float(counts[target + 51 : target + 251].sum())
    local_sums = window_sums[target - 500 : target + 501]
    above_half = np.flatnonzero(2 * local_sums >= window_sums[target])
    half_width = float(above_half[-1] - above_half[0] + 1) if above_half.size else 0.0
    weighted_counts = counts[target - 350 : target + 351]
    relative_bins = np.arange(-350, 351, dtype=np.float64)
    weighted_mean = float(np.dot(relative_bins, weighted_counts) / max(area_350, 1.0))
    weighted_sigma = float(
        np.sqrt(np.dot((relative_bins - weighted_mean) ** 2, weighted_counts) / max(area_350, 1.0))
    )
    peak = float(smoothed[target])
    # 顺序与 FEATURE_NAMES 一致：两个面积比、峰高比、核心占比、尾/前沿比、
    # 半高宽、加权宽度、峰高/面积。
    features = np.array(
        [
            area_150 / ref_area,
            area_350 / ref_area,
            peak / max(float(smoothed[reference]), 1.0),
            core / max(area_350, 1.0),
            tail / max(head, 1.0),
            half_width,
            weighted_sigma,
            peak / max(area_350, 1.0),
            float(target),  # 第9维先保留峰bin；模型边界再减去训练时保存的Fe基线。
        ],
        dtype=np.float64,
    )
    detail = {
        "reference_bin": reference,
        "return_bin": target,
        "return_offset_bins": target - reference,
        "return_area_350": int(area_350),
        "return_smoothed_height": round(peak, 2),
    }
    return features, detail


def discover_frames(dataset: Path, run_keys=None):
    """从每次采集的 manifest.csv 找到成功保存的逐帧 CSV。"""
    from data_catalog import collection_manifests
    from acquisition_metadata import material_row
    frames = []
    selected = None if run_keys is None else set(run_keys)
    if selected is not None and not selected:
        raise ValueError("请至少选择一个采集批次")
    found = set()
    for manifest in collection_manifests(dataset):
        key = manifest.parent.parent.name + "/" + manifest.parent.name
        if selected is not None and key not in selected:
            continue
        found.add(key)
        with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if not material_row(row):
                    continue
                frame_path = (manifest.parent / row["csv_path"].replace("\\", "/")).resolve()
                try:
                    frame_path.relative_to(manifest.parent.resolve())
                except ValueError:
                    raise ValueError(f"Frame path outside run directory: {frame_path}")
                row = dict(row, _run_key=key)
                frames.append((frame_path, row))
    if selected is not None and selected - found:
        raise ValueError("选定批次已不存在：{}".format(sorted(selected - found)))
    if not frames:
        raise ValueError(f"没有可训练的已标注帧，请先采集并填写材质编号：{dataset}")
    return frames


def holdout_indices(
    labels: np.ndarray, groups: np.ndarray, frame_numbers: np.ndarray
):
    """能按不同实物划分就按实物划分，否则只用末尾帧做诊断。"""
    test_mask = np.zeros(len(labels), dtype=bool)
    specimens_per_class = {label: sorted(set(groups[labels == label])) for label in sorted(set(labels))}
    if all(len(specimens) >= 2 for specimens in specimens_per_class.values()):
        # 每种材质都有多件实物时，测试集中每类放一件未参与训练的实物。
        for label, specimens in specimens_per_class.items():
            test_mask |= (labels == label) & (groups == specimens[-1])
        method = "held-out physical specimen per class"
    else:
        # 目前每类只有一件实物：这种验证不能代表新实物的泛化能力。
        for label in sorted(set(labels)):
            class_indices = np.flatnonzero(labels == label)
            ordered = class_indices[np.argsort(frame_numbers[class_indices], kind="mergesort")]
            test_count = max(1, int(np.ceil(len(ordered) * 0.2)))
            test_mask[ordered[-test_count:]] = True
        method = "last 20% frames per class; same physical specimens, diagnostic only"
    train_idx = np.flatnonzero(~test_mask)
    test_idx = np.flatnonzero(test_mask)
    if len(train_idx) == 0 or len(test_idx) == 0:
        raise ValueError("Not enough frames for a train/test diagnostic split")
    return train_idx, test_idx, method


def save_training_figures(
    model_path: Path, report: dict, X: np.ndarray,
    labels: np.ndarray, details: list, model, prefer_raw=False,
):
    """统一报告风格；绘图模块按需加载，训练与推理参数保持原有定义。"""
    from training_figures import save_figures
    return save_figures(model_path, report, X, labels, details, read_frame,
                        smooth_histogram, read_raw_frame, prefer_raw)


def load_training_data(dataset: Path, prefer_raw=False, run_keys=None) -> TrainingData:
    """校验所有帧并提取特征；训练和验证共用这份数据。"""
    frames = discover_frames(dataset, run_keys)
    X, labels, groups, frame_numbers, settings, details = [], [], [], [], set(), []
    configs = {}
    for number, (frame_path, row) in enumerate(frames, 1):
        raw_path = frame_path.parents[1] / row.get("raw_path", "")
        if prefer_raw and raw_path.is_file():
            raw_path.resolve().relative_to(frame_path.parents[1].resolve())
            _, counts = read_raw_frame(raw_path, int(row["bin_num"]))
        else:
            _, counts = read_frame(frame_path)
        if counts.size != int(row["bin_num"]):
            raise ValueError(f"BIN_NUM mismatch: {frame_path}")
        if int(counts.sum()) != int(row["total_counts"]):
            raise ValueError(f"Total-count mismatch: {frame_path}")
        settings.add((int(row["bin_num"]), int(float(row["bin_width_ps"])), int(float(row["trig_num"]))))
        features, detail = extract_features(counts)
        from acquisition_metadata import parse_distance, timing_signature
        if row['_run_key'] not in configs:
            config_path = dataset / Path(row['_run_key']).name / 'config.json'
            configs[row['_run_key']] = json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
        row = dict(row, distance_cm=parse_distance(row.get('distance_cm')),
                   _timing_signature=timing_signature(configs[row['_run_key']]))
        X.append(features)
        labels.append(row["material_id"])
        groups.append(f'{row["material_id"]}:{row["specimen_id"]}')
        frame_numbers.append(int(row["frame_index"]))
        details.append((frame_path, row, detail))
        if number % 20 == 0 or number == len(frames):
            print("已读取并提取特征：{}/{} 帧".format(number, len(frames)), flush=True)
    if len(settings) != 1:
        raise ValueError(f"Acquisition settings differ between runs: {sorted(settings)}")
    return TrainingData(
        features=np.vstack(X),
        labels=np.asarray(labels),
        groups=np.asarray(groups),
        frame_numbers=np.asarray(frame_numbers),
        settings=next(iter(settings)),
        details=details,
    )


def classification_summary(truth, prediction, classes):
    """直接由混淆矩阵计算报告，兼容不支持 output_dict 的旧 sklearn。"""
    matrix = confusion_matrix(truth, prediction, labels=classes)
    rows = {}
    for i, name in enumerate(classes):
        tp = float(matrix[i, i])
        predicted, support = float(matrix[:, i].sum()), int(matrix[i].sum())
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows[str(name)] = {"precision": precision, "recall": recall, "f1-score": f1, "support": support}
    rows["accuracy"] = float(accuracy_score(truth, prediction))
    return rows


def portable_forest(model, metadata):
    """导出纯 JSON 节点表，用于电脑/旧 PYNQ 间交换，不跨版本反序列化 sklearn。"""
    payload = dict(metadata)
    payload["format"] = "tdc_random_forest_v1"
    payload["class_names"] = [str(name) for name in model.classes_]
    payload["trees"] = []
    for estimator in estimators(model):
        tree = estimator.tree_
        values = tree.value[:, 0, :].astype(np.float64)
        totals = values.sum(axis=1, keepdims=True)
        probabilities = values / np.maximum(totals, 1e-300)
        payload["trees"].append({
            "left": tree.children_left.tolist(), "right": tree.children_right.tolist(),
            "feature": tree.feature.tolist(), "threshold": tree.threshold.tolist(),
            "probabilities": probabilities.tolist(),
        })
    return payload


def classifier_options(algorithm, trees, max_depth):
    """只使用板端旧版 sklearn 已有参数，限制单线程降低训练峰值资源。"""
    if algorithm not in ALGORITHMS:
        raise ValueError("不支持的训练算法")
    if algorithm == "tiny_cnn":
        return dict(epochs=250, learning_rate=0.003, alpha=0.001, batch_size=32, random_state=42)
    if algorithm == "mlp":
        return dict(hidden_layer_sizes=(32,16), activation="relu", solver="lbfgs",
                    alpha=0.1, max_iter=2000, tol=1e-4, random_state=42)
    options = dict(max_depth=max_depth, min_samples_leaf=FOREST_MIN_SAMPLES_LEAF,
                   class_weight="balanced", random_state=42)
    if algorithm != "decision_tree":
        options.update(n_estimators=trees, max_features="sqrt", n_jobs=1)
    return options


def make_classifier(algorithm, options):
    if algorithm == 'tiny_cnn':
        from cnn_models import TinyCNNClassifier
        return TinyCNNClassifier(**options)
    if algorithm == "mlp":
        classifier = MLPClassifier(**options)
        return Pipeline([("cast",FunctionTransformer(cast_features, validate=False)),
                         ("scale",StandardScaler()), ("classifier",classifier)])
    return {"random_forest": RandomForestClassifier, "decision_tree": DecisionTreeClassifier}[algorithm](**options)


def fit_classifier(model, samples, labels):
    """将优化器未收敛写入报告；有参数输出不代表已达到优化终点。"""
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(samples, labels)
    messages = []
    for notice in notices:
        if issubclass(notice.category, ConvergenceWarning):
            messages.append(str(notice.message))
        else:
            warnings.warn(str(notice.message), notice.category)
    return messages


def train(args: argparse.Namespace):
    """依次完成读取、留出验证、全量训练、保存模型和绘图。"""
    start = time.perf_counter()
    algorithm = getattr(args, "algorithm", "random_forest")
    if algorithm not in ALGORITHMS:
        raise ValueError('该训练算法已停用，请选择随机森林、决策树、小型MLP或小型CNN')
    selected_runs = getattr(args, "run_keys", None)
    if getattr(args, "runs_file", None) is not None:
        selected_runs = json.loads(Path(args.runs_file).read_text(encoding="utf-8"))["run_keys"]
    data = load_training_data(args.dataset.resolve(), getattr(args, "prefer_raw", False), selected_runs)
    X, labels, groups = data.features.copy(), data.labels, data.groups
    if algorithm == 'tiny_cnn':
        from cnn_models import waveform
        waves=[]
        for path,row,detail in data.details:
            _,counts=read_frame(path)
            waves.append(waveform(counts,detail['return_bin']))
        X=np.c_[X,np.asarray(waves)]
    classes = sorted(set(labels))
    if len(classes) < 2:
        raise ValueError("Training requires at least two material classes")
    if any(np.sum(labels == name) < 2 for name in classes):
        raise ValueError("每类至少需要2帧才能同时训练和留出验证，请增加所选批次")
    # 先用留出集评估；随后重新用全部帧训练最终部署模型。
    from training_validation import split_data, tune_dense
    train_idx, test_idx, split_method = split_data(data)
    diagnostic_baseline, _ = reference_from_training(data, train_idx)
    X[:,8] -= diagnostic_baseline
    model_options = classifier_options(algorithm, getattr(args, "trees", FOREST_TREES),
                                      getattr(args, "max_depth", FOREST_MAX_DEPTH))
    tuning = None
    if getattr(args, 'tune', False) and algorithm == 'mlp':
        # 调参仅用训练折，标准化也在内部训练子折拟合。
        model_options, tuning = tune_dense(algorithm, model_options, data, train_idx)
    diagnostic_model = make_classifier(algorithm, model_options)
    diagnostic_warnings = fit_classifier(diagnostic_model, X[train_idx], labels[train_idx])
    prediction = diagnostic_model.predict(X[test_idx])
    from plot_data import holdout_diagnostics, save_plot_data
    diagnostics = holdout_diagnostics(diagnostic_model, X[test_idx], labels[test_idx], algorithm)
    report = {
        "schema_version": 2,
        "model_type": ALGORITHMS[algorithm]["model_type"],
        "algorithm": algorithm,
        "algorithm_name": ALGORITHMS[algorithm]["name"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_id": uuid.uuid4().hex[:12],
        "model_parameters": dict(model_options),
        "tuning": tuning,
        "training_runs": sorted(set(row["_run_key"] for _, row, _ in data.details)),
        "feature_version": FEATURE_VERSION,
        "feature_settings": feature_settings(),
        "timing_reference_bin": reference_from_training(data, range(len(labels)))[0],
        "timing_reference_source": reference_from_training(data, range(len(labels)))[1],
        "diagnostic_timing_reference_bin": diagnostic_baseline,
        "library_versions": {"sklearn": sklearn.__version__, "numpy": np.__version__,
                             "scipy": scipy.__version__, "joblib": joblib.__version__},
        "samples": len(labels),
        "frames_per_material": dict(Counter(labels)),
        "frames_per_illumination":dict(Counter(row.get('illumination') or 'unknown' for _,row,_ in data.details)),
        "holdout_by_illumination":{light:dict(samples=sum((data.details[i][1].get('illumination') or 'unknown')==light for i in test_idx),
             accuracy=float(np.mean(prediction[[j for j,i in enumerate(test_idx) if (data.details[i][1].get('illumination') or 'unknown')==light]]==labels[[i for i in test_idx if (data.details[i][1].get('illumination') or 'unknown')==light]])))
             for light in sorted(set(data.details[i][1].get('illumination') or 'unknown' for i in test_idx))},
        "specimens_per_material": {name: len(set(groups[labels == name])) for name in classes},
        "holdout_method": split_method,
        "holdout_accuracy": float(accuracy_score(labels[test_idx], prediction)),
        "holdout_confusion_labels": classes,
        "holdout_confusion_matrix": confusion_matrix(labels[test_idx], prediction, labels=classes).tolist(),
        "holdout_classification_report": classification_summary(labels[test_idx], prediction, classes),
        "feature_names": FEATURE_NAMES,
        "model_diagnostics": diagnostics,
        "histogram_settings": {"bin_num": data.settings[0], "bin_width_ps": data.settings[1], "trig_num": data.settings[2]},
    }
    if algorithm == 'tiny_cnn':
        baseline_score=float(accuracy_score(labels[test_idx],prediction));drops=[]
        rng=np.random.RandomState(42)
        for j in range(9):
            trials=[]
            for _ in range(5):
                shuffled=X[test_idx].copy();shuffled[:,j]=shuffled[rng.permutation(len(test_idx)),j]
                trials.append(baseline_score-accuracy_score(labels[test_idx],diagnostic_model.predict(shuffled)))
            drops.append(trials)
        report.update(feature_importances=np.mean(drops,axis=1).tolist(),feature_importance_std=np.std(drops,axis=1).tolist(),
                      importance_label='Holdout permutation importance of 9 auxiliary features',
                      cnn_settings=__import__('cnn_models').SPEC)
    elif algorithm == "mlp":
        importance = permutation_importance(diagnostic_model, X[test_idx], labels[test_idx],
                                           n_repeats=5, random_state=42, n_jobs=1)
        report.update(feature_importances=importance.importances_mean.tolist(),
                      feature_importance_std=importance.importances_std.tolist(),
                      importance_label="Holdout permutation importance (accuracy decrease)")
    del diagnostic_model
    gc.collect()
    model = make_classifier(algorithm, model_options)
    X[:,8] += diagnostic_baseline - report['timing_reference_bin']
    final_warnings = fit_classifier(model, X, labels)
    if algorithm == 'tiny_cnn':
        report['cnn_training_loss']=model.loss_curve_
        report['cnn_epochs']=model.n_iter_
    report["optimizer_warnings"] = {"holdout":diagnostic_warnings,"final":final_warnings}
    if diagnostic_warnings or final_warnings:
        print("提示：优化器未完全收敛，参数仍可比对；训练报告已记录警告，请结合独立验证判断效果。",flush=True)
    args.model.parent.mkdir(parents=True, exist_ok=True)
    metadata = {key: report[key] for key in ("schema_version", "model_type", "model_id", "feature_version",
                                            "feature_settings", "library_versions", "feature_names", "timing_reference_bin", "timing_reference_source")}
    metadata["settings"] = list(data.settings)
    temporary = args.model.with_name(args.model.name + ".tmp")
    joblib.dump(dict(metadata, model=model), str(temporary))
    temporary.replace(args.model)
    portable_path = args.model.with_suffix(".portable.json")
    if algorithm == 'tiny_cnn':
        from cnn_models import export_cnn
        portable=export_cnn(model,metadata)
    else:
        portable = export_dense(model, metadata) if algorithm == "mlp" else portable_forest(model, metadata)
    portable_path.write_text(json.dumps(portable, ensure_ascii=False), encoding="utf-8")
    report["tree_count"] = len(portable.get("trees", []))
    report["node_count"] = sum(len(tree["left"]) for tree in portable.get("trees", []))
    if algorithm in ("tiny_cnn", "mlp"):
        from cnn_models import pack_cnn
        report["pl_parameter_bytes"] = int((pack_cnn if algorithm=='tiny_cnn' else pack_dense)(portable).nbytes) if len(classes) <= 64 else 0
        report["pl_compatible"] = len(classes) <= 64 and data.settings[0] == 65536
        report["score_kind"] = portable["score_kind"]
    else:
        report["pl_parameter_bytes"] = (report["tree_count"] + report["node_count"] * (4 + len(classes))) * 8
        report["pl_compatible"] = (len(classes) <= 64 and report["tree_count"] <= 128
                                   and report["node_count"] <= 16384 and model_options["max_depth"] <= 32
                                   and data.settings[0] == 65536)
        report["feature_importances"] = model.feature_importances_.tolist()
        report["feature_importance_std"] = np.std([tree.feature_importances_ for tree in estimators(model)],axis=0).tolist()
        report["importance_label"] = "Impurity importance (tree-to-tree standard deviation)"
    report["pl_model_kind"] = {"tiny_cnn":3,"mlp":2}.get(algorithm,0)
    del portable
    report["class_names"] = [str(name) for name in model.classes_]
    snapshot_started = time.perf_counter()
    save_plot_data(args.model, report, X[:,:9], labels, data.details, read_frame,
                   smooth_histogram, read_raw_frame, prefer_raw=getattr(args, "prefer_raw", False))
    report["plot_snapshot_seconds"] = round(time.perf_counter() - snapshot_started, 3)
    report["training_seconds"] = round(time.perf_counter() - start, 3)
    report_path = args.model.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = args.model.with_suffix(".summary.txt")
    summary_path.write_text("{}模型\n模型编号：{}\n树数：{}\n类别：{}\n验证方式：{}\n验证准确率：{:.1%}\n".format(
        ALGORITHMS[algorithm]["name"], report["model_id"], report["tree_count"], ", ".join(report["class_names"]), split_method,
        report["holdout_accuracy"]), encoding="utf-8")
    peaks_path = args.model.with_suffix(".peaks.csv")
    with peaks_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frame_path", "material_id", "specimen_id", "reference_bin", "return_bin", "return_offset_bins", "return_area_350", "return_smoothed_height"])
        for path, row, detail in data.details:
            writer.writerow([str(path), row["material_id"], row["specimen_id"], *detail.values()])
    figure_paths = [] if getattr(args, "no_figures", False) else save_training_figures(args.model, report, X, labels, data.details, model, prefer_raw=getattr(args, "prefer_raw", False))
    # 清理旧单树的展示产物，只处理相同模型前缀对应的两份文件。
    for suffix in (".rules.txt", ".tree.png"):
        obsolete = args.model.with_suffix(suffix)
        if obsolete.is_file():
            obsolete.unlink()
    print(f"训练完成，共 {len(labels)} 帧：{dict(Counter(labels))}")
    print(f"验证方式：{split_method}；准确率={report['holdout_accuracy']:.3f}")
    print("混淆矩阵：行是真实材质，列是预测材质；类别顺序：", classes)
    print(np.asarray(report["holdout_confusion_matrix"]))
    print("模型类型：{}；树数={}，类别数={}；PL参数约{}字节".format(ALGORITHMS[algorithm]["name"], report["tree_count"], len(classes), report["pl_parameter_bytes"]))
    print(f"模型：{args.model}\n便携模型：{portable_path}\n报告：{report_path}\n模型摘要：{summary_path}\n峰位核对表：{peaks_path}")
    print("结果图：\n" + "\n".join(str(path) for path in figure_paths))
    if "diagnostic only" in split_method:
        print("提示：每类只有一件实物；此准确率不能代表新实物的识别能力。")
    return figure_paths


def main() -> None:
    """直接运行即可训练并打开图表；--no-open 只保存图表。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--algorithm", choices=sorted(ALGORITHMS), default="random_forest", help="模型算法")
    parser.add_argument('--tune', action='store_true', help='MLP仅在训练折内轻量调参')
    parser.add_argument("--runs-file", type=Path, help="批次清单JSON，内容为run_keys列表；省略则使用全部已标注批次")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--no-open", action="store_true", help="只保存结果图，不自动打开")
    parser.add_argument("--no-figures", action="store_true", help="仅保存模型和报告，不生成 PNG")
    parser.add_argument("--prefer-raw", action="store_true", help="优先读取已校验格式的 .dat，适合板端加速读数据")
    parser.add_argument("--trees", type=int, default=FOREST_TREES, help="森林树数")
    parser.add_argument("--max-depth", type=int, default=FOREST_MAX_DEPTH, help="每棵树的最大深度")
    args = parser.parse_args()
    if args.trees < 1 or args.max_depth < 1:
        parser.error("树数和深度必须为正整数")
    figures = train(args)
    if args.model.resolve() == DEFAULT_MODEL.resolve():
        # 默认一键训练也进入版本库；网页使用自定义暂存路径，由业务层归档。
        from model_registry import ModelRegistry
        registry = ModelRegistry(DEFAULT_MODEL.parent)
        registry.register(args.model.parent)
        model_id = json.loads(args.model.with_suffix(".report.json").read_text(encoding="utf-8"))["model_id"]
        registry.activate(model_id)
        print("已归档并启用模型版本：{}".format(model_id))
    if not args.no_open:
        if os.name == "nt":
            for figure in figures:
                os.startfile(figure)
        else:
            print("结果图已保存，请打开上面列出的 PNG 文件查看。")


if __name__ == "__main__":
    main()
