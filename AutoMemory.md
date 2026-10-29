# Project Agent 长期记忆

长期记忆分为两个独立流程：后台从历史会话提取并合并经验；用户请求开始时召回相关主题并注入模型。模型参数不会因记忆而改变。

## 目录与职责

```text
.project_agent/
  sessions/<session_id>.json     # 原始会话、任务和上下文状态
  memory/
    MEMORY.md                   # 程序生成的活跃主题索引
    topics/<topic>.md            # 正式记忆正文，归档后仍保留
    candidates/<session_hash>.json  # 待合并候选及会话版本
    state.json                  # 主题元数据、已处理版本、遗忘标记
```

只扫描 `topics/` 下的主题 Markdown，候选不会进入召回。主题名使用不超过 64 字符的小写英文 slug，例如 `testing`、`project_preferences`。

**旧目录升级：** 根目录下的旧主题不再参与召回，也不会自动搬移。首次使用新版本前，请将旧主题文件移入 `topics/` 并使用合法主题名；`MEMORY.md` 之后由程序重新生成。旧文件不会被本次代码升级删除。不要把必须执行的规则仅保存在记忆里，应继续使用项目规则文档。

## 从会话生成记忆

`project-agent run` 启动时创建一个后台维护线程，每次最多处理 5 个会话。它只处理已经空闲 30 分钟、包含用户输入和助手正文、尚未处理当前版本的历史会话，并排除当前会话和子 Agent 会话。

会话版本取完整持久化内容的 SHA-256；更新时间来自会话文件。运行时使用会话活动锁，提取和合并的模型调用不会长时间持有会话锁。写入前再次检查活动状态和版本：会话已恢复工作或内容已改变时，本次结果不发布。

记忆扫描使用专用的对话快照，只解析 messages 和生成开关，不恢复 agent_runs、任务计划或上下文管理状态。这些运行字段的格式不会影响有效对话的提取；正常恢复会话时仍严格校验完整运行状态。

1. `MemoryExtractor` 接收最近最多 60000 字符的会话材料和已有主题名，输出最多 10 条候选。提取长期偏好、项目约束、可复用流程和已验证经验；不保存临时进度、猜测和凭证。
2. 每条候选包含 topic、content、evidence、source_session_id、created_at。evidence 必须是实际传入模型的输入材料中的连续原文片段，不接受改写或模糊匹配。不匹配的候选单独丢弃并计入 rejected，其余候选继续处理；日志只记录数量，不输出原文。原文匹配只能验证来源存在，不能证明模型归纳一定正确。
3. 候选通过结构、长度、路径名和明显凭证检查后保存到 candidates。失败的合并可以复用候选，避免再次提取。
4. `MemoryConsolidator` 将候选按主题与已有正文合并。重复内容合并，明确纠正更新旧事实，无法确定的冲突返回 deferred 并保留候选。
5. 程序校验模型返回的主题集合和正文，使用原子替换保存主题、状态和索引。主题来源会话保存在 state.json 的 sources 中，原始依据仍可在会话中查看。
6. 全部通过校验的候选处理成功才记录已处理版本并删除该候选批次。空提取或所有候选都因原文不匹配被丢弃时，也记录该版本已处理，避免启动时重复提取；会话内容变化产生新版本后会再次处理。模型请求或响应结构错误仍算失败，不标记成功。

处理过程有跨进程维护锁，状态更新有短期文件锁，并检查合并期间主题是否被修改，避免静默覆盖新内容。多个文件的发布不构成数据库事务；进程中断后未完成的候选可重试，索引会在下一次维护或构建时重建。

后台任务随 CLI 进程退出而停止，不是常驻服务。很短的单次命令可能在后台完成前退出；需要确定完成时，使用同步的 `memory refresh`。本轮刚结束的会话通常在下次启动时处理。

## 使用与恢复

每个用户回合只构建一次 MemoryContext，同一回合内复用：

