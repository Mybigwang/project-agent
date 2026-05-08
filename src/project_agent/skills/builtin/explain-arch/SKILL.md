---
name: explain-arch
description: Explain a module, feature, or architecture path in this repository
when_to_use: Use when you want a structured explanation of how some code works
user_invocable: true
version: "1"
shell_interpolation: false
---

请基于当前仓库上下文，解释下面这个主题相关的实现：

主题：{{args}}

请按以下结构回答：
1. 入口文件或入口函数
2. 核心执行流程
3. 关键数据结构或配置
4. 与哪些模块耦合
5. 容易出错或值得注意的地方

如果用户给的是具体文件、类、函数名，请优先围绕它展开，不要泛泛而谈。
