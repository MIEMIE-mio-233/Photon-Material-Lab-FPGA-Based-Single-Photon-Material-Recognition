"""训练入口和参数协议；仅提供当前四种模型。"""

ALGORITHMS = {
    "random_forest": {"name": "随机森林", "model_type": "RandomForestClassifier"},
    "decision_tree": {"name": "决策树", "model_type": "DecisionTreeClassifier"},
    "tiny_cnn": {"name": "小型CNN", "model_type": "TinyCNNClassifier"},
    "mlp": {"name": "小型MLP", "model_type": "MLPClassifier"},
}
LEGACY_ALGORITHMS = {}


def algorithm_info(key):
    return (ALGORITHMS if key in ALGORITHMS else LEGACY_ALGORITHMS)[key]


def algorithm_key(model_type):
    for key, item in dict(ALGORITHMS, **LEGACY_ALGORITHMS).items():
        if item["model_type"] == model_type:
            return key
    raise ValueError("不支持的模型类型：{}".format(model_type))


def estimators(model):
    """单棵决策树也按一棵树的森林导出，保持 PL 数据格式不变。"""
    return list(model.estimators_) if hasattr(model, "estimators_") else [model]
