"""读取一帧 TDC 直方图 CSV/NPY，用随机森林识别；支持连续输入和 MATLAB JSON 调用。

双击「一键识别.bat」后输入文件名，或运行：
python predict_material.py "dataset/run_.../frame_0001.csv"
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from model_algorithms import algorithm_info, algorithm_key
from dense_models import PortableDense, FORMAT as DENSE_FORMAT, class_scores
from feature_contract import feature_count, model_features
from cnn_models import PortableCNN, TinyCNNClassifier, FORMAT as CNN_FORMAT

from train_material import (
    DEFAULT_DATASET,
    DEFAULT_MODEL,
    FEATURE_NAMES,
    FEATURE_VERSION,
    SCRIPT_DIR,
    extract_features,
    feature_settings,
    read_frame,
)


class PortableForest:
    """纯节点表推理，匹配 sklearn 的 float32 输入与各树叶概率平均规则。"""

    def __init__(self, payload):
        if payload.get("format") != "tdc_random_forest_v1":
            raise ValueError("不是本项目的便携随机森林文件")
        self.classes_ = np.asarray(payload["class_names"])
        self.trees = payload["trees"]
        if not self.trees or not len(self.classes_):
            raise ValueError("森林或类别列表为空")
        for tree in self.trees:
            count = len(tree["left"])
            if not count or any(len(tree[key]) != count for key in ("right", "feature", "threshold", "probabilities")):
                raise ValueError("便携森林节点数组长度不一致")
            for i in range(count):
                if len(tree["probabilities"][i]) != len(self.classes_):
                    raise ValueError("叶概率的类别数与模型不一致")
                if tree["left"][i] != -1:
                    if not 0 <= tree["feature"][i] < feature_count(payload):
                        raise ValueError("节点特征编号越界")
                    if not all(0 <= tree[key][i] < count for key in ("left", "right")):
                        raise ValueError("节点子树编号越界")

    def predict_proba(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        output = np.zeros((len(samples), len(self.classes_)), dtype=np.float64)
        for row, sample in enumerate(samples):
            for tree in self.trees:
                node = 0
                for _ in range(len(tree["left"])):
                    if tree["left"][node] == -1:
                        output[row] += np.asarray(tree["probabilities"][node], dtype=np.float64)
                        break
                    value = float(sample[tree["feature"][node]])
                    key = "left" if value <= tree["threshold"][node] else "right"
                    node = tree[key][node]
                else:
                    raise ValueError("便携森林出现循环节点")
        return output / len(self.trees)

    def predict(self, samples):
        return self.classes_[np.argmax(self.predict_proba(samples), axis=1)]


def load_model(model_path, backend="auto"):
    """同版本用 joblib，跨 sklearn 版本自动使用同一前缀的便携 JSON。"""
    model_path = Path(model_path)
    portable_path = model_path if model_path.suffix.lower() == ".json" else model_path.with_suffix(".portable.json")
    report_path = model_path.with_suffix(".report.json")
    use_portable = backend == "portable" or model_path.suffix.lower() == ".json"
    report = None
    # 已停用的距离包只能浏览/下载，不再通过命令行自动路由子模型。
    if portable_path.is_file():
        header = json.loads(portable_path.read_text(encoding='utf-8'))
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        trained_version = report.get("library_versions", {}).get("sklearn")
        if backend == "auto" and trained_version and trained_version != sklearn.__version__:
            use_portable = True
    if use_portable:
        if not portable_path.is_file():
            raise FileNotFoundError("找不到便携模型：{}；请重新一键训练".format(portable_path))
        artifact = json.loads(portable_path.read_text(encoding="utf-8"))
        artifact["model"] = PortableCNN(artifact) if artifact.get('format') == CNN_FORMAT else PortableDense(artifact) if artifact.get("format") == DENSE_FORMAT else PortableForest(artifact)
        artifact["backend"] = "portable-json"
    else:
        if not model_path.is_file():
            raise FileNotFoundError("找不到训练模型：{}；请先一键训练".format(model_path))
        if backend == "sklearn" and report:
            trained_version = report.get("library_versions", {}).get("sklearn")
            if trained_version and trained_version != sklearn.__version__:
                raise ValueError("sklearn 版本不同，请使用 --backend auto 或 portable")
        artifact = joblib.load(str(model_path))
        from sklearn.pipeline import Pipeline
        from sklearn.neural_network import MLPClassifier
        native = artifact.get("model")
        classifier = native.named_steps.get("classifier") if isinstance(native, Pipeline) else native
        if not isinstance(classifier, (RandomForestClassifier, DecisionTreeClassifier, MLPClassifier, TinyCNNClassifier)):
            raise ValueError("当前模型不是支持的树分类器")
        if type(classifier).__name__ != artifact.get("model_type", "RandomForestClassifier"):
            raise ValueError("模型实际类型与元数据不一致")
        artifact["backend"] = "sklearn"
    feature_count(artifact)
    if artifact.get("feature_settings") != feature_settings():
        raise ValueError("选峰参数与模型不一致，请使用匹配参数或重新训练")
    if report and artifact.get("model_id") != report.get("model_id"):
        raise ValueError("模型与训练报告编号不同，请重新训练或完整复制模型文件")
    return artifact


def find_frame(filename: str, interactive: bool) -> Path:
    """接受完整路径、相对路径或文件名；同名文件多于一个时让用户选择。"""
    filename = filename.strip().strip('"').strip("'")
    if not filename:
        raise ValueError("没有输入文件名")
    if not filename.lower().endswith((".csv", ".npy")):
        raise ValueError("请输入一帧 .csv 或 .npy 直方图文件")

    entered_path = Path(filename).expanduser()
    for candidate in (entered_path, SCRIPT_DIR / entered_path, DEFAULT_DATASET / entered_path):
        if candidate.is_file():
            return candidate.resolve()

    # 只输入 frame_0001.csv 时，去所有采集目录中查找。
    if entered_path.name == filename:
        matches = sorted(DEFAULT_DATASET.rglob(filename))
        if len(matches) == 1:
            return matches[0].resolve()
        if len(matches) > 1:
            if not interactive:
                raise ValueError(f"找到 {len(matches)} 个同名文件，请传入带目录的路径")
            print(f"找到 {len(matches)} 个同名文件，请选择要识别的采集目录：")
            for number, path in enumerate(matches, start=1):
                print(f"  {number}. {path.relative_to(DEFAULT_DATASET)}")
            choice = input("输入序号：").strip()
            if not choice.isdigit() or not 1 <= int(choice) <= len(matches):
                raise ValueError("序号无效")
            return matches[int(choice) - 1].resolve()

    raise FileNotFoundError(f"找不到数据文件：{filename}")


def predict(frame_path: Path, model_path: Path, artifact=None, backend="auto") -> dict:
    """返回材质、前后峰、森林参考分数；artifact 可复用，连续识别只加载一次。"""
    if not frame_path.is_file():
        raise FileNotFoundError(f"找不到直方图 CSV/NPY：{frame_path}")
    if artifact is None:
        artifact = load_model(model_path, backend)
    _, counts = read_frame(frame_path)
    if counts.size != artifact["settings"][0]:
        raise ValueError(f"该帧有 {counts.size} 个 bin，模型要求 {artifact['settings'][0]} 个")

    # 与训练时调用同一个函数，保证前峰排除规则和特征计算完全一致。
    features, peaks = extract_features(counts)
    parent_id = artifact['model_id']
    parent_type = artifact.get('model_type','RandomForestClassifier')
    model = artifact["model"]
    sample = model_sample(artifact,counts,features,peaks)
    label = str(model.predict(sample)[0])
    scores = class_scores(model, sample)[0]
    return {
        "file": str(frame_path),
        "material": label,
        "reference_bin": peaks["reference_bin"],
        "return_bin": peaks["return_bin"],
        "peak_shift_bins": float(features[8]-artifact.get('timing_reference_bin',0)) if feature_count(artifact)==9 else None,
        "class_scores": {str(name): round(float(score), 4) for name, score in zip(model.classes_, scores)},
        "model_type": parent_type,
        "model_id": parent_id,
        "backend": artifact["backend"],
        "score_kind": "model_probability",
    }


def model_sample(artifact,counts,features,peaks):
    """统一PC、网页和MATLAB入口；CNN多取波形，树/MLP只取统计特征。"""
    values=model_features(features,artifact)
    if artifact.get('model_type')=='TinyCNNClassifier':
        from cnn_models import sample
        values=sample(counts,values,peaks['return_bin'])
    return values.reshape(1,-1)


def print_result(result: dict, as_json: bool = False) -> None:
    """显示识别结果；JSON 模式供其他程序解析。"""
    if as_json:
        # ASCII JSON 避免 Windows/MATLAB/SSH 的终端编码差异，解析后仍是原中文。
        print(json.dumps(result, ensure_ascii=True))
        return
    print(f"数据文件：{result['file']}")
    print(f"识别结果：{result['material']}")
    name = algorithm_info(algorithm_key(result["model_type"]))["name"]
    print("模型：{}；编号={}；推理方式={}".format(name, result["model_id"], result["backend"]))
    print(f"实际回波：bin {result['return_bin']}（前峰：bin {result['reference_bin']}）")
    print("各类别分数：" + "，".join(
        f"{name}={score:.4f}" for name, score in result["class_scores"].items()
    ))


def main() -> int:
    """无参数时连续识别；带路径时只识别一帧，兼容命令行调用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame_csv", nargs="?", help="一帧 frame_*.csv/.npy 直方图文件；省略时手动输入")
    parser.add_argument("--model", type=Path, help="指定模型路径；省略时使用版本库的当前模型")
    parser.add_argument("--json", action="store_true", help="标准输出仅包含 JSON，兼容 MATLAB")
    parser.add_argument("--backend", choices=["auto", "sklearn", "portable"], default="auto", help="默认自动处理电脑/板端 sklearn 版本差异")
    args = parser.parse_args()
    interactive = args.frame_csv is None
    if args.json and interactive:
        parser.error("--json 需要同时提供直方图路径")
    if args.model is not None:
        model_path = args.model.resolve()
    elif (DEFAULT_MODEL.parent / "active.json").is_file():
        from model_registry import ModelRegistry
        model_path = ModelRegistry(DEFAULT_MODEL.parent).path()
    else:
        model_path = DEFAULT_MODEL.resolve()

    if not interactive:
        try:
            frame_path = find_frame(args.frame_csv, interactive=False)
            print_result(predict(frame_path, model_path, backend=args.backend), as_json=args.json)
            return 0
        except (OSError, ValueError) as error:
            print(f"识别失败：{error}", file=sys.stderr)
            return 1

    print("可连续输入单帧 CSV/NPY 的完整路径、相对路径或文件名；也可将文件拖入窗口。")
    print("输入 q 或直接按回车退出。")
    try:
        artifact = load_model(model_path, args.backend)
    except (OSError, ValueError) as error:
        print("模型加载失败：{}".format(error))
        return 1
    while True:
        try:
            filename = input("数据文件名：").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if not filename or filename.lower() in {"q", "quit", "exit"}:
            return 0
        try:
            frame_path = find_frame(filename, interactive=True)
            print_result(predict(frame_path, model_path, artifact=artifact))
        except (OSError, ValueError) as error:
            print(f"识别失败：{error}")
        print()  # 分隔两次结果，方便连续查看。


if __name__ == "__main__":
    raise SystemExit(main())
