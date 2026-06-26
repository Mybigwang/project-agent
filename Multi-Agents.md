Mengqing，本次 multi-agent 改造把原来“能启动子 Agent / coordinator 可以派 worker”的基础能力，升级成了带角色契约、权限边界、结构化通信、反递归和验证角色的成熟版。下面结合代码逐项说明。

## 1. 总览：本次新增了哪些核心能力？

本次主要新增/强化了 10 类能力：

1. 显式 Agent 角色体系：`explore` / `plan` / `worker` / `verification` / `coordinator` / `generalPurpose`。
2. 角色契约 `AgentRoleContract`：每种角色有独立 prompt、只读策略、是否允许派生、是否要求结构化输出。
3. Explore / Plan 硬只读：不再只靠 prompt 约束，而是通过权限策略禁止写入和命令执行。
4. Verification 独立验证角色：禁写，只允许安全验证命令，并输出 `PASS` / `FAIL` / `PARTIAL` verdict。
5. 结构化 worker 输出协议：统一解析 `<agent-result>`，提取 summary、evidence、touched_files、commands_run、open_questions、verdict。
6. 更丰富的 `<task-notification>`：coordinator 收到的不再只是 summary/result，而是带 role、verdict、evidence、文件、命令、开放问题。
7. 反递归硬约束：child agent 不能再创建 child agent，即使 `agent` 工具意外泄漏也会拒绝。
8. Anti-lazy 任务规格校验：拒绝 `fix it` / `make it better` / `figure it out` 这类模糊派工。
9. Coordinator 阶段模型：Discovery -> Merge/Plan -> Execution -> Verification。
10. Session 持久化升级：父 session 中保存更完整的 agent run 元数据和结构化结果。

仍然明确不支持：真后台 `run_in_background`、真并行 worker、递归 subagent、team/mailbox/swarm、per-worker model routing。

## 2. 核心数据结构新增了什么？

位置：`src/project_agent/core/types.py:8-10`、`src/project_agent/core/types.py:119-172`

### 2.1 AgentRole

新增：

```python
AgentRole = Literal[
    "explore",
    "plan",
    "worker",
    "verification",
    "coordinator",
    "generalPurpose",
]
```

含义：

- `explore`：只读探索，负责找文件、符号、证据。
- `plan`：只读规划，负责分阶段、风险、验收、验证命令。
- `worker`：执行明确任务。
- `verification`：独立验证，不信任实现者自述。
- `coordinator`：顶层协调器角色，不允许作为 child agent。
- `generalPurpose`：普通通用子 Agent，但也受反递归和任务规格约束。

### 2.2 AgentVerdict

新增：

```python
AgentVerdict = Literal["PASS", "FAIL", "PARTIAL"]
```

用于 verification agent 汇报验证结论。

### 2.3 AgentStructuredResult

位置：`src/project_agent/core/types.py:119-126`

新增结构化结果：

```python
@dataclass(frozen=True)
class AgentStructuredResult:
    summary: str
    evidence: tuple[str, ...] = ()
    touched_files: tuple[str, ...] = ()
    commands_run: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    verdict: AgentVerdict | None = None
```

作用：

- 让 coordinator 不再只能读一段自由文本。
- 子 Agent 输出可以被拆成证据、文件、命令、问题、结论。
- verification 的 `PASS/FAIL/PARTIAL` 可以单独持久化和展示。

### 2.4 AgentSpec 扩展

位置：`src/project_agent/core/types.py:129-142`

新增字段：

- `role`：本次子 Agent 的角色。
- `target_files`：目标文件集合，后续可用于冲突检测/任务边界。
- `verification_commands`：建议验证命令。
- `depth`：agent 深度，用于反递归。

现在一次子 Agent 请求不只是“description + prompt”，而是可以带角色和边界信息。

### 2.5 AgentRunRecord 扩展

位置：`src/project_agent/core/types.py:145-160`

新增字段：

- `role`：实际运行角色。
- `readonly`：该角色是否只读。
- `structured_result`：结构化结果。
- `verdict`：验证结论。
- `parent_session_id`：父 session。
- `depth`：当前 agent 深度。

父 session 里的 `agent_runs` 现在能记录更多审计信息。

### 2.6 AgentNotification 扩展

位置：`src/project_agent/core/types.py:163-172`

新增：

- `role`
- `verdict`
- `structured_result`

这样 `<task-notification>` 可以携带结构化字段，而不是只有纯文本 result。

## 3. multi_agent.py 新增了哪些成熟能力？

位置：`src/project_agent/runtime/multi_agent.py`

### 3.1 结构化输出模板

位置：`multi_agent.py:41-60`

