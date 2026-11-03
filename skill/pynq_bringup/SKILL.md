---
name: pynq-bringup
description: 核验已启动PYNQ的bit/HWH、IP地址、寄存器和只读版本回读，定位Overlay与驱动接口错配。
---

# PYNQ Overlay接口核验

加载前检查bit/HWH与接口契约；板端验证分别记录文件、寄存器、数值算法和物理采集结果。

## 文件与元数据

[check_overlay.py](scripts/check_overlay.py)支持HWH清点和显式契约检查，默认读取电脑文件。

```bash
python scripts/check_overlay.py --inventory design.hwh --report inventory.json
python scripts/check_overlay.py --contract contract.json --report check.json
```

契约记录同basename的bit/HWH、可信构建SHA256、器件、IP路径及VLNV、地址范围、主接口和寄存器。BRAM同时检查mem_dict，层级模块使用完整路径。自定义module_ref缺少HWH寄存器表时，依据RTL偏移及只读ID/版本寄存器验证。

## 加载与回读

确认目标板、镜像、任务空闲和外部输出状态后加载Overlay。重配后核对默认输出、ip_dict、mem_dict及register_map。PYNQ设备发现异常时，对照服务实际解释器、用户与XRT环境。线程初始化所需事件循环按线程设置。

probes仅填写无副作用的32位寄存器，确认已加载对应文件后执行：

```bash
python scripts/check_overlay.py --contract contract.json --read-live --report live.json
```

该模式核对PL.bitfile_name、IP元数据和显式MMIO读值；读清零与FIFO端口排除在安全回读表外。合成夹具用于离线模式。

## 共享数据与恢复

PS和加速器共享BRAM时按阶段分配写权限，读完后再复用。DDR缓冲使用pynq.allocate，写模型后flush，读结果前invalidate；释放以硬件访问结束为条件。

跨域多位配置通过稳定保持及请求应答提交。取消等待硬件确认，超时保存故障状态。总线实现与对应验证按AXI BRAM、HP共享DDR等通路分别记录。

通用夹具见[契约示例](references/contract.md)，板端观察见[验证案例](references/validated-cases.md)，当前版本与地址见[接口定义](references/current_interfaces.md)。

共享DDR进一步使用[缓冲生命周期检查](../pynq-buffer-ownership/SKILL.md)，验证flush/invalidate、超时与释放顺序；实际缓存属性由目标平台确定。
