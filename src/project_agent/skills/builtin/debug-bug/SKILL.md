---
name: debug-bug
description: Investigate a bug, identify root cause, and propose or implement a minimal fix
when_to_use: Use when a bug report, failing behavior, or error message needs focused debugging
user_invocable: true
version: "1"
shell_interpolation: false
---

请定位并修复下面这个问题：

问题描述：{{args}}

工作要求：
1. 先确认复现线索或可观察现象
2. 再定位根因，不要只停留在表面报错
3. 只做满足需求的最小改动，不做顺手重构
4. 修改后运行相关测试或校验命令
5. 最终说明根因、修改点、验证结果

如果信息不足，请先基于仓库现状缩小排查范围，再继续推进。