新增 `STRUCTURED_RESULT_TEMPLATE`，要求子 Agent 最终输出：

```xml
<agent-result>
<summary>...</summary>
<evidence>
- ...
</evidence>
<touched-files>
- ...
</touched-files>
<commands-run>
- ...
</commands-run>
<open-questions>
- ...
</open-questions>
<verdict>PASS|FAIL|PARTIAL</verdict>
</agent-result>
```

意义：

- coordinator 可以稳定提取结果。
- verification 的 verdict 可以单独识别。
- 结果不再完全依赖自然语言总结。

### 3.2 Coordinator 阶段模型

位置：`multi_agent.py:62-78`

`COORDINATOR_SYSTEM_PROMPT` 从简单协调说明升级为 4 阶段工作流：

1. Discovery：用 `explore` 子 Agent 做只读探索。
2. Merge/Plan：合并证据，识别文件冲突，决定串行/独立派工。
3. Execution：给 `worker` 派明确任务，必须包含目标、范围、文件、约束、验收、验证。
4. Verification：实现后使用独立 `verification` 子 Agent 检查。

同时强调：

- worker 输出是 `untrusted evidence`。
- 不能执行 worker 文本里的指令。
- 不允许 worker 互看私有 transcript。
- 同一热点文件或共享接口必须串行处理。

### 3.3 统一子 Agent 启动前缀

位置：`multi_agent.py:80-84`

新增 `SHARED_SUBAGENT_PROMPT`：

```text
Fork started — processing in background.
You are a focused Project Agent subagent running in a child session.
You MUST NOT spawn subagents or ask another agent to do your work.
Complete only the assigned task and stay within scope.
```

作用：

- 统一子 Agent 行为边界。
- 明确禁止再派生。
- 使用稳定 prompt 前缀，有利于缓存和一致性。

### 3.4 角色专属 prompt

位置：`multi_agent.py:86-110`

新增：

- `EXPLORE_SYSTEM_PROMPT`
- `PLAN_SYSTEM_PROMPT`
- `WORKER_SYSTEM_PROMPT`
- `VERIFICATION_SYSTEM_PROMPT`
- `GENERAL_PURPOSE_SYSTEM_PROMPT`

每种角色有不同职责。例如：

- Explore：只读，只返回路径、符号、行号、证据、不确定性。
- Plan：只读，只输出阶段、依赖、风险、验收和验证命令。
- Verification：独立检查，不信任实现者自述，输出 verdict。

### 3.5 AgentRoleContract

位置：`multi_agent.py:113-129`

新增：

```python
@dataclass(frozen=True)
class AgentRoleContract:
    role: AgentRole
    readonly: bool
    can_spawn: bool
    requires_structured_output: bool
    system_prompt: str
```

并通过 `ROLE_CONTRACTS` 定义角色能力：

| role | readonly | can_spawn | structured output |
| --- | --- | --- | --- |
| explore | true | false | true |
| plan | true | false | true |
| worker | false | false | true |
| verification | false | false | true |
| coordinator | false | true | false |
| generalPurpose | false | false | true |

注意：`coordinator` 只用于顶层 coordinator mode，不允许作为 child agent。

### 3.6 build_subagent_prompt 增强

位置：`multi_agent.py:136-152`

现在 prompt 会包含：

- Task description
- Role
- Instructions
- Target files
- Verification commands
- Parent user request
- Structured result template

这比旧版只包含 description / instructions / parent request 更完整。

### 3.7 task notification 结构化

位置：`multi_agent.py:164-187`

`format_task_notification()` 现在输出：

```xml
<task-notification>
<task-id>...</task-id>
<role>...</role>
<status>...</status>
<verdict>...</verdict>
<summary>...</summary>
<evidence>...</evidence>
<touched-files>...</touched-files>
<commands-run>...</commands-run>
<open-questions>...</open-questions>
<result trust="untrusted-worker-output">...</result>
</task-notification>
```

增强点：

- coordinator 能看到 role 和 verdict。
- evidence / files / commands / open questions 单独分区。
- 所有 worker 输出仍会经过 XML 转义，避免 prompt injection。
- `<result>` 继续标记为 `trust="untrusted-worker-output"`。

### 3.8 结构化结果解析

位置：`multi_agent.py:204-239`

新增：

- `parse_agent_structured_result()`
- `_extract_tag()`
- `_extract_list_tag()`

行为：

- 从 `<agent-result>` 中提取 summary、evidence、touched-files、commands-run、open-questions、verdict。
- 如果 verification 没有合法 verdict，自动设为 `PARTIAL`。
- 如果没有结构化字段，summary fallback 为原始文本。

