# 已验证案例与提炼来源（2026-10-17）

来源：项目先从PC网口采集迁到PYNQ内部AXI，过程中出现bit/hwh不配套、自定义寄存器没有HWH表、BRAM在mem_dict而不在ip_dict、Flask线程没有事件循环等问题。后来双DAC改为125MHz，旧驱动的300MHz换算不再适用，因此版本寄存器从2升3并增加时钟回读。

验证记录见[validation-20261017.json](validation-20261017.json)：

- 非TDC vector_sum合成元数据在电脑与P4均通过，错误hash/VLNV/地址/寄存器/不安全probe均被拒绝，合成bit拒绝live模式。
- 当前真实XCZU4EV bit/hwh文件哈希、3个IP地址范围、7个HLS寄存器元数据通过；记录对应产物哈希。
- P4已加载Overlay只读回读：ID=0x54444331、接口版本3、时钟125000000，未下载bit、未写寄存器、未开输出。
- 复现了能import pynq但No Devices Found：该镜像网页服务设置了XILINX_XRT=/usr，独立终端未继承。检查命令继承该服务环境后设备发现通过，目标镜像使用其实际XRT路径。

实测HWH为Vivado2020.2 EDKSYSTEM XML，合成Zynq-7000夹具用于元数据软件检查。其他目标按各自构建与授权核验。
