Mengqing，这次新增的是一个 Claude Code 风格的本地 skill 机制。它的核心不是“先跑 skill，再让模型解释一次”，而是：

把 skill 展开后的文本，直接当成这次 agent 的真实输入。

也就是说，skill 本质上是一个可复用的 prompt/workflow 模板层，接在 CLI 的 slash command 分发前面。

1. 现在新增了什么能力
1) CLI 支持 /<skill-name> 调用
入口在 src/project_agent/cli.py:205。

以前：

/plan 是特殊命令
其他 /xxx 都是 unknown
现在：

/plan 继续保留：src/project_agent/cli.py:208
其他像 /demo hello world
会先去 skill registry 查 demo
找到后做参数展开
最终把展开后的文本直接传给 runtime.run_turn()
关键逻辑在：

src/project_agent/cli.py:210
src/project_agent/cli.py:215
2) 新增了完整的 skill 子系统
主要模块：

src/project_agent/skills/loader.py:10

负责发现和加载 skills

src/project_agent/skills/parser.py:15

负责解析 SKILL.md 的 frontmatter 和 body

src/project_agent/skills/registry.py

负责按名字查 skill

src/project_agent/skills/preprocessor.py:17

负责参数替换、内置变量替换、skill 组合展开、安全限制

src/project_agent/skills/models.py

定义 skill 相关数据结构

2. 你应该怎么用
你以后在 CLI 里可以直接这样写：


project-agent run --prompt "/demo hello world"
或者交互模式里输入：


/demo hello world
系统会做这几步：

解析命令 /demo
找到 skill demo
把 hello world 当作 skill 参数
展开 SKILL.md 中的占位符
得到最终 prompt
把这个 prompt 直接交给当前 agent runtime 执行
3. skill 文件应该怎么写
文件结构
现在支持的核心结构是：


.project_agent/
  skills/
    demo/
      SKILL.md
默认项目级 skill 目录来自配置：

workspace_root/.project_agent/skills
相关配置定义在：

src/project_agent/config.py:36
src/project_agent/config.py:38
另外也支持内建 skill：

src/project_agent/skills/builtin/<skill-name>/SKILL.md
加载入口：

src/project_agent/skills/loader.py:10
SKILL.md 格式
必须是：


---
name: demo
description: demo skill
---
这里写 skill 正文
解析规则在：

src/project_agent/skills/parser.py:8
src/project_agent/skills/parser.py:15
src/project_agent/skills/parser.py:27
要求：

必须有 frontmatter
必须有 name
必须有 description
body 不能为空
4. 一个最小可用例子
比如你建一个文件：

.project_agent/skills/explain-api/SKILL.md


---
name: explain-api
description: explain API-related code
---
请阅读当前仓库中与下面主题相关的代码，并解释其实现方式、关键入口、主要数据流和潜在风险：

主题：{{args}}

请用中文回答。
然后你运行：


project-agent run --prompt "/explain-api 用户登录"
系统真正送进模型的内容，大概会变成：


Skill: explain-api

请阅读当前仓库中与下面主题相关的代码，并解释其实现方式、关键入口、主要数据流和潜在风险：

主题：用户登录

请用中文回答。
注意顶部这个：


Skill: explain-api
是 preprocessor 自动加上的：

src/project_agent/skills/preprocessor.py:33
src/project_agent/skills/preprocessor.py:41
5. 现在支持哪些占位符
1) 参数占位符
实现位置：

src/project_agent/skills/preprocessor.py:130
支持：

{{args}}

原始整串参数

{{args[0]}}

{{args[1]}}

{{args[2]}}
等位置参数

例子：


---
name: summarize
description: summarize topic
---
主题={{args}}
第一个词={{args[0]}}
第二个词={{args[1]}}
调用：


/summarize hello world
展开后大概是：


主题=hello world
第一个词=hello
第二个词=world
如果你引用了不存在的位置参数，比如只有一个参数却写了 {{args[1]}}，会直接报错：

src/project_agent/skills/preprocessor.py:135
这是故意的，不会静默降级。

2) 内置变量占位符
实现位置：

src/project_agent/skills/preprocessor.py:144
支持：

{{skill_name}}
{{skill_dir}}
{{workspace_root}}
例子：


---
name: inspect-skill
description: inspect current skill context
---
当前 skill={{skill_name}}
skill 目录={{skill_dir}}
工作区根目录={{workspace_root}}
参数={{args}}
6. 现在支持 skill 组合
这是这次比较重要的能力之一。

实现位置：

src/project_agent/skills/preprocessor.py:68
你可以在一个 skill 里引用另一个 skill：


{{skill:child}}
也可以带参数：