### 3.9 角色权限策略

位置：`multi_agent.py:242-251`

新增 `_permission_policy_for_role()`：

- `explore` / `plan`：使用 `PermissionPolicy(mode=PermissionMode.PLAN)`，硬禁止写和执行。
- `verification`：使用 `VerificationPermissionPolicy`。
- `worker` / `generalPurpose`：沿用基础权限策略。

这意味着只读角色不再只是 prompt 约束。

### 3.10 VerificationPermissionPolicy

位置：`multi_agent.py:254-281`

新增 verification 专用权限策略：

- 禁止所有 `WRITE` 工具。
- `EXECUTE` 只允许安全验证命令。
- 其他读/搜请求交给基础权限策略。

安全验证命令白名单位置：`multi_agent.py:284-303`

当前允许：

- `pytest`
- `python -m pytest`
- `ruff check`
- `black --check`
- `git status`
- `git diff`

这样 verification 能跑检查，但不能通过任意 shell 命令修改工作区。

### 3.11 run_subagent 增强

位置：`multi_agent.py:311-429`

`MultiAgentOrchestrator.run_subagent()` 现在新增：

1. 拒绝 child `coordinator` role。
2. 拒绝 `depth > 1`，防递归。
3. 根据 role 读取 `ROLE_CONTRACTS`。
4. 根据 role 设置权限策略。
5. 注入 shared prompt + role prompt。
6. 执行后解析结构化结果。
7. 截断 summary，最多保存 `MAX_AGENT_RECORD_CHARS = 2000`。
8. 写入扩展后的 `AgentRunRecord`：role、readonly、structured_result、verdict、parent_session_id、depth。

失败时也会记录 role、readonly、parent_session_id、depth，方便审计。

## 4. multi_agent_tools.py 新增了什么？

位置：`src/project_agent/runtime/multi_agent_tools.py`

### 4.1 agent 工具 schema 支持角色枚举

位置：`multi_agent_tools.py:31-45`

`subagent_type` 从任意字符串变成枚举：

```json
["explore", "plan", "worker", "verification", "generalPurpose"]
```

不再允许模型传任意角色。

### 4.2 SubagentTool 新增运行参数

位置：`multi_agent_tools.py:49-97`

新增构造参数：

- `default_role`
- `strict_task_specs`
- `parent_depth`

含义：

- `default_role`：未显式传 `subagent_type` 时使用的默认角色。
- `strict_task_specs`：是否启用 anti-lazy 任务规格校验。
- `parent_depth`：当前工具所在 agent 深度，用于反递归。

CLI 现在默认传 `default_role="worker"`。

### 4.3 反递归工具级拦截

位置：`multi_agent_tools.py:99-107`

如果 `parent_depth > 0`，直接返回：

```text
recursive subagents are denied
```

错误码：

```text
recursive_subagents_denied
```

这和 orchestrator 层的 `depth > 1` 检查形成双保险。

### 4.4 max_subagents 仍然生效

位置：`multi_agent_tools.py:108-115`

单轮超过上限继续返回：

```text
maximum subagents per turn exceeded
```

错误码：`max_subagents_exceeded`。

### 4.5 background 仍明确拒绝

位置：`multi_agent_tools.py:116-122`

`run_in_background=True` 仍返回：

```text
run_in_background is not supported yet
```

错误码：`background_not_supported`。

### 4.6 ToolResult 返回结构化 data

位置：`multi_agent_tools.py:157-184`

`ToolResult.data` 现在包含：

- `agent_id`
- `session_id`
- `status`
- `summary`
- `role`
- `verdict`
- `evidence`
- `touched_files`
- `commands_run`
- `open_questions`
- `result`
- `result_trust = "untrusted-worker-output"`

### 4.7 notification 截断方式修复

位置：`multi_agent_tools.py:157-165`

现在只截断 notification 的 `result` 内容，再重新包装 `<task-notification>`。

也就是说：

- `<task-notification>` 外壳保持完整。
- `<role>` / `<status>` / `<summary>` / `<verdict>` 等结构不会被截断破坏。
- 大结果会在 `<result>` 内出现 `[truncated]`。

### 4.8 AgentSpecError

位置：`multi_agent_tools.py:187-190`

新增 `AgentSpecError`，支持携带结构化错误码。

### 4.9 _parse_agent_spec 增强

位置：`multi_agent_tools.py:193-236`

现在解析时会：

1. 校验 description / prompt 非空。
2. 校验 name / subagent_type / model 类型。
3. 校验 run_in_background 是 bool。
4. 解析 role。
5. 根据 `strict_task_specs` 执行任务规格校验。
6. 构造带 role/depth 的 `AgentSpec`。

