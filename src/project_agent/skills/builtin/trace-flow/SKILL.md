---
name: trace-flow
description: Trace an end-to-end execution flow for a request, command, or feature
when_to_use: Use when you need to follow a data flow or call chain through the codebase
user_invocable: true
version: "1"
shell_interpolation: false
---

请追踪下面这个流程在仓库中的完整执行路径：

流程：{{args}}

要求：
- 明确列出起点、关键中间步骤、终点
- 标出重要文件、函数、类和它们之间的调用关系
- 如果存在分支逻辑，说明进入条件
- 如果有外部依赖、配置开关、环境变量，也一起说明
- 最后用一个简短的小结概括整条链路

回答要具体，尽量基于实际代码位置来说明。
