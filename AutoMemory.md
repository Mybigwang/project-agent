# Project Agent Memory 系统说明

本次实现的是一套参考 Claude Code 设计的文件化 memory 系统。核心目标是：让 Agent 在每轮用户请求开始时读取持久记忆索引，交给模型判断哪些 topic memory 与当前输入相关，再把被召回的记忆内容注入主模型 prompt。

## 1. 文件化 memory 存储

默认目录：

```text
<workspace_root>/.project_agent/memory/
```

目录约定：

```text
.project_agent/memory/
  MEMORY.md          # 入口索引
  user_preferences.md
  release_process.md
  external_refs.md
```

实现位置：

- `src/project_agent/runtime/memory/store.py`
- `src/project_agent/runtime/memory/builder.py`

特点：

- 不使用数据库或隐藏状态。
- `MEMORY.md` 只作为入口索引。
- 具体长期记忆拆分到独立 Markdown topic 文件。
- 首次运行会自动创建 memory 目录和 `MEMORY.md`，不会覆盖已有文件。

## 2. MEMORY.md 入口索引

`MEMORY.md` 是轻量索引，不应该堆积长正文。

推荐写法：

```markdown
- [User preferences](user_preferences.md) — 用户长期协作偏好
- [Release process](release_process.md) — 项目发布流程约束
```

运行时会把当前 `MEMORY.md` 内容放进 memory system prompt。若为空，会明确提示 `MEMORY.md is currently empty`。

相关限制：

- `memory_entrypoint_max_lines`：默认 200 行。
- `memory_entrypoint_max_bytes`：默认 25000 bytes。

超出后会截断，并在 prompt 中提示 index 被截断。

## 3. Topic memory 文件

除 `MEMORY.md` 外，memory 目录下其他 `.md` 文件都是 topic memory。

每个 topic 文件建议只表达一个主题，例如：

```markdown
# User preferences

用户希望每次回复前称呼 Mengqing。

**Why:** 项目 CLAUDE.md 明确要求。
**How to apply:** 所有普通回复开头使用 Mengqing。
```

扫描 topic 文件时，系统提取轻量 manifest：

- `relative_path`
- `title`：第一个 Markdown heading；没有 heading 时使用文件 stem。
- `description`：标题后的第一个非空、非 heading 行。
- `mtime`

系统不会一开始读取所有 topic 全文，只先读取 manifest，降低 prompt 成本。

## 4. 大模型驱动 Relevant Memory Recall

当前版本已不是关键词匹配。

实现位置：

- `src/project_agent/runtime/memory/recall.py`

流程：

1. `MemoryContextBuilder.build(user_input=...)` 先初始化 memory 目录。
2. 读取 `MEMORY.md`。
3. 扫描 topic memory manifest。
4. 调用 `ModelMemoryRecall.select(...)`。
5. recall 模型收到：
   - 当前用户输入。
   - `max_files` 限制。
   - memory manifest。
6. recall 模型必须返回 JSON：

```json
{"files":["relative/path.md"]}
```

7. 系统只接受 manifest 中存在的路径，忽略未知路径，并限制最多 `memory_max_relevant_files` 个。
8. 被选中的 topic 文件全文会被读取并注入 memory prompt。

这意味着 relevant recall 发生在主模型调用之前：先让模型根据 manifest 选择记忆，再把选中的记忆内容放入主模型 prompt。

## 5. 每轮只 recall 一次，后续复用

实现位置：

- `src/project_agent/runtime/agent.py`

`AgentRuntime.run_turn()` 会在每个 user turn 开始时构建一次 `MemoryContext`：

```python
memory_context = self._build_memory_context(
    memory_context_builder=memory_context_builder,
    user_input=user_input,
)
```

随后这个 `memory_context` 会在同一轮内复用：

- 普通首次模型调用。
- tool result 后重新构建模型消息。
- skill message 后重新构建模型消息。
- planner task 首次调用。
- planner task tool / skill 后重新构建模型消息。

这样既能保证 memory prompt 在每次主模型调用前都存在，又避免 tool-heavy 流程中反复调用 recall 模型。

## 6. Memory prompt 注入顺序

模型消息构建时的顺序是：

1. task prefix message（如果是 planner task）。
2. repository context system message。
3. memory system message。
4. skill catalog system message。
5. conversation messages。
6. `ContextManager.prepare_messages(...)`。

因此 memory 会先进入模型消息队列，再经过 context manager / compaction 处理。

## 7. 终端显示 recall 结果

现在 CLI 会在终端显示本轮 memory recall 结果。

实现位置：

