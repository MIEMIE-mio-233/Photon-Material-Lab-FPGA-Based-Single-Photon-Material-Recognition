"""统一采集数据目录，按批次清单索引。"""
from pathlib import Path


def collection_manifests(dataset):
    return sorted(Path(dataset).glob("run_*/manifest.csv"))


def has_material_label(value):
    """未填写材质时仍保存原始帧，但不能把缺失标签训练为一种材料。"""
    return str(value or "").strip().lower() not in ("", "unlabeled")
