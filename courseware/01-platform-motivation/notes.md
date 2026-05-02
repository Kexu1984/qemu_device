# Notes 01. 讲师备注

## 讲授重点

本讲不要过早进入代码细节。重点是建立平台定位和边界：

- 软件开发为什么需要虚拟平台
- 验证团队为什么需要 firmware-driven 视角
- 客户为什么需要 binary simulator 来调试 application
- QEMU/Python/SV 各自负责什么
- 这个平台不是 signoff 工具

## 推荐讲法

先从团队痛点讲起，而不是从 QEMU 技术讲起：

1. 软件等板子、等 RTL、等 FPGA。
2. RTL testbench 与真实 firmware 脱节。
3. bring-up 问题拖到很晚才暴露。
4. 客户拿到 SDK 后也可能缺少硬件，app 调试和问题复现效率低。
5. 平台的意义是把一部分问题前移，并把虚拟调试能力交付给客户。

然后再引出本项目架构。

## 客户价值讲法

可以把平台价值分成三层：

1. 内部 BSP/SDK/driver bring-up。
2. 内部 RTL device firmware-driven functional validation。
3. 对客户交付 binary-compatible simulator，让客户调试自己的 app。

第三层很重要，因为它把平台从“研发工具”提升成“客户支持和生态工具”。

典型表述：

```text
我们不仅用它调试 BSP，也可以让客户在没有开发板时运行 SDK binary，
调试 application，复现问题，并把 trace/log 反馈给我们。
```

## 容易被误解的点

### 误解 1：QEMU 可以替代 RTL 仿真

澄清：不能。QEMU 是 CPU/SoC 行为级模型，本平台验证软件可见行为，不验证门级时序和 RTL coverage closure。

### 误解 2：SV 接进来就等于 cycle accurate co-sim

澄清：当前 SV device 有本地 clock，但 QEMU 与 SV 不做跨域 cycle 对齐。MMIO 是同步事务边界。

### 误解 3：Python model 不够真实，所以没价值

澄清：Python model 的价值是快、可观测、可作为 reference/checker。它和 RTL model 是互补关系。

### 误解 4：客户只能等硬件才能开始 app 开发

澄清：如果 BSP/SDK binary interface 稳定，客户可以先在 simulator 上开发和调试大量软件逻辑。硬件到位后再做性能、模拟特性和真实外设边界验证。

## 可展示的命令

```bash
git log -1 --oneline
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
less build/e2e_server.log
less build/e2e_sv_timer.log
```

## 建议讨论

- 哪些软件问题可以在这个平台暴露？
- 哪些 RTL 问题不适合在这个平台验证？
- 如果公司内部要落地，软件团队和验证团队分别需要提供什么？
- 如果作为客户交付工具，需要哪些最小文档、脚本、sample app 和问题复现流程？

## 课后任务

让学员用自己的话写一段平台定位，必须包含：

- 适合解决的问题
- 不适合解决的问题
- 对内部研发和外部客户分别有什么价值
- QEMU/Python/SV 的角色分工
