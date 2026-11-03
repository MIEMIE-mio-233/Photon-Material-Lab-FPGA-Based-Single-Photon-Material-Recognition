"""MLP便携参数与统一评分，只依赖NumPy，供PC、PYNQ及PL驱动共用。

匹配版本的8/9维特征先取float32，再用double做标准化，匹配PL的特征边界。
"""
import numpy as np

FORMAT = "tdc_dense_classifier_v1"


def cast_features(samples):
    """保留PL特征的float32舍入，再提升到double计算，避免跨端预处理不同。"""
    return np.asarray(samples, dtype=np.float32).astype(np.float64)


def softmax(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] < 1 or not np.isfinite(values).all():
        raise ValueError("分类分数必须是有限的二维数值矩阵")
    shifted = values - np.max(values, axis=1, keepdims=True)
    result = np.exp(shifted)
    return result / result.sum(axis=1, keepdims=True)


def class_scores(model, samples):
    """原生模型使用predict_proba。"""
    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(samples)
        if not np.isfinite(scores).all() or (scores < 0).any() or not np.allclose(scores.sum(axis=1),1.0):
            raise ValueError("分类概率无效，禁止把空结果识别为第一类")
        return scores
    raise ValueError('模型没有概率输出接口')


def export_dense(model, metadata):
    scaler, classifier = model.named_steps["scale"], model.named_steps["classifier"]
    payload = dict(metadata, format=FORMAT,
                   class_names=[str(item) for item in classifier.classes_],
                   mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist())
    h1, h2 = classifier.hidden_layer_sizes
    if not 1 <= h1 <= 32 or not 1 <= h2 <= 16:
        raise ValueError('当前PL支持两层隐藏层，最大32/16')
    out = classifier.coefs_[-1].shape[1]
    inputs = len(scaler.mean_)
    padded = [np.zeros((inputs, 32)), np.zeros((32, 16)), np.zeros((16, out))]
    padded[0][:, :h1] = classifier.coefs_[0]
    padded[1][:h1, :h2] = classifier.coefs_[1]
    padded[2][:h2, :] = classifier.coefs_[2]
    bias = [np.zeros(32), np.zeros(16), classifier.intercepts_[2].copy()]
    bias[0][:h1] = classifier.intercepts_[0]
    bias[1][:h2] = classifier.intercepts_[1]
    payload.update(weights=[item.tolist() for item in padded], bias=[item.tolist() for item in bias], original_hidden_layer_sizes=[h1, h2], activation='relu', output_activation=classifier.out_activation_, score_kind='model_probability')
    # 导出时立即执行尺寸/有限值检查，损坏参数不会被归档或上传硬件。
    PortableDense(payload)
    return payload


class PortableDense:
    """按固定类别顺序计算，不反序列化来自另一sklearn版本的对象。"""
    def __init__(self, payload):
        if payload.get("format") != FORMAT:
            raise ValueError("不是支持的MLP参数格式")
        self.payload = payload
        self.classes_ = np.asarray(payload["class_names"])
        if len(self.classes_) < 2 or len(set(self.classes_)) != len(self.classes_):
            raise ValueError("模型类别必须唯一且至少两类")
        self.mean, self.scale = np.asarray(payload["mean"], dtype=float), np.asarray(payload["scale"], dtype=float)
        self.inputs=len(self.mean)
        if self.inputs not in (8,9) or self.mean.shape != (self.inputs,) or self.scale.shape != (self.inputs,) or (self.scale <= 0).any():
            raise ValueError("标准化参数必须为匹配的8/9维且缩放大于0")
        arrays = [self.mean, self.scale]
        self.kind = payload["model_type"]
        if self.kind == 'MLPClassifier':
            self.weights = [np.asarray(item, dtype=float) for item in payload['weights']]
            self.bias = [np.asarray(item, dtype=float) for item in payload['bias']]
            out = 1 if len(self.classes_) == 2 else len(self.classes_)
            shapes = [(self.inputs, 32), (32, 16), (16, out)]
            if len(self.weights) != 3 or len(self.bias) != 3 or any((w.shape != shape or b.shape != (shape[1],) for w, b, shape in zip(self.weights, self.bias, shapes))):
                raise ValueError('MLP结构必须为8→32→16→类别输出')
            if payload.get('activation') != 'relu' or payload.get('output_activation') != ('logistic' if out == 1 else 'softmax'):
                raise ValueError('MLP激活函数不匹配')
            arrays.extend(self.weights + self.bias)
        else:
            raise ValueError('不支持的乘加模型')
        if not all(np.isfinite(item).all() for item in arrays):
            raise ValueError("模型参数含NaN或无穷数")

    def decision_function(self, samples):
        values = (cast_features(samples) - self.mean) / self.scale
        for index, (weights, bias) in enumerate(zip(self.weights, self.bias)):
            values = np.dot(values, weights) + bias
            if index < 2:
                values = np.maximum(values, 0)
        if values.shape[1] == 1:
            values = np.column_stack([np.zeros(len(values)), values[:, 0]])
        return values

    def predict_proba(self, samples):
        return softmax(self.decision_function(samples))

    def predict(self, samples):
        return self.classes_[np.argmax(self.decision_function(samples), axis=1)]


def pack_dense(payload):
    """HLS节点表之外的紧凑double表；MLP与CNN共享乘加硬件。"""
    model = PortableDense(payload)
    if len(model.classes_) > 64:
        raise ValueError("PL最多支持64类")
    header = [model.inputs, 32, 16, model.weights[-1].shape[1]]
    params = [item for pair in zip(model.weights, model.bias) for item in pair]
    return np.concatenate([np.asarray(header,dtype=float), model.mean, model.scale] + [item.ravel() for item in params])
