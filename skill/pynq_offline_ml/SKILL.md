---
name: pynq-offline-ml
description: 在可启动PYNQ上安装匹配ARM和Python ABI的离线机器学习依赖，验证独立解释器及实际Jupyter内核。
---

# PYNQ离线机器学习环境

在项目实际解释器中补齐兼容依赖，完成PYNQ导入、小模型拟合及Jupyter内核检查。

## 环境与包

使用[probe_pynq_environment.py](scripts/probe_pynq_environment.py)记录Python版本、指针位数、ARM架构、库路径、PYNQ API及用户。SSH解释器与Notebook内核分别核对。

另建继承系统库的环境，保留镜像提供的PYNQ、NumPy和SciPy。按发行版、Python ABI、armhf/aarch64及NumPy ABI选择wheel；缺少匹配wheel时检查同发行版预编译包及其依赖。

通过可用连接以二进制方式传输包，校验哈希，shell及校验文件使用LF。记录包来源、独立环境和内核名称。

## 验证

在独立解释器导入编译扩展并拟合小森林，再启动实际新增内核。使用[verify_pynq_kernel.py](scripts/verify_pynq_kernel.py)读取内核环境、拟合小模型并关闭临时内核。

权限异常核对执行用户，导入异常核对kernelspec argv、sys.executable和库路径。原生依赖或版本不符时保留原环境，补齐兼容包后继续。

交付环境JSON、来源与哈希、安装命令、拟合结果及内核入口，兼容范围以已验证板卡和镜像记录。

P4的Python3.8/aarch64依赖见[环境案例](references/p4-tested-setup.md)。运行`python scripts/verify_ml_stack.py --report stack.json`检查原生扩展、三类小森林与SciPy滤波，板端可加`--require-pynq`。
