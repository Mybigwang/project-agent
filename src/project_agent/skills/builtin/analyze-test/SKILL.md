---
name: analyze-test
description: Analyze a failing test or design the right test coverage for a change
when_to_use: Use when tests are failing or when you want help deciding what tests to add
user_invocable: true
version: "1"
shell_interpolation: false
---

请分析下面这个测试相关问题：

测试主题：{{args}}

如果是失败测试，请回答：
1. 失败现象
2. 更可能是实现问题、测试问题，还是环境问题
3. 应该先检查哪些文件和断言
4. 最小修复路径

如果是要补测试，请回答：
1. 应该补哪些测试场景
2. 哪些是核心路径，哪些是边界条件
3. 更适合写单测、集成测试还是端到端测试

请尽量结合当前仓库已有测试风格来判断。
