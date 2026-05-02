# 面向 Claude Code 的 Python 开源 CLI Agent 框架 Roadmap

## Phase 0：项目初始化与技术基线
### 目标
建立可持续迭代的 Python 开源框架骨架，明确最小产品边界与工程规范。

### 功能
- 初始化 Python 项目结构（src/tests/examples/docs）
- 建立 CLI 入口与基础命令框架
- 接入配置系统（环境变量、配置文件、命令行参数）
- 建立日志系统与统一错误处理
- 建立测试框架、lint、format、type check、CI
- 定义插件接口、Tool 接口、Model 接口、Session 接口的基础抽象

### 阶段完成标准
- 可通过命令启动 CLI
- 本地开发、测试、格式化、静态检查流程跑通
- 框架目录与核心抽象稳定

---

## Phase 1：最小 Agent Runtime
### 目标
实现 Claude Code 风格的最小执行闭环：用户输入、模型推理、工具调用、结果回注、最终输出。

### 功能
- 实现会话管理与消息历史管理
- 实现 Model Client 抽象，支持标准 LLM 对接
- 实现 Agent Loop：推理 -> 调用工具 -> 注入工具结果 -> 继续推理
- 支持流式输出
- 支持 tool calling 的统一协议与执行结果封装
- 支持基础执行日志与调用轨迹展示

### 阶段完成标准
- CLI 可完成多轮交互
- 模型可以主动选择调用工具并基于结果继续执行
- 一次请求可完成多步执行闭环

---

## Phase 2：核心本地工具集
### 目标
具备 Claude Code 最核心的本地工程操作能力，让 Agent 真正能对代码库行动。

### 功能
- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `search_code`
- `run_command`
- Tool Registry 与 Tool Schema 管理
- 工具输出标准化与失败重试策略
- Workspace 边界限制

### 阶段完成标准
- Agent 可读取、搜索、修改项目文件
- Agent 可执行受控命令并消费命令输出
- 所有工具具备统一注册、调用、返回结构

---

## Phase 3：代码仓上下文系统
### 目标
让 Agent 像 Claude Code 一样围绕代码仓上下文工作，而不是只依赖对话文本。

### 功能
- Workspace 上下文收集
- Git 上下文收集（branch、status、diff、recent commits）
- 项目规则文件加载（如 `CLAUDE.md`）
- 当前任务相关文件聚合
- 上下文裁剪与优先级装配
- 大仓库场景下的分段读取与搜索策略

### 阶段完成标准
- Agent 能自动感知当前仓库状态
- Agent 能在回答和执行时使用项目约束
- 上下文长度可控，不因大仓库直接失效

---

## Phase 4：任务规划与执行管理
### 目标
让 Agent 具备“先拆解任务，再逐步执行”的能力，形成 Claude Code 风格的任务推进体验。

### 功能
- Task 数据结构与状态流转（pending/in_progress/completed/blocked）
- Planner：从用户请求生成分阶段任务
- 执行过程中的任务状态更新
- 任务依赖关系管理
- 失败任务重试与重新规划
- CLI 中展示当前任务进度

### 阶段完成标准
- 复杂请求会先生成任务列表
- Agent 在执行中能更新任务状态
- 执行失败时可局部修正而不是整体失控

---

## Phase 5：权限、安全与可控自治
### 目标
建立 Claude Code 风格的人机协作安全机制，保证 Agent 能做事但不越权。

### 功能
- 工具级风险分级
- 写文件、执行命令等操作的交互确认
- 路径级访问控制
- 命令黑白名单机制
- 危险操作拦截（删除、覆盖、外发）
- 审计日志与可追踪执行记录
- 安全策略配置文件

### 阶段完成标准
- 高风险操作默认不可静默执行
- Agent 的所有关键动作可追踪、可审计
- 用户可配置权限策略

---

## Phase 6：开发工作流能力
### 目标
把 Agent 从“能调用工具”升级为“能参与真实开发流程”的工程助手。