- `src/project_agent/core/types.py`
- `src/project_agent/runtime/agent.py`
- `src/project_agent/cli.py`

`RunResult` 新增：

```python
memory_context: MemoryContext | None = None
```

CLI 在输出最终回答前会显示：

```text
Memory recall:
  - auth.md
  - release_process.md
```

如果本轮没有召回任何 topic 文件，或者 memory 被禁用，则不显示 memory recall 行，避免干扰普通输出。

这用于实际测试时确认大模型本轮到底选择了哪些记忆文件。

## 8. 相关 topic 内容注入

被 recall 选中的 topic 文件会以 section 形式注入：

```markdown
## Relevant recalled memories

## Relevant memory: auth.md

# Auth

OAuth login decisions...
```

每个 topic 文件注入内容受配置限制：

- `memory_max_relevant_file_chars`：默认 3000 chars。

超出后会追加：

```text
[Memory file truncated]
```

## 9. Memory 写入与维护规则

memory prompt 会提醒模型：

应该保存：

- 长期用户偏好。
- 长期项目偏好。
- 跨会话决策。
- 非显而易见的项目背景。
- 外部系统引用及其意义。

不应该保存：

- secret、token、私钥。
- 可从代码或 git history 直接推导的信息。
- 临时任务状态。
- 一次性 debugging notes。
- 大段日志或原始 tool output。
- 重复、过时、猜测性信息。

保存流程：

1. 创建或更新 topic markdown 文件。
2. 在 `MEMORY.md` 增加或更新一行索引。
3. 更新或删除过时记忆，不重复追加。

当前版本没有新增专用 memory tool；因为 memory 目录在 workspace 内，模型可通过现有文件工具维护这些 Markdown 文件。

## 10. 容错与安全

实现位置：

- `src/project_agent/config.py`
- `src/project_agent/runtime/memory/store.py`

约束：

- `memory_dir` 必须位于 `workspace_root` 内。
- 防止 memory path traversal。
- `MEMORY.md` 或 topic 文件非 UTF-8 / 不可读时不会让整轮 Agent 失败。

容错行为：

- `MEMORY.md` 读取失败：按空内容处理。
- topic manifest 读取失败：跳过该文件。
- recalled topic 读取失败：按空内容处理。

## 11. CLI doctor 输出

`project-agent doctor` 会显示：

```text
memory_enabled=True
memory_dir=<workspace_root>/.project_agent/memory
```

用于确认 memory 是否启用以及实际目录。

## 12. 配置一览

所有配置都在 `[project_agent]` 下，并支持环境变量。

| 配置 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `memory_enabled` | `PROJECT_AGENT_MEMORY_ENABLED` | `true` | 是否启用 memory 系统 |
| `memory_dir` | `PROJECT_AGENT_MEMORY_DIR` | `<workspace_root>/.project_agent/memory` | memory 文件目录，必须在 workspace 内 |
| `memory_entrypoint_max_lines` | `PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_LINES` | `200` | 注入 `MEMORY.md` 的最大行数 |
| `memory_entrypoint_max_bytes` | `PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_BYTES` | `25000` | 注入 `MEMORY.md` 的最大字节数 |
| `memory_max_manifest_files` | `PROJECT_AGENT_MEMORY_MAX_MANIFEST_FILES` | `50` | 每轮最多扫描多少个 topic manifest |
| `memory_max_relevant_files` | `PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILES` | `3` | 每轮最多召回多少个 topic memory 文件 |
| `memory_max_relevant_file_chars` | `PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILE_CHARS` | `3000` | 每个 recalled topic 文件最多注入多少字符 |

完整示例：

```toml
[project_agent]
memory_enabled = true
memory_dir = ".project_agent/memory"

memory_entrypoint_max_lines = 200
memory_entrypoint_max_bytes = 25000

memory_max_manifest_files = 50
memory_max_relevant_files = 3
memory_max_relevant_file_chars = 3000
```

## 13. 当前未实现的能力

当前版本暂未实现：

1. 自动后台记忆提取。
2. Session Memory 摘要文件。
3. user / project / local 多层 memory scope。
4. Agent Memory Snapshot。
5. Team Memory Sync。
6. 向量检索。
7. 专用 memory read/write/edit tool。
8. memory UI 文件选择器。

当前版本定位是基础文件化 memory substrate：

```text
文件化存储
+ MEMORY.md 索引
+ topic markdown
+ 大模型驱动 relevant recall
+ 召回内容 prompt 注入
+ 每轮 recall 一次并复用
+ 终端显示 recall 结果
+ 配置化截断保护
```
