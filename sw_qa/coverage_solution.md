# Coverage Data Export Solution

本文档说明 semihosting 的机制，以及基于当前 KX6625 QEMU firmware coverage 工作流的最小 dump 通路方案。目标是先论证方法，不把 semihosting 作为最终唯一方案；主路径仍倾向 MMIO coverage device，semihosting 作为技术验证和对照路径。

## Semihosting 机制

Semihosting 是一种让 target 程序向 host 调试/仿真环境发起服务请求的机制。它最早常用于裸机程序在没有文件系统、没有 printf 后端、没有调试 console 的情况下，通过调试器或模拟器访问 host 侧资源。

在 Cortex-M/Arm 裸机环境里，semihosting 典型通路是：

1. firmware 把 semihosting operation number 放到 `r0`。
2. firmware 把参数块地址放到 `r1`。
3. firmware 执行特殊断点指令，Cortex-M 常用 `BKPT 0xAB`。
4. QEMU/GDB/debug agent 捕获这个 breakpoint。
5. host 侧根据 `r0/r1` 执行对应服务，例如 open/write/close 文件。
6. host 把返回值写回 `r0`，target 从 `BKPT` 后继续执行。

典型调用形态类似：

```c
static inline int semihost_call(int op, void *args)
{
    register int r0 __asm__("r0") = op;
    register void *r1 __asm__("r1") = args;
    __asm__ volatile ("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
    return r0;
}
```

QEMU 侧必须显式启用 semihosting，例如：

```bash
qemu-system-arm ... -semihosting
```

或使用更明确的配置：

```bash
qemu-system-arm ... -semihosting-config enable=on,target=native
```

### 与 SVC 的区别

当前 FreeRTOS Cortex-M port 已经使用 SVC 作为调度启动和系统调用机制：vector table 里的 `SVCall -> vPortSVCHandler`。因此不建议用 `svc` 指令承载 semihosting。对 Cortex-M 来说，coverage semihosting 应使用 `BKPT 0xAB`，由 QEMU 捕获，而不是进入 firmware 的 SVC handler。

### Semihosting 的优点

- firmware 侧实现简单，不需要新增 MMIO 设备。
- 可以直接让 target 写 host 文件，适合快速 demo。
- 对单次 coverage dump 很方便，例如测试完成后写出 `build/coverage/firmware.profraw`。

### Semihosting 的限制

- 需要修改 QEMU 启动参数，未启用时 `BKPT 0xAB` 可能变成 HardFault 或调试异常。
- host 文件访问语义由 QEMU/debugger 实现，和真实芯片行为不同。
- semihosting 调用通常会停住 CPU 等 host 处理，时间语义不适合放进性能或实时路径。
- 在当前平台里，QEMU `-icount` 虚拟时间和 semihosting host I/O 是不同层面的行为；dump 应只放在测试结束点。

## LLVM Coverage 当前状态

当前 `TOOLCHAIN=clang COVERAGE=1` 已经完成第一阶段：

- 编译时启用 `-fprofile-instr-generate -fcoverage-mapping`。
- firmware ELF 中已经保留 LLVM coverage/profile sections。
- coverage-instrumented firmware 已通过 QEMU e2e。
- 还未生成 host 侧 `.profraw` 文件。

ELF 中关键 section/symbol：

| 内容 | 位置 | 用途 |
|------|------|------|
| `__llvm_covmap` | FLASH/rodata | 源码 coverage mapping，供 `llvm-cov` 解释 counter 与源码关系 |
| `__llvm_prf_names` | FLASH/rodata | 函数/profile 名称表 |
| `__llvm_prf_data` | RAM/data | profile metadata |
| `__llvm_prf_cnts` | RAM/data | 运行时 counters，测试执行时被插桩代码更新 |

当前缺少的是“把 RAM 中 counters/profile 数据按 LLVM raw profile 格式导出”的 runtime 逻辑。

## 最小 Semihosting Dump 方案

### 目标

先打通一个技术验证闭环：

```text
Clang coverage firmware
  -> QEMU e2e executes tests
  -> firmware calls coverage dump at test end
  -> semihosting writes build/coverage/firmware.profraw
  -> llvm-profdata merge
  -> llvm-cov show/report generates HTML/text
```

### 推荐最小路径

#### Step 1: 启用 QEMU semihosting 参数

