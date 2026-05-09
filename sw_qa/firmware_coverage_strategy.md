# KX6625 Firmware Coverage Improvement Strategy

本文档记录基于当前 KX6625 QEMU 平台提升 firmware 测试覆盖率的建议实施方式，以及需要进一步确认的决策项。目标不是一次性把所有覆盖率工具堆上去，而是建立一条可稳定运行、可诊断、可逐步收敛到 release gate 的路径。

## 背景判断

当前平台已经具备几个非常适合做 firmware coverage 的基础能力：

- QEMU 可以稳定运行 Cortex-M4 firmware，并通过 `ICOUNT_SHIFT=5` 提供确定性的虚拟时间。
- `scripts/e2e_test.sh` 已经能自动启动 Python device server、SV host shell、QEMU、UART 注入和结果断言。
- firmware 已经覆盖 UART、DMA、CRC、dual CPU IPC、SV timer/DMA、HSM、OTP、SYSCTRL、WDT reset 等主要路径。
- Python trace 已经能输出 `build/device_trace.jsonl` 和 `build/trace_report.html`，适合作为 coverage 诊断 artifact 的一部分。
- firmware 使用 `arm-none-eabi-gcc` 裸机/FreeRTOS 构建，没有目标端文件系统，因此常规 `gcov` 的 `.gcda` 文件落盘流程不能直接套用，需要设计目标端数据导出机制。

因此建议把 coverage 分成三层推进：

1. 场景/需求/API 覆盖：最快落地，先把当前 e2e 输出结构化。
2. 行覆盖率和函数覆盖率：基于 GCC/LLVM instrumentation，在 QEMU 运行后从 firmware 导出覆盖率数据。
3. 分支覆盖和 MC/DC：先做关键 safety/security 代码的增量试点，再决定是否引入专用工具或更高版本编译器能力。

## 推荐实施路线

### Phase 0: 建立 coverage 目标和测试矩阵

先不要直接追求一个全局百分比。建议先建立 `sw_qa/test_matrix.yaml` 或 `sw_qa/test_matrix.md`，把 firmware 测试拆成可命名、可追踪的测试项。

建议字段：

| Field | 含义 |
|-------|------|
| test_id | 稳定测试编号，例如 `FW_UART_001` |
| module | UART/DMA/CRC/HSM/OTP/SYSCTRL/WDT/RTOS 等 |
| scenario | 测试场景描述 |
| trigger | UART 菜单命令、启动参数、fault injection 参数等 |
| expected_log | 当前可自动 grep 的关键输出 |
| expected_trace | 可选，对 `device_trace.jsonl` 的期望事件 |
| requirement | 关联需求、设计条目或 RDM ID |
| coverage_type | API/feature/IRQ/reset/negative/source 等 |

这一层的产出应该是 `summary.json`：

```json
{
  "build": "pass",
  "tests": [
    {
      "id": "FW_DMA_001",
      "module": "DMA",
      "scenario": "memory to memory copy",
      "result": "pass",
      "evidence": ["Verification PASSED"]
    }
  ],
  "artifacts": {
    "firmware": "build/firmware.elf",
    "trace": "build/device_trace.jsonl",
    "trace_html": "build/trace_report.html"
  }
}
```

推荐原因：这一步不依赖 gcov/MC/DC 工具链，能很快把“当前到底测了什么”说清楚，也方便后面把源码覆盖率和需求覆盖率合并展示。

### Phase 1: 行覆盖率和函数覆盖率

行覆盖率、函数覆盖率建议优先使用编译器 instrumentation，而不是从 QEMU 指令 trace 反推源码行。

推荐方案：GCC freestanding gcov flow。

核心思路：

1. 增加一个 coverage firmware 构建模式，例如 `make fw COVERAGE=1`。
2. coverage 模式增加类似编译选项：
   - `-O0` 或 `-Og`
   - `-g3`
   - `-fprofile-arcs`
   - `-ftest-coverage`
   - 如工具链支持，增加 `-fprofile-info-section`，更适合裸机导出。
3. 链接 `libgcov`，并在 linker script 中保留 `.gcov_info` 或相关 section。
4. firmware 在测试完成后调用 coverage dump 函数，把 gcov 数据通过 UART、专用 MMIO coverage device、semihosting 或 QEMU debug channel 导出到 host。
5. host 侧脚本把导出的 stream 还原/合并为 `.gcda`，再用 `gcov`/`lcov`/`genhtml` 生成行覆盖率和函数覆盖率报告。

建议优先选择“专用 MMIO coverage device”或“UART coverage stream”：

