# Lab 07. 设计软件 CI/CD 与 Coverage 雏形

## 目标

把当前 e2e 测试整理成 CI pipeline 草案，并设计第一阶段 coverage 指标。

## 实验 1：写出最小 CI 命令序列

在纸面或临时文件中写出：

```bash
make gen
make sv
make fw
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

讨论：

- 哪些命令可以缓存？
- 哪些失败应该立即终止？
- 哪些文件需要保存为 artifacts？

## 实验 2：设计 test matrix

填写类似表格：

| Test ID | Module | Scenario | Expected |
|---------|--------|----------|----------|
| T001 | UART | RX IRQ | UART interrupt handled |
| T002 | DMA | M2M copy | Verification PASSED |
| T003 | CRC | direct vector | 0xCBF43926 PASSED |
| T004 | SV_TIMER | IRQ clear | IRQ observed and cleared PASSED |

## 实验 3：设计 coverage 指标

第一阶段建议指标：

- driver API coverage
- feature coverage
- reset scenario coverage
- IRQ scenario coverage
- negative scenario count

讨论每项如何从 firmware log 或 result register 中提取。

## 实验 4：设计 CI artifacts

建议输出：

```text
artifacts/
├── firmware.elf
├── e2e_server.log
├── e2e_qemu.log
├── e2e_uart.log
├── e2e_sv_host_shell.log
├── device_trace.jsonl
├── trace_report.html
└── summary.json
```

## 思考题

1. 软件 coverage 和 RTL coverage 最大区别是什么？
2. 为什么第一阶段不建议直接追求完整 gcov/lcov？
3. 如果 e2e 偶发失败，如何判断是平台 flaky 还是软件 bug？
4. 哪些指标适合作为 release gate？