新增 coverage 专用脚本时，不直接改 `scripts/e2e_test.sh` 主路径。建议新增：

```text
scripts/coverage_test.sh
```

该脚本启动 QEMU 时增加：

```bash
-semihosting-config enable=on,target=native
```

或先用简单形式：

```bash
-semihosting
```

原因：避免普通 e2e 依赖 semihosting，也避免没有 semihosting 时 firmware 的 `BKPT 0xAB` 影响主线测试。

#### Step 2: firmware 增加 semihosting write/open/close helper

新增或扩展 `firmware/coverage_runtime.c`，只在 `COVERAGE=1` 时编译。

需要的 semihosting operations：

| Operation | 常见编号 | 用途 |
|-----------|----------|------|
| `SYS_OPEN` | `0x01` | 打开 host 文件 |
| `SYS_CLOSE` | `0x02` | 关闭 host 文件 |
| `SYS_WRITE` | `0x05` | 写 host 文件 |
| `SYS_FLEN` | `0x0C` | 可选，查询文件长度 |

最小实现只需要 open/write/close。建议 firmware 写固定路径：

```text
build/coverage/firmware.profraw
```

如果 QEMU semihosting 的工作目录不稳定，可以先写相对路径 `coverage.profraw`，由脚本运行前 `cd $PROJECT_ROOT` 固定 cwd。

#### Step 3: 生成 LLVM raw profile 数据

这里是关键点：不能简单把 `__llvm_prf_cnts` 原样写出去就声称是 `.profraw`。`llvm-profdata` 需要 LLVM raw profile 格式，里面包含 header、profile data、counters、names、版本和 padding 等。

有两种实现路径：

##### 路径 A：移植 LLVM profile writer 的最小子集

从 LLVM compiler-rt profile runtime 的 raw profile writer 中抽取最小逻辑，结合当前 ELF 中的边界符号：

```c
extern char __llvm_prf_data_start[];
extern char __llvm_prf_data_end[];
extern char __llvm_prf_cnts_start[];
extern char __llvm_prf_cnts_end[];
extern char __llvm_prf_names_start[];
extern char __llvm_prf_names_end[];
```

然后 firmware 构造 raw profile header，并通过 semihosting `SYS_WRITE` 输出：

```text
raw profile header
profile data records
counters
names
padding
```

优点：host 侧可以直接使用标准 `llvm-profdata merge`。

缺点：需要认真对齐 LLVM 10 raw profile 格式，初次实现要用 host 小程序对照验证。

##### 路径 B：先 dump 自定义 raw sections，再由 host 转换

firmware 不直接生成 `.profraw`，而是通过 semihosting 写出一个自定义 container，例如：

```text
KXCV magic/version
prf_data_size + bytes
prf_cnts_size + bytes
prf_names_size + bytes
covmap_size + bytes, optional
```

host 侧再写 `scripts/llvm_coverage_pack.py`，把这些 sections 按 LLVM 10 raw profile 格式组装成 `.profraw`。

优点：firmware 侧简单、可调试、容易打印和比对。

缺点：host 转换脚本需要理解 LLVM raw profile 格式；这不是标准 compiler-rt 直接输出。

### 当前建议

最小 demo 优先选择路径 B：

1. firmware 通过 semihosting dump 自定义 coverage section 包。
2. host 侧脚本解析包并生成可检查的中间 JSON/二进制摘要。
3. 再决定是否直接实现 LLVM raw profile packer，或切回 MMIO coverage device 承载同样的数据。

原因：我们当前目标是方法论证。先证明 target 能在测试结束时把 coverage counters 和 mapping 数据稳定导出，比第一步就完全复刻 LLVM raw profile writer 更稳。

## 最小 Dump 触发点

当前 firmware 的 `a` 全量测试最后会进入 WDT reset，warm boot 后打印：

```text
[WDT] WDT demo complete.
```

建议第一版 dump 点放在 warm boot path 中，打印完成后调用：

```c
coverage_dump_semihosting();
send_string("[COV] semihosting dump complete\n");
```

这样好处是：

- 当前 e2e 的所有 demo case 都已经跑完。
- WDT reset path 也已经覆盖。
- dump 发生在测试末尾，不影响中间设备时序。

如果后续拆分 test suite，则每个 suite 可以在退出前显式 dump。

## 与 MMIO Coverage Device 的关系

Semihosting 是最短路径，但 MMIO coverage device 更适合作为主线：