- UART stream 实现最轻，但日志里会混入大量 coverage payload，需要 framed protocol 和转义。
- 专用 MMIO coverage device 更干净，可以把 coverage payload 直接写到 `build/coverage/coverage.stream`，也能避免污染正常 firmware 输出。
- semihosting 简单，但会改变 QEMU 启动参数和运行语义，不一定适合当前平台主路径。

建议目录结构：

```text
sw_qa/
├── firmware_coverage_strategy.md
├── test_matrix.yaml
└── coverage_notes.md

build/coverage/
├── firmware.elf
├── gcov-stream.bin
├── gcov-data/
├── lcov.info
└── html/
```

第一阶段可先限定统计对象：

- `firmware/main.c`
- `firmware/cpu1_main.c`
- `firmware/runtime.c`
- 当前自研 driver/helper 代码

暂不建议把完整 FreeRTOS kernel 作为第一批 coverage gate。FreeRTOS 源码会显著稀释指标，且很多路径不是当前 firmware 测试目标。

### Phase 2: 分支覆盖率和条件覆盖率

行/函数覆盖稳定后，再加入 branch coverage。GCC gcov 可以输出 branch taken 信息，适合发现明显未覆盖的错误处理路径、timeout 路径和 negative path。

建议优先覆盖这些代码类型：

- HSM/OTP security negative paths。
- SYSCTRL secure boot/status 判断。
- WDT reset reason 判断。
- DMA busy/error/done 状态判断。
- UART RX timeout、非法命令、buffer 边界。
- 多核 IPC 异常或超时路径。

QEMU 的优势在这里很明显：我们可以用 deterministic virtual time 和可控 device model 做 fault injection。例如：

- 让 OTP 返回 zero-to-one error。
- 让 HSM 返回 error interrupt。
- 让 DMA fabric read/write 失败。
- 让 timer/WDT 在固定虚拟时间触发。
- 让 SYSCTRL/CRU 模拟 clock gated、reset asserted、secure boot fail 等状态。

建议新增 test mode，而不是把所有 negative path 混进现有 `a` 全量菜单。例如：

| Mode | 用途 |
|------|------|
| `a` | 当前 smoke/all demos |
| `c` | coverage normal suite |
| `n` | negative/fault injection suite |
| `r` | reset/reboot suite |
| `s` | security suite |

### Phase 3: MC/DC 覆盖

MC/DC 不建议一开始就做全 firmware 全量指标。它适合作为高风险逻辑的目标化度量，例如 boot/security/reset/clock/power/error handling。

推荐两条可选路径：

#### 路径 A：工具链/开源能力试点

如果我们可以升级或选择较新的 host compiler/toolchain，可以评估：

- Clang/LLVM source-based coverage 是否支持目标架构和裸机导出流程。
- 是否可用 `llvm-cov` 生成条件覆盖或 MC/DC 类报告。
- 当前 `arm-none-eabi-gcc` 版本是否支持条件覆盖相关选项。

这种路径成本较低，但要先验证工具链版本、裸机 runtime、报告可信度和 CI 稳定性。

#### 路径 B：安全关键代码引入专用 MC/DC 工具

如果目标是功能安全或客户审计级别的 MC/DC，建议评估商用/认证工具链，例如 VectorCAST、LDRA、Tessy、Cantata 等。QEMU 仍然有价值：它可以作为执行 backend 或辅助环境，但最终报告需要满足工具的审计要求。

#### 当前建议

短期先不把 MC/DC 作为全局 gate。建议先选 2 到 3 个函数做 pilot：

- secure boot pass/fail decision。
- CRU/SYSCTRL clock-reset policy decision。
- OTP/HSM key access permission decision。

对这些函数建立 decision table，明确每个 condition 如何独立影响 decision，再设计 QEMU fault injection case 验证。即使第一版没有自动 MC/DC 工具，这个表也能作为后续工具导入和审计的基础。

## QEMU 平台应新增的能力

### 1. Coverage 专用运行脚本

建议新增 `scripts/coverage_test.sh`，不要直接把 coverage 逻辑塞进 `e2e_test.sh`。

职责：

- 用 coverage flags 构建 firmware。
- 启动 Python device server、SV host shell、QEMU。
- 注入 coverage suite 命令。
- 等待 firmware 打印 `COVERAGE_DUMP_DONE` 或 coverage device close event。
- 生成 `summary.json`、`lcov.info` 和 HTML report。

### 2. Coverage 数据通道

建议新增一个 host-side coverage sink，二选一：

- Python coverage device：新增一个 MMIO 设备或扩展 UART server，把 firmware 写入的数据保存为 binary stream。
- QEMU-native debug device：更靠近 QEMU，但需要改 QEMU fork。

我倾向先做 Python coverage device，因为它和当前 Python device domain 风格一致，迭代快，也容易记录 trace。

