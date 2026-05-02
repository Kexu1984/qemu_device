# Lab 06. 分析 e2e 测试和 Trace Report

## 目标

理解 e2e 如何自动判断 PASS/FAIL，并掌握基本失败定位方法。

## 实验 1：运行 e2e

```bash
ICOUNT_SHIFT=5 bash scripts/e2e_test.sh
```

确认：

```text
[PASS] End-to-end IRQ test PASSED
```

## 实验 2：阅读 e2e 脚本

```bash
sed -n '1,340p' scripts/e2e_test.sh
```

重点找出：

- sanity check
- port cleanup
- Python server 启动
- UART client
- SV bridge
- QEMU command line
- EXPECTED array
- command injection
- result evaluation

## 实验 3：制造一个失败

临时复制脚本：

```bash
cp scripts/e2e_test.sh /tmp/e2e_test_fail.sh
```

把其中一个 expected string 改成不存在的字符串，然后运行：

```bash
ICOUNT_SHIFT=5 bash /tmp/e2e_test_fail.sh
```

观察 FAIL 输出。

## 实验 4：查看 trace report

```bash
xdg-open build/trace_report.html
```

或直接打开 HTML 文件。

观察：

- DMA events
- WDT reset events
- virtual time ordering

## 思考题

1. 为什么 e2e 同时检查 SERVER_LOG 和 UART_LOG？
2. expected string 方式在什么情况下不可靠？
3. 如果要接 CI，哪些文件应该作为 artifacts 保存？
4. 如何把 e2e 输出转换成 JUnit XML 或 JSON summary？
