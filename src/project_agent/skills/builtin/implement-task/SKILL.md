---
name: implement-task
description: Implement a scoped feature or change with minimal, direct execution steps
when_to_use: Use when you already know what to build and want focused implementation work
user_invocable: true
version: "1"
shell_interpolation: false
---

请实现下面这个任务：

任务：{{args}}

执行要求：
- 先阅读相关代码，确认修改入口
- 采用与当前项目一致的实现方式
- 只实现任务本身，不额外加功能
- 如果需要测试，补充最相关的测试
- 完成后简要说明修改了哪些文件，以及如何验证

如果任务存在多种合理实现方式，优先选择最简单、最贴合现有架构的一种。