### 3. Fault injection 配置

建议 Python device server 支持一个可选配置文件，例如：

```bash
python3 device_model/mmio_device_server.py --fault-config sw_qa/fault_profiles/otp_zero_to_one.yaml
```

示例 profile：

```yaml
name: otp_zero_to_one
rules:
  - device: otp
    operation: program
    row: 16
    force_error: ZERO_TO_ONE
```

这样 branch/MC/DC 测试可以系统化，而不是在 firmware 中写死异常路径。

### 4. Coverage 报告聚合

建议最终每次 coverage run 产出：

```text
build/coverage/
├── summary.json
├── lcov.info
├── html/index.html
├── test_matrix_result.json
├── device_trace.jsonl
├── trace_report.html
├── e2e_server.log
├── e2e_qemu.log
├── e2e_uart.log
└── e2e_sv_host_shell.log
```

CI 只需要上传整个 `build/coverage/` 目录即可。

## 建议的初始 gate

不要第一天就设置高覆盖率门槛。建议分阶段：

| 阶段 | Gate 建议 |
|------|-----------|
| 初始 | coverage job 能稳定运行并产出报告 |
| 第 1 阶段 | 所有 test matrix 中 P0/P1 用例通过 |
| 第 2 阶段 | 自研 firmware 文件行覆盖率不下降 |
| 第 3 阶段 | 关键模块函数覆盖率达到约定阈值，例如 80% |
| 第 4 阶段 | security/reset/error handling 的 branch/condition 覆盖不下降 |
| 第 5 阶段 | 选定安全关键函数达到 MC/DC 目标 |

阈值建议先以 baseline 为准，而不是拍脑袋定 90%。先跑出第一版报告，再把 baseline 固化到 CI。

## 已确认决策

以下决策来自 2026-05-08 的方案确认，后续实现以“方法论证清楚、发挥虚拟平台使用价值”为主，不以短期 CI/CD 部署或高阈值 gate 为目标。

| Item | 决策 |
|------|------|
| 覆盖率目标范围 | 第一阶段只针对 `firmware/` 下的自研代码，不把 FreeRTOS kernel 纳入 gate。 |
| 工具链 | 可以引入 Clang/LLVM，与现有 `arm-none-eabi-gcc` 并行评估。 |
| 覆盖率数据通道 | 主路径倾向 MMIO coverage device；同时保留 semihosting 打通验证，作为有价值的技术点。 |
| 报告格式 | 接受可视化 HTML 报告。 |
| 测试组织 | 现阶段 firmware 菜单暂不拆分，先论证 coverage 方法。 |
| Fault injection | 接受在 Python device model 或 SV device 中注入错误，用来触发错误路径和 MC/DC case。 |
| MC/DC 目标 | 先面向内部质量提升，重点打通通路和方法，不做客户/功能安全审计承诺。 |
| CI 环境 | 未来环境是公司 Jenkins，但当前暂不处理 CI/CD 部署事务。 |
| Release gate | 第一版只做趋势监控，不设置强制覆盖率阈值。 |
| 需求追踪 | 可以先建立 demo 用 test matrix，用于演示需求到测试到证据的覆盖关系。 |

## 建议下一步

我建议先做一个最小闭环：

1. 新增 `sw_qa/test_matrix.yaml`，把当前 `e2e_test.sh` 的 expected log 拆成 demo 测试项。
2. 新增一个 `scripts/coverage_summary.py`，从 e2e log 和 trace 生成 `build/coverage/summary.json`。
3. 在 firmware Makefile 增加 `TOOLCHAIN=clang` 编译入口，先证明 Clang/LLVM 可以作为可插拔 coverage backend 的基础。
4. 在 firmware Makefile 增加 `COVERAGE=1` 编译开关，先验证带 LLVM coverage mapping/profile counters 的 firmware 能编译、链接并通过 e2e。
5. 选择 coverage 数据通道并做一个最小 LLVM profile stream dump demo。
6. 用 `lcov/genhtml` 或 `llvm-cov show` 生成第一版 HTML，再决定 gate 阈值。

`scripts/coverage_summary.py` 的第一版职责是读取 `sw_qa/test_matrix.yaml`，扫描 `build/e2e_server.log`、`build/e2e_uart.log` 等 evidence log，判断每个 demo requirement/test 是否有对应证据，并输出 `build/coverage/summary.json` 与 `build/coverage/summary.html`。由于当前策略是趋势监控，可以使用 `--trend-only` 只生成报告而不让脚本返回失败码；需要把它用作 gate 时则不加该参数。

这个顺序的好处是：即使 gcov/MC/DC 工具链验证需要时间，测试矩阵和 summary artifact 也能先服务日常 CI 和质量评审。