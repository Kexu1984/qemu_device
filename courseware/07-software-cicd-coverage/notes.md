# Notes 07. 讲师备注

## 讲授重点

本讲要把平台从技术 demo 拉到软件工程体系。

重点强调：

- CI/CD 是本平台最自然的落地点
- coverage 要分阶段做
- RTL 验证不在本路径承接
- artifacts 和报告是团队协作的接口

## 推荐讲法

先问团队：现在软件提交后，如何证明没破坏 driver/RTOS/SDK？

然后引出 CI pipeline。

## Coverage 讲授建议

不要一上来讲 gcov 实现细节。先讲 coverage 的层次：

1. case 是否跑过
2. feature 是否覆盖
3. API 是否调用
4. branch/assert 是否命中
5. code line/branch coverage

这样更符合平台演进节奏。

## 常见误区

### 误区 1：没有 line coverage 就不算 coverage

澄清：早期平台可以先做 test/API/scenario coverage。这些对驱动质量已经有价值。

### 误区 2：软件 CI 可以替代 RTL 验证

澄清：软件 CI 只能证明软件可见行为在模型上通过，不能替代 RTL coverage/signoff。

### 误区 3：CI 只要 PASS/FAIL

澄清：CI 更重要的是可诊断 artifacts。否则失败无法快速定位。

## 课后任务

让学员设计一个 `summary.json` 格式，至少包含：

- build status
- test cases
- duration
- failed checks
- artifact paths