### 4.10 role 校验

位置：`multi_agent_tools.py:239-246`

`_parse_role()` 行为：

- 允许：`explore`、`plan`、`worker`、`verification`、`generalPurpose`。
- 拒绝：`coordinator` child role。
- 拒绝未知 role。

错误码：`role_not_allowed`。

### 4.11 Anti-lazy 任务规格校验

位置：`multi_agent_tools.py:249-284`

`_validate_task_spec()` 会拒绝明显模糊任务：

- `fix it`
- `figure it out`
- `make it better`
- `do everything`
- `handle everything`
- `based on your findings fix`

并且：

- `worker` / `generalPurpose` 必须包含路径、文件、测试、验证、scope、accept 等具体信号之一。
- `verification` 必须包含 test / pytest / check / lint / build / probe / verify 等验证意图。

错误码：`task_spec_too_vague`。

## 5. session_store.py 做了哪些持久化升级？

位置：`src/project_agent/runtime/session_store.py:25-31`、`session_store.py:146-262`

### 5.1 新增校验集合

新增：

- `AGENT_ROLES`
- `AGENT_VERDICTS`

### 5.2 AgentRunRecord 序列化增强

位置：`session_store.py:146-162`

现在会保存：

- `role`
- `readonly`
- `structured_result`
- `verdict`
- `parent_session_id`
- `depth`

### 5.3 AgentStructuredResult 序列化

位置：`session_store.py:165-175`

保存：

- `summary`
- `evidence`
- `touched_files`
- `commands_run`
- `open_questions`
- `verdict`

### 5.4 反序列化校验增强

位置：`session_store.py:178-242`、`session_store.py:245-262`

新增校验：

- role 必须在允许集合中。
- readonly 必须是 bool。
- verdict 必须是 `PASS|FAIL|PARTIAL`。
- parent_session_id 必须是字符串或 None。
- depth 必须是非负整数。
- structured_result 必须是 object。
- structured_result 中列表字段必须是字符串列表。
- 字段长度继续受 `MAX_AGENT_FIELD_CHARS` 限制。

## 6. config.py 和 CLI 有哪些变化？

### 6.1 config.py

位置：`src/project_agent/config.py:65-70`

配置项现在包括：

- `multi_agent_enabled`
- `coordinator_enabled`
- `max_subagents_per_turn`
- `max_subagent_steps`
- `max_worker_result_chars`
- `multi_agent_strict_task_specs`

移除了：

- `allow_recursive_subagents`

原因：当前成熟版明确不支持递归 subagent，不再保留会造成误解的配置占位。

新增环境变量：

```text
PROJECT_AGENT_MULTI_AGENT_STRICT_TASK_SPECS=true|false
```

### 6.2 CLI doctor 输出

位置：`src/project_agent/cli.py:113-120`

`project-agent doctor` 现在会显示：

```text
multi_agent_enabled=True
coordinator_enabled=False
max_subagents_per_turn=4
max_subagent_steps=12
max_worker_result_chars=8000
multi_agent_strict_task_specs=True
multi_agent_roles=explore,plan,worker,verification,generalPurpose
recursive_subagents_supported=False
```

### 6.3 CLI 构造 SubagentTool

位置：`src/project_agent/cli.py:351-378`

现在 CLI 创建 `SubagentTool` 时会传入：

- `default_role="worker"`
- `strict_task_specs=settings.multi_agent_strict_task_specs`
- `parent_depth=0`

这意味着 CLI 入口默认更严格：未显式指定 subagent_type 时按 `worker` 处理，而不是宽泛的通用 Agent。

## 7. 实际怎么使用？

### 7.1 普通 worker

```bash
project-agent run \
  --multi-agent \
  --prompt "Use the agent tool to inspect src/project_agent/runtime/multi_agent.py and summarize risks."
```

模型调用 agent 工具时，如果没有指定 `subagent_type`，默认是 `worker`。

### 7.2 Explore 只读探索

```json
{
  "description": "Explore multi-agent runtime",
  "prompt": "Inspect src/project_agent/runtime/multi_agent.py and list key extension points.",
  "subagent_type": "explore"
}
```

特点：

- 只能读/搜。
- 写工具和命令执行都会被权限策略拒绝。

### 7.3 Plan 只读规划

```json
{
  "description": "Plan runtime refactor",
  "prompt": "Read src/project_agent/runtime/multi_agent.py and propose phases, risks, and verification commands.",
  "subagent_type": "plan"
}
```

特点：

- 只能读/搜。
- 不允许直接实现。

### 7.4 Verification 独立验证