### 功能
- Plan Mode
- Review Mode
- Fix Mode
- Test Mode
- Git 集成（status、diff、commit message 草拟）
- 测试执行与结果解析
- 失败诊断与修复循环
- 面向开发流程的标准命令入口

### 阶段完成标准
- Agent 可围绕开发任务进行计划、修改、验证、汇报
- Agent 可在本地形成最基本的开发闭环
- 常见研发操作具备统一入口和行为规范

---

## Phase 7：Slash Commands / Skills 系统
### 目标
把高频流程沉淀为可复用能力，提升框架的开放性与可扩展性。

### 功能
- Slash Command 机制（如 `/plan`、`/review`、`/fix`、`/test`）
- Skill 定义格式
- Skill 加载与发现机制
- Skill 级权限与上下文注入
- Skill 组合执行
- 第三方 Skill 扩展接口

### 阶段完成标准
- 高价值工作流可通过命令直接触发
- 新能力可通过 Skill 扩展，而不必修改核心框架
- 框架具备开源生态扩展基础

---

## Phase 8：Hooks 与自动化工作流
### 目标
让 Agent 能嵌入用户工程流程，形成 Claude Code 风格的自动化协作机制。

### 功能
- PreToolUse Hook
- PostToolUse Hook
- SessionEnd Hook
- Hook 配置与执行上下文
- Hook 失败处理策略
- 自动格式化、自动测试、自动校验等示例 Hook

### 阶段完成标准
- 工具执行前后可挂接自动化逻辑
- 用户可用 Hook 定制团队工作流
- 框架支持更强的工程自动化能力

---

## Phase 9：多 Agent 协作
### 目标
支持将复杂任务拆给不同角色 Agent 执行，提升复杂任务处理能力。

### 功能
- 子 Agent 生命周期管理
- Agent 角色定义（planner/reviewer/researcher/fixer）
- 并行任务分发
- 子 Agent 结果汇总
- 主 Agent 调度与冲突控制
- 多 Agent 上下文隔离

### 阶段完成标准
- 一个复杂任务可拆分给多个子 Agent
- 主 Agent 能汇总子 Agent 结果继续推进任务
- 多 Agent 并行不会污染主会话状态

---

## Phase 10：MCP 与外部能力接入
### 目标
建立标准化外部工具接入层，让框架具备平台化扩展能力。

### 功能
- MCP Client 抽象
- 外部资源与工具发现
- 外部文档、浏览器、数据库、Issue 系统接入
- 外部工具权限控制
- 本地工具与 MCP 工具统一调度

### 阶段完成标准
- 框架可接入外部 MCP 服务
- 外部能力与本地工具在统一执行模型下协作
- 插件生态边界清晰

---

## Phase 11：记忆、压缩与长会话能力
### 目标
提升长会话与持续协作能力，让 Agent 更接近真实长期开发助手。

### 功能
- Session 历史压缩
- Memory 抽象（user/project/reference/feedback）
- Memory 写入与检索策略
- 重要上下文摘要与回放
- 长任务恢复能力

### 阶段完成标准
- 长对话不会因上下文膨胀完全失效
- Agent 能在后续会话中复用关键信息
- 会话恢复与摘要机制稳定可用

---

## Phase 12：IDE / Browser / 发布生态
### 目标
从 CLI 框架演进为完整开源 Agent 平台，支持更丰富的开发入口与生态能力。

### 功能
- IDE 集成接口
- Browser 自动化接口
- 示例项目与模板仓库
- 开源文档站点
- 插件开发文档
- 版本发布流程与兼容性策略
- Benchmark 与评测用例

### 阶段完成标准
- 除 CLI 外具备更广泛的接入方式
- 外部开发者可基于文档进行二次开发
- 项目具备开源社区协作基础

---

## 推荐开发顺序
1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7
9. Phase 8
10. Phase 9
11. Phase 10
12. Phase 11
13. Phase 12
