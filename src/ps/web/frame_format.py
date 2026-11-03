"""历史UDP帧格式兼容读取；真实采集使用pl_runtime的内部AXI接口。"""
import numpy as np

class Cancelled(Exception):
    """用户停止任务。"""


def decode_frame(raw, bin_num):
    """只接受完整且序号连续的帧；丢包、乱序或重复不能混进训练集。"""
    if len(raw) != 28 + 8 * bin_num:
        raise ValueError("帧长错误：收到 {} 字节".format(len(raw)))
    records = np.frombuffer(raw, dtype=np.dtype([("marker", ">u2"), ("bin", ">u2"), ("count", ">u4")]), offset=28)
    if not np.all(records["marker"] == 65535):
        raise ValueError("帧内 FF FF 标记错误")
    bins = records["bin"].astype(np.int64)
    if bins[0] not in (0, 1) or not np.all(np.mod(np.diff(bins), 65536) == 1):
        raise ValueError("bin 序号不连续：可能丢包、重复或乱序")
    return bins, records["count"].astype(np.float64)