| 维度 | Semihosting | MMIO coverage device |
|------|-------------|----------------------|
| 接入成本 | 低 | 中 |
| 是否需要改 QEMU 参数 | 是 | 否，按现有 mmio-sockdev 模式扩展即可 |
| 与芯片 MMIO 模型一致性 | 弱 | 强 |
| 数据流可追踪性 | 一般 | 好，可进入 Python trace/artifact |
| 适合长期主路径 | 一般 | 更适合 |

建议把两者设计成同一个上层接口：

```c
void coverage_dump(void)
{
#if defined(COVERAGE_DUMP_SEMIHOSTING)
    coverage_dump_semihosting();
#elif defined(COVERAGE_DUMP_MMIO)
    coverage_dump_mmio();
#endif
}
```

这样后续替换数据通道时，不影响测试矩阵、coverage summary、`llvm-cov` 报告聚合流程。

## 已实现的 MMIO Coverage Device

当前已实现第一版 MMIO coverage dump 通路：

- `coverage` device 挂在 `0x40010000`，通过 `mmio-sockdev` 端口 `7918` 接入 Python device domain。
- firmware 在 `TOOLCHAIN=clang COVERAGE=1` 时编译 `coverage_runtime.c`，把 LLVM profile/coverage sections 分块写入 coverage device。
- dump 触发点放在 `a` 全量测试路径的 WDT reset 之前，避免 WDT reset 清空 `.data` 中的 `__llvm_prf_cnts`。
- Python device 写出 `build/coverage/firmware.kxcv`，并生成 `build/coverage/firmware_coverage_summary.json`。
- `scripts/inspect_coverage_dump.py` 可以解析 `KXCV` 文件，并检查 `prf_cnts` 是否包含非零 counter。
- `scripts/kxcv_to_profraw.py` 可以把 `KXCV` 中间容器转换为 LLVM 10 raw profile：`build/coverage/firmware.profraw`。
- `scripts/llvm_coverage_report.py` 可以生成 `firmware.profdata`、text summary、line report 和 HTML report。

`KXCV` 是 MMIO 通路的中间容器，标准 LLVM 链路从 host 侧转换开始：

```bash
scripts/kxcv_to_profraw.py build/coverage/firmware.kxcv \
    -o build/coverage/firmware.profraw \
    --elf build/firmware.elf

llvm-profdata merge -sparse build/coverage/firmware.profraw \
    -o build/coverage/firmware.profdata
```

常规使用建议直接运行：

```bash
scripts/llvm_coverage_report.py
```

该脚本会生成：

- `build/coverage/firmware.profraw`
- `build/coverage/firmware.profdata`
- `build/coverage/llvm_cov_report.txt`
- `build/coverage/llvm_cov_show.txt`
- `build/coverage/html/index.html`

注意：当前 `llvm-cov` 报告使用 `build/main.o`、`build/cpu1_main.o`、`build/runtime.o` 作为 coverage object，而不是最终 `build/firmware.elf`。原因是当前 linker script 为了裸机运行把 LLVM coverage input sections 合并进 `.rodata/.data`，最终 ELF 不再保留 `llvm-cov` 识别所需的 `__llvm_covmap` 命名 section；编译后的 `.o` 文件仍保留这些 section，适合用于 host 侧 coverage report。

当前一次 e2e 后的示例结果：

```text
TOTAL  Regions 705, Missed 89, Cover 87.38%
TOTAL  Functions 40, Missed 7, Executed 82.50%
TOTAL  Lines 743, Missed 97, Cover 86.94%
```

### 如何理解 llvm-cov 结果

`llvm-cov report` 里的几个核心字段含义如下：