```json
{
  "description": "Verify multi-agent tests",
  "prompt": "Verify tests for tests/unit/test_runtime_multi_agent.py by running pytest and report PASS/FAIL/PARTIAL.",
  "subagent_type": "verification"
}
```

特点：

- 不能写文件。
- 只能执行白名单验证命令，例如 `pytest`、`python -m pytest`、`ruff check`、`black --check`、`git status`、`git diff`。
- 必须输出 verdict。

### 7.5 Coordinator 模式

```bash
project-agent run \
  --coordinator \
  --trace \
  --prompt "Use explore, worker, and verification subagents to review the multi-agent runtime and summarize issues."
```

coordinator 会按阶段模型工作：先探索、再合并规划、再派 worker、最后验证。

## 8. 错误码有哪些？

`agent` 工具现在可能返回：

| error_code | 场景 |
| --- | --- |
| `max_subagents_exceeded` | 单轮超过最大子 Agent 数 |
| `background_not_supported` | 传入 `run_in_background=True` |
| `recursive_subagents_denied` | child agent 尝试继续创建 agent |
| `invalid_agent_request` | 参数类型或必填字段错误 |
| `role_not_allowed` | 未知 role 或 child 请求 coordinator role |
| `task_spec_too_vague` | 任务描述过于模糊 |

## 9. 安全与隔离策略

### 9.1 子 session 隔离

仍然使用：

```text
<parent_session_id>.agent.<agent_id>
```

完整 worker 对话保存在 child session；父 session 只保存摘要和结构化元数据。

### 9.2 worker 输出不可信

所有 `<task-notification>` 中的 worker 内容：

- 会 XML 转义。
- `<result>` 标记为 `trust="untrusted-worker-output"`。
- coordinator prompt 明确禁止执行 worker 文本里的指令。

### 9.3 反递归双保险

- `SubagentTool.run()` 通过 `parent_depth > 0` 拒绝递归。
- `MultiAgentOrchestrator.run_subagent()` 通过 `spec.depth > 1` 再次拒绝。
- worker 工具列表仍会过滤掉 `agent` 工具。

### 9.4 Verification 命令白名单

verification 不是任意命令执行器，只能运行安全验证命令；写工具直接拒绝。

## 10. 测试覆盖情况

本次新增/更新了多类测试，重点覆盖：

位置：`tests/unit/test_runtime_multi_agent.py`

- child session 和 parent `agent_runs`。
- role/default role。
- unknown role rejected。
- lazy prompt rejected。
- recursive subagent rejected。
- explore 写工具被拒绝。
- verification 写工具被拒绝。
- verification unsafe command 被拒绝。
- verification safe command 被允许。
- structured result 解析。
- long result 截断但保持 `<task-notification>` 外壳完整。
- max subagents 限制。
- coordinator 收到 `<task-notification>`。

位置：`tests/unit/test_session_store.py`

- 新 agent schema 持久化。
- invalid role rejected。
- invalid verdict rejected。
- structured_result 字段校验。

位置：`tests/unit/test_config.py`

- `multi_agent_strict_task_specs` 默认值。
- TOML/env/CLI override 优先级。
- 移除 recursive 配置相关断言。

位置：`tests/unit/test_cli.py`

- doctor 输出 roles。
- doctor 输出 recursive unsupported。
- coordinator 仍然能注入 agent tool。
- `/coordinator` 路由仍正常。

最终测试结果：

```text
pytest tests/unit/test_runtime_multi_agent.py tests/unit/test_session_store.py tests/unit/test_config.py tests/unit/test_cli.py
124 passed

pytest tests/unit/test_runtime_agent.py tests/unit/test_permissions_policy.py tests/unit/test_tool_registry.py
43 passed

pytest
296 passed, 3 skipped
```

## 11. 当前边界和限制

已支持：

- 普通 subagent。
- coordinator -> workers。
- 显式 role contract。
- explore / plan 硬只读。
- verification 独立校验。
- 结构化 agent result。
- 结构化 task notification。
- 子 session 隔离。
- 父 session 保存结构化 agent run。
- worker 输出转义和 untrusted 标记。
- 最大 worker 数限制。
- 反递归硬拒绝。
- anti-lazy 派工校验。
- CLI/config/doctor 接入。

仍不支持：

- 真后台 `run_in_background`。
- 真并行 worker。
- recursive subagents。
- swarm/team/mailbox。
- 不同 worker 指定不同模型。
- worker 之间直接通信或读取彼此私有 transcript。

这些限制是有意保留的，避免在 session store 并发、审批并发、trace 顺序、模型客户端并发安全还没完善前引入半成品能力。