1. 更新归档状态并读取活跃索引。
2. 根据当前输入、近期用户消息、文件标题和描述生成候选清单，优先匹配内容、固定主题和近期使用主题。
3. 召回模型选择最多 3 个主题；如果没有选中活跃主题，再搜索归档主题。
4. 每个主题最多读取 3000 字符，并限制完整记忆提示词预算；放不下的主题整体移除。
5. 以 system 消息加入上下文。提示词明确这些是可能过时的历史依据，当前用户要求和已验证事实优先。
6. 上下文压缩优先保留独立预算内的 Memory 和最新消息；极小预算仍可能裁掉 Memory。
7. 只有主题正文实际保留在请求中、模型调用成功返回，才刷新 last_recalled_at。被裁掉、仅被扫描或失败的模型请求不刷新。它代表成功送入模型，不代表模型一定采用。

归档主题成功送入模型后恢复为 active，并重新加入 MEMORY.md。每轮最多记录一次召回，记忆写入失败不会使主任务失败。

## 闲置归档与遗忘

主题元数据包含 created_at、updated_at、last_recalled_at、status、pinned、sources。

- 默认 30 天没有召回的主题标记 archived，从活跃清单和索引中移出，正文仍留在 topics。
- 新建、内容更新或成功召回都会获得新的保留时间；单纯扫描、索引重建和内容未变化的合并不会延长保留时间。
- pinned=true 的主题不因闲置归档。pin 已归档主题也会将其恢复。
- forget 删除该主题正文、清理候选中的对应条目，并保存主题名的遗忘标记，阻止其自动生成。
- 用户通过 remember 明确重新保存同主题时，可以解除遗忘标记。

遗忘标记按主题名生效，不是语义级隐私删除。原始会话不在 forget 的删除范围内；同一信息若以其他主题名重新提取，仍有再次生成的可能。

## 明确要求记住

当用户明确说“记住”时，主 Agent 可调用 `remember` 工具，提供 topic、content、evidence 和可选的 pinned。工具复用相同的合并和保存流程；冲突暂缓时返回错误供用户澄清，不假装已保存。此工具属于 WRITE 类别，经过已有权限策略；只读沙箱或 plan 模式不注册该工具，也不启动后台生成。

## 配置

配置文件使用 `[project_agent]`：

```toml
[project_agent]
memory_enabled = true
memory_use_enabled = true
memory_generate_enabled = true
memory_idle_minutes = 30
memory_max_sessions_per_pass = 5
memory_max_unused_days = 30
memory_prompt_max_chars = 12000
memory_max_manifest_files = 50
memory_max_relevant_files = 3
memory_max_relevant_file_chars = 3000
memory_entrypoint_max_lines = 200
memory_entrypoint_max_bytes = 25000
```

对应环境变量为 `PROJECT_AGENT_` 加配置名大写，例如 `PROJECT_AGENT_MEMORY_MAX_UNUSED_DAYS=60`。优先级仍为调用覆盖值 > 环境变量 > TOML > 默认值。

use 控制召回，generate 控制后台生成和 remember 工具，两者独立。关闭总开关或生成开关期间保存的会话会持久标记为不参与提取，之后开启生成也不会追溯提取该会话；要重新参与请新建会话。

记忆提示词预算还受上下文窗口大小约束。提取、合并和召回暂时共用模型配置，没有独立向量数据库。未配置真实模型时，Mock 提取返回空列表，不能用于评估语义记忆质量。

## CLI

```bash
# 同步处理符合空闲条件的历史会话
project-agent memory refresh

# 跳过空闲等待，仍跳过活跃、已处理、排除的会话
project-agent memory refresh --force

# 查看已登记主题及归档、固定状态
project-agent memory list

# 固定或取消固定主题
project-agent memory pin testing
project-agent memory pin testing --unpin

# 删除主题并阻止同主题自动重新生成
project-agent memory forget testing
```

refresh 输出 extracted、rejected、merged、deferred、archived、skipped、failed 计数；rejected 表示本次新提取中原文不匹配而丢弃的候选数，不计为 failed。有失败时退出码为 1。后台异常只记日志，不阻断正常任务。明显凭证的规则检查不等于完整 DLP，仍不应主动向记忆中提交敏感信息。