| 字段 | 含义 | 如何判断 |
|------|------|----------|
| `Regions` | LLVM coverage mapping 生成的代码区域数量。一个区域通常对应一个基本语句块、分支块、条件表达式片段或宏展开片段，不等同于源码行数。 | 区域覆盖率比行覆盖率更细，可以看到同一行里部分表达式未执行的情况。 |
| `Missed Regions` | 执行计数为 0 的 region 数量。 | 数值越小越好；若某个文件行覆盖率高但 missed regions 多，说明可能有未覆盖分支或条件路径。 |
| `Cover` | 覆盖率百分比，计算方式是 `(Regions - Missed Regions) / Regions`。在 `Lines` 栏下同理是行覆盖率，在 `Functions` 栏下是函数执行覆盖率。 | 用于横向比较版本趋势，不建议单独作为准入标准；要结合需求覆盖和测试意图判断。 |
| `Functions` | 被插桩识别到的函数总数。 | 包含 static helper、IRQ handler、runtime helper 等，只要编译进 coverage object 就会统计。 |
| `Missed Functions` | 函数入口计数为 0 的函数数。 | 可用来快速发现完全没被测试调用的函数。 |
| `Executed` | 函数执行覆盖率，计算方式是 `(Functions - Missed Functions) / Functions`。 | 对 firmware smoke/e2e 很直观，但无法说明函数内部所有分支都覆盖。 |
| `Lines` | 有 coverage mapping 的源码行总数。 | 不等于文件总行数；空行、注释、部分声明不会计入。 |
| `Missed Lines` | 执行计数为 0 的源码行数。 | 适合做直观展示，但对一行多分支的代码不够细。 |

这次结果的可信度主要来自四层校验：

1. firmware 是用 `TOOLCHAIN=clang COVERAGE=1` 构建，插桩 section 和 counter section 已经进入镜像。
2. e2e 日志显示 `a` 全量测试在 WDT reset 前打印 `[COV] MMIO coverage dump complete`，说明 dump 发生在 counter 被 reset 清空之前。
3. `firmware_coverage_summary.json` 中 `prf_data/prf_cnts/prf_names/covmap` 均完整，且 `prf_cnts.nonzero_u64` 为非零，说明不是空 dump。
4. `llvm-profdata merge` 能接受转换后的 `firmware.profraw`，`llvm-cov report/show` 能基于 profile 输出函数计数、行计数和 HTML 报告。

需要注意的局限：当前 source report 使用 `build/main.o`、`build/cpu1_main.o`、`build/runtime.o` 作为 coverage object，因此报告范围就是这些 firmware 源文件；FreeRTOS kernel、QEMU native device、Python device model 不在这个 LLVM source coverage 统计范围内。

## 验证标准

第一版 coverage dump 通路完成后，至少验证：

1. `TOOLCHAIN=clang COVERAGE=1` firmware 能构建。
2. QEMU 带 MMIO coverage device 后 e2e 仍 PASS。
3. 测试结束后 host 侧出现 coverage dump 文件。
4. dump 文件中 `prf_data/prf_cnts/prf_names/covmap` size 非零，且与 ELF 符号范围一致。
5. `scripts/coverage_summary.py --trend-only` 仍输出 13/13 PASS。
6. `scripts/kxcv_to_profraw.py` 能生成 `build/coverage/firmware.profraw`。
7. `llvm-profdata merge` 能生成 `build/coverage/firmware.profdata`。
8. `llvm-cov show -format=html` 能输出 `build/coverage/html/index.html`。

## 风险与待确认点

- LLVM raw profile 格式和版本强相关。当前环境是 LLVM 10，未来升级 LLVM 后需要重新验证 packer/runtime。
- WDT reset 会清除 `.data` 中的 profile counters。当前 linker 把 `__llvm_prf_cnts` 放在 `.data`，如果 dump 放在 warm boot 后，可能丢失 reset 前 counters。这个点需要重点验证。
- 若 WDT reset 确实清除 counters，则第一版 dump 点应改到 WDT reset 前，或者把 profile counter section 放入不被 reset 清零/重初始化的 RAM 区域。
- Semihosting file path 在 QEMU 中的 cwd 需要固定，建议 coverage script 进入 repo root 后再启动 QEMU。
- `BKPT 0xAB` 在未启用 semihosting 时不可执行，因此 dump 函数必须只在 coverage + semihosting 专用构建/运行路径启用。

## 下一步建议

1. 把 `scripts/llvm_coverage_report.py` 接入 CI，作为 coverage 方法论证明的固定产物。
2. 增加趋势文件，记录每次 e2e 的 line/function/region coverage 百分比。
3. 按 `sw_qa/test_matrix.yaml` 拆分 suite，把 requirement evidence 和 LLVM source coverage 关联展示。
4. 评估是否把最终 ELF 保留 `__llvm_covmap` 命名 section；若可行，`llvm-cov` 可直接使用 `build/firmware.elf`。
5. 后续如仍需对照，可新增 semihosting transport，但复用当前 `KXCV -> profraw -> llvm-cov` host 链路。