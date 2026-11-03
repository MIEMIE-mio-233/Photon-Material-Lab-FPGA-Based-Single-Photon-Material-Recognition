# P4 Python3.8 / aarch64案例

已部署案例：XCZU4EV、PYNQ2.7.0、Python3.8.2、aarch64，基础NumPy1.20.3、SciPy1.3.3，新增sklearn0.24.2、joblib1.1.1、threadpoolctl3.1.0。wheel适配Python3.8/aarch64。

assets/p4-py38-aarch64-packages.json含这三个实测wheel的PyPI地址和SHA256，均与工程已有文件逐个核对。可在联网电脑下载（不安装）：

```bash
python scripts/fetch_wheels.py assets/p4-py38-aarch64-packages.json --output downloaded_wheels
```

包来源与哈希保存在清单，计算检查记录对应既有P4环境。

在另一块兼容镜像上复用时，先probe实际Python ABI/架构和基础库；以镜像PYNQ解释器创建独立venv并继承基础依赖。原PYNQ位于另一个venv时，--system-site-packages可能不包含它的site-packages，应先用原解释器sysconfig.get_paths()["purelib"]找出位置，再在新环境.pth显式加入，保留系统PYNQ/NumPy/SciPy。

确认清单与目标相符后，针对新环境执行pip install --no-index --no-deps --find-links <wheel_dir> scikit-learn==0.24.2 joblib==1.1.1 threadpoolctl==3.1.0。基础依赖与ABI检查通过后使用--no-deps。

在该解释器运行verify_ml_stack.py --require-pynq；若需Notebook，再注册独立内核并使用verify_pynq_kernel.py实际验证。独立环境注册新内核，保留镜像默认内核。