{{skill:child nested value}}
例子
child

---
name: child
description: child skill
---
Child {{args[0]}}
parent

---
name: parent
description: parent skill
---
Before
{{skill:child nested}}
After
执行：


/parent
会展开成：


Before
Child nested
After
这个行为在测试里有覆盖：

tests/unit/test_skills_preprocessor.py:41
7. skill 的加载优先级
加载逻辑在：

src/project_agent/skills/loader.py:17
当前优先级是：

builtin
user
project
后面的会覆盖前面的同名 skill。

也就是说：

项目 skill 可以覆盖内建 skill
同一来源内如果重名，会直接报错
这个测试在：

tests/unit/test_skills_loader.py:9
tests/unit/test_skills_loader.py:31
8. 这次加了哪些安全边界
1) 循环引用检测
比如：

a 引 b
b 又引 a
会报错，不会无限递归。

实现：

src/project_agent/skills/preprocessor.py:85
测试：

tests/unit/test_skills_preprocessor.py:63
2) 最大组合深度限制
防止 skill 嵌 skill 嵌太深。

实现：

src/project_agent/skills/preprocessor.py:82
测试：

tests/unit/test_skills_preprocessor.py:118
3) 最大展开长度限制
防止最终 prompt 膨胀过大。

实现：

src/project_agent/skills/preprocessor.py:64
测试：

tests/unit/test_skills_preprocessor.py:99
9. 命令替换现在是什么状态
这次没有真正开放执行 shell 命令，但把接口和校验边界先做好了。

检测位置：

src/project_agent/skills/preprocessor.py:13
src/project_agent/skills/preprocessor.py:14
src/project_agent/skills/preprocessor.py:109
支持识别两类写法：

行内

!`git status --short`
代码块

```!
git status --short
```
但是现在即使检测到，也不会执行。

行为是：

如果 skill frontmatter 没写：


shell_interpolation: true
直接报错

如果全局配置不允许 command substitution
直接报错

即使两者都允许，目前仍然会报：
skill command substitution is not implemented yet

也就是说：
现在只是“识别 + 校验 + 拒绝执行”，还没有真正落地 shell 插值。

对应测试：

tests/unit/test_skills_preprocessor.py:145
tests/unit/test_skills_preprocessor.py:171
tests/unit/test_skills_preprocessor.py:192
10. 现在有哪些配置项
定义在：

src/project_agent/config.py:36
src/project_agent/config.py:42
这次新增的 skill 配置主要有：

skills_enabled
skills_builtin_enabled
project_skills_dir
user_skills_dir
skills_allow_command_substitution
skills_max_composition_depth
skills_max_expansion_chars
默认行为大致是：

skill 总开关：开
builtin skill：开
project skill 目录：<workspace_root>/.project_agent/skills
command substitution：关
最大组合深度：3
最大展开字符数：20000
默认值测试：

tests/unit/test_config.py:37
11. 这次功能的边界：支持什么，不支持什么
已支持
/<skill-name> 显式调用
SKILL.md frontmatter + body
内建 skill / 项目 skill 加载
占位符替换
skill 组合
循环检测
深度限制
展开大小限制
CRLF 兼容
还没做
模型自动决定“该触发哪个 skill”
根据上下文自动注入 skill
真正执行 shell interpolation
远程 skill 源
条件触发规则
这一版是一个 稳定的第一阶段显式 skill 系统。

12. 最推荐的使用方式
我建议你现在先把它当成一组“可复用命令模板”来用。

比如你可以做这些 skill：

1) explain-code

---
name: explain-code
description: explain code by topic
---
请阅读仓库中与“{{args}}”相关的代码，并说明：
1. 入口
2. 核心流程
3. 关键数据结构
4. 潜在问题

用中文回答。
2) review-module

---
name: review-module
description: review module quality
---
请审查与“{{args}}”相关的模块，重点关注：
- 可维护性
- 错误处理
- 安全边界
- 重复逻辑

请给出明确结论。
3) fix-bug

---
name: fix-bug
description: debug and fix a bug
---
请定位并修复这个问题：{{args}}

要求：
- 先确认根因
- 最小改动修复
- 不做额外重构
- 修改后运行相关测试
然后直接这样用：


/explain-code 登录流程
/review-module skills 子系统
/fix-bug CLI slash command 解析异常
13. 一句话总结你该怎么理解它
你可以把这套功能理解成：

把常用工程任务封装成 SKILL.md，然后通过 /命令 直接展开成真实 prompt 执行。

不是二次包装，不是额外模型层，而是 prompt 预处理层。

如果你愿意，我下一步可以直接给你写 3～5 个适合这个项目的实用 skill 示例。