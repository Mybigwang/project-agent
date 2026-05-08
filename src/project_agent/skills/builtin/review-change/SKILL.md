---
name: review-change
description: Review a module or recent change for correctness, maintainability, and risk
when_to_use: Use when you want a focused code review of a file, feature, or change area
user_invocable: true
version: "1"
shell_interpolation: false
---

请对下面这个范围做一次严格代码审查：

审查范围：{{args}}

重点检查：
- 正确性和潜在 bug
- 边界条件
- 可维护性
- 不必要的复杂度
- 安全风险
- 测试覆盖是否合理

输出要求：
- 按严重级别给出问题（HIGH / MEDIUM / LOW）
- 尽量指出具体文件和位置
- 如果没有明显问题，也要明确说明结论
