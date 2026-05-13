Mengqing，当前这个上下文管理模块，整体上是在做一件事：                                                                        
                                                                                                                                
  ▎ 在不改业务逻辑的前提下，控制发给模型的消息体积，尽量延缓上下文爆掉；实在太大时，用结构化摘要保留关键信息继续对话。          
                                                                                                                                
  我按“模块功能 -> 具体行为 -> 怎么测效果”给你拆开说。                                                                          
                                                                                                                                
  ---                                                                                                                       
  一、这个上下文管理模块现在具备什么功能

  ---
  1. 统一的上下文管理入口

  文件：
  - src/project_agent/runtime/context_management/manager.py:14
  - src/project_agent/runtime/agent.py:481

  功能

  ContextManager 是总入口。
  在模型调用前，它会统一做：

  1. 微压缩
  2. 预算估算
  3. 自动压缩判断
  4. 极限情况下全量压缩
  5. 生成并返回新的 ContextManagementState

  作用

  你不需要在 runtime 各处手动判断“要不要压缩”，只要把消息交给 ContextManager.prepare_messages(...) 即可。

  ---
  2. 上下文预算估算

  文件：
  - src/project_agent/runtime/context_management/budget.py
  - src/project_agent/core/types.py

  功能

  模块会对当前 message 列表做一个 token 预算估算，产出 BudgetSnapshot，里面至少有：

  - estimated_tokens_used
  - estimated_tokens_limit
  - fill_ratio
  - profile
  - version

  作用

  这是整个压缩系统的判断基础。
  后面的 Tier 2、Tier 3 都是根据 fill_ratio 来决定是否触发。

  当前实现特点

  现在用的是启发式估算，不是模型真实返回 token usage。
  所以它更像“近似预算器”，但足够支撑压缩策略。

  ---
  3. Tier 1：微压缩（Micro Compaction）

  文件：
  - src/project_agent/runtime/context_management/micro_compaction.py:9

  功能

  对历史消息中的 旧 tool 输出 做轻量压缩。

  具体行为

  - 保留最近 N 条 tool result 完整内容
  - 更早的 tool result 不删除，而是改成精简版 JSON
  - 精简后的内容保留：
    - 工具名
    - status
    - content preview
    - error_code
    - retryable
    - elided=True
  - 保留 tool_call_id

  不会压缩什么

  - user message 不动
  - assistant 的自然语言不动
  - 最近的 tool result 保留原文

  作用

  这是最便宜的一层。
  主要目的是：长工具输出很多时，先把旧输出瘦身。

  ---
  4. Tier 2：自动压缩（Auto Compaction）

  文件：
  - src/project_agent/runtime/context_management/auto_compaction.py
  - src/project_agent/runtime/context_management/manager.py:61

  功能

  当上下文接近预算上限时，自动触发更激进的压缩。

  具体行为

  它有一套状态机逻辑：

  4.1 触发阈值

  当 fill_ratio 超过阈值时，触发 auto-compaction。

  4.2 恢复阈值

  为了避免在边界反复抖动，设置了 recover threshold。
  也就是不是一超过就开、一降一点就关，而是有滞回。

  4.3 连续失败计数

  如果自动压缩多次尝试都没有真正减小 prompt，就会累计失败次数。

  4.4 熔断（Circuit Breaker）

  失败次数过多时，进入 circuit_open=True，避免每轮都无意义重试。

  当前实现里“实际压缩”怎么做

  在 manager.py 里，Tier 2 触发后会调用 _trim_to_budget(...)：

  - 不做摘要
  - 直接裁剪消息列表
  - 尽量把 fill_ratio 拉回 <= 1

  作用

  这是“快到上限时的自动保底”。

  ---
  5. Tier 3：全量压缩 / 摘要压缩（Full Compaction）

  文件：
  - src/project_agent/runtime/context_management/summary.py:8
  - src/project_agent/runtime/context_management/manager.py:90

  功能

  当上下文已经超预算，且普通裁剪不够时，生成结构化摘要来保留历史关键信息。

  具体行为

  会生成一个 CompactionSummarySnapshot，里面包括：

  - summary_text
  - intent
  - concepts
  - files
  - errors
  - message_highlights
  - tasks
  - current_focus
  - environment
  - kept_conclusions

  摘要文本目前包含这些段落

  summary.py 现在会组织成：

  1. Intent
  2. Concepts
  3. Files
  4. Errors
  5. Message Highlights
  6. Tasks
  7. Current Focus
  8. Environment / Constraints
  9. Kept Conclusions

  full compaction 触发后会做什么

  1. 用当前消息生成 summary snapshot
  2. 插入一条新的 system summary message
  3. 再保留少量最近消息 tail
  4. 再次 trim，确保最后结果尽量回到预算内
  5. 把 summary snapshot 存进 context_state

  作用

  这是“实在太大时，保命继续聊”的最后一层。

  ---
  6. 上下文状态可持久化

  文件：
  - src/project_agent/core/types.py
  - src/project_agent/runtime/session_store.py

  功能

  上下文管理不是临时变量，而是会持久化到 session 里的。

  主要状态有：

  - BudgetSnapshot
  - AutoCompactionState
  - CompactionSummarySnapshot
  - ContextManagementState

  SessionState 现在包含：
  - messages
  - task_plan
  - context_state

  作用

  这样系统能跨 turn 记住：

  - 上一轮预算是多少
  - 自动压缩失败过几次
  - 是否已经熔断
  - 有没有 full compaction 摘要
  - 当前 profile/version 是什么

  ---
  7. planner / task 模式下也能带着 context_state 跑

  文件：
  - src/project_agent/runtime/agent.py:96
  - src/project_agent/runtime/agent.py:114
  - src/project_agent/runtime/agent.py:372
  - src/project_agent/runtime/agent.py:764

  功能

  现在多 task 执行时，context_state 会在 task 之间传递，不会在 planner 路径丢掉。

  作用

  如果你的 agent 不是单轮问答，而是：
  - 先 task1
  - 再 task2
  - 再 task3

  那每个 task 不会把上下文管理状态重置掉。

  ---
  8. 摘要长度可控

  文件：
  - src/project_agent/runtime/context_management/summary.py:54

  功能

  摘要不是无限长的。
  会根据 max_summary_tokens 做近似长度截断。

  作用

  避免“为了压缩而生成一个更大的 summary”。

  ---
  9. 支持 profile/version 标识

  文件：
  - src/project_agent/runtime/context_management/summary.py:9
  - src/project_agent/runtime/context_management/manager.py:23
  - src/project_agent/config.py

  功能

  上下文管理有 profile 和 version。

  作用

  方便你后面做：
  - 压缩策略升级
  - 不同模型/不同模式用不同 compaction profile
  - 问题排查时知道当前用的是哪套策略

  ---
  二、现在这个模块实际表现出来的效果是什么

  你可以把它理解成这三层防线：

  ---
  第一层：平时先瘦旧工具输出

  如果你连续用了很多工具，旧工具结果会先被压成 preview。

  效果：
  - 消息还在
  - 关键信息还在
  - 但不会把完整大段输出一直塞给模型

  ---
  第二层：快超预算时自动裁剪

  如果 prompt 太大，会自动 trim 一部分消息，尽量回到预算以内。

  效果：
  - 不一定摘要
  - 先用更便宜的裁剪方式压回去

  ---
  第三层：真的撑不住时生成结构化摘要

  如果已经超过预算，会生成“历史压缩摘要 + 最近少量原始消息”。

  效果：
  - 不是直接丢历史
  - 而是保留可恢复的任务/错误/结论/焦点

  ---
  三、这个模块目前还没完全做到的地方

  这个很重要，你测试时要有预期。

  ---
  1. tool / skill 之后的同一 turn 内，还不会再次重新 compact

  也就是：
  - 第一次模型调用前会 compact
  - 但 tool result 追加后，下一次模型调用前没有再次走一遍 ContextManager

  这意味着：
  - 真正最容易爆的场景，其实就是 tool 返回超长文本之后
  - 这一点现在还没彻底闭环

  ---
  2. task system message 目前是在 compaction 之后才插入

  也就是说 task 提示本身没参与预算估算。

  这会导致：
  - 预算是按“未加 task 指令”的 prompt 算的
  - 最终真正发给模型的 prompt 可能比估算时稍大一点

  ---
  3. repository context 还没有完全做成“细粒度 token 预算分配”

  设计上已经考虑了，但你现在的 repo context 还不是最完整形态。

  ---
  四、你该怎么实际测试，看出效果

  我建议你分成 单元测试、日志观察、真实长上下文场景验证 三层来测。

  ---
  A. 先跑现成单元测试，确认机制存在

  1. 测 Tier 2 / Tier 3

  运行：

  pytest tests/unit/test_context_manager.py

  你会看到当前已经有两条关键测试：

  - test_context_manager_auto_compaction_trims_messages_when_budget_exceeded
  - test_context_manager_full_compaction_trims_after_summary_insertion_to_fit_budget

  它们验证的是：
  - Tier2 触发后确实裁剪了消息
  - Tier3 插入 summary 后仍然满足预算

  ---
  2. 测 planner 下的 context_state 传播

  运行：

  pytest tests/unit/test_runtime_agent.py -k context_state

  关键测试：
  - test_agent_runtime_persists_context_state_from_context_manager
  - test_agent_runtime_propagates_context_state_across_planned_tasks

  它们验证的是：
  - 普通路径会保存 context_state
  - 多 task 场景下 context_state 会跨 task 传递

  ---
  B. 直接在 Python 里构造消息，肉眼看压缩前后差异

  这个最直观。

  你可以写一个临时脚本，直接调用 ContextManager.prepare_messages(...)。

  ---
  方案 1：测 Tier 1 微压缩

  目标：
  - 构造很多旧 tool 消息
  - 看哪些被精简成 preview

  你可以测：

  1. 构造 10 条 tool message
  2. 配置 recent_tool_results_keep=2
  3. 调 prepare_messages()
  4. 打印返回消息

  你应该看到：
  - 最近 2 条 tool message 保留原文
  - 更早的 tool message 内容变成带 elided 的 JSON

  你重点看：
  - content 是否被截短
  - tool_call_id 是否还在

  ---
  方案 2：测 Tier 2 自动压缩

  目标：
  - 故意把消息数堆到超过 budget
  - 看返回消息数是否减少

  做法：
  1. 把 context_window_tokens 设得很小，比如 20 或 30
  2. 构造很多 message
  3. 打印：
    - 原始消息数
    - 压缩后消息数
    - prepared_state.latest_budget

  你应该关注：
  - estimated_tokens_used
  - fill_ratio
  - last_compacted_turn
  - fail_streak
  - circuit_open

  如果 Tier2 生效，你会看到：
  - 消息数减少
  - fill_ratio 下降

  ---
  方案 3：测 Tier 3 摘要压缩

  目标：
  - 故意让上下文远超预算
  - 看是否生成 summary message

  做法：
  1. enable_full_compaction=True
  2. enable_auto_compaction=False
  3. context_window_tokens 设得非常小
  4. 构造很多历史消息
  5. 调 prepare_messages()

  你应该看到：
  - 返回的第一条消息是 role="system"
  - 内容里包含：
    - Compaction summary (...)
  - prepared_state.summary_snapshot 不为空

  这就说明 Tier3 触发了。

  ---
  C. 在真实 agent 运行里验证效果

  这个更接近你最终想看到的效果。

  ---
  场景 1：连续长工具输出

  目标：
  - 验证旧工具输出会被微压缩

  做法：
  1. 准备一个会返回很长字符串的 tool
  2. 连续调用多轮
  3. 每轮结束后看 session 里的 messages 或中间日志

  你要看：
  - 旧的 tool message 是否还保留原始长文本
  - 还是已经变成 preview JSON

  ---
  场景 2：把 budget 故意调小

  目标：
  - 更容易触发 Tier2 / Tier3

  做法：
  把配置调得激进一点，例如：

  - context_window_tokens 调小
  - context_trigger_fill_ratio 调低
  - context_recover_fill_ratio 调低
  - context_summary_max_tokens 调小

  这样你很容易在开发环境里看到：
  - auto compaction 频繁触发
  - full compaction 被触发
  - summary snapshot 出现

  ---
  场景 3：planner 多 task 长流程

  目标：
  - 验证 task 间上下文状态真的连续

  做法：
  1. 用 planner 生成多个 task
  2. 每个 task 都制造一些消息增长
  3. 跑完整个流程
  4. 看最终 session 里的 context_state

  你要看：
  - turn_count 是否递增
  - summary 是否被保存
  - auto compaction 状态是否被持续保留

  ---
  五、我建议你怎么“看效果”最直观

  如果你想最快看到效果，我建议按这个顺序：

  ---
  最推荐的 3 个步骤

  第一步：先跑测试确认机制没坏

  pytest tests/unit/test_context_manager.py tests/unit/test_runtime_agent.py

  ---
  第二步：把 context_window_tokens 调得很小

  比如调到一个很小的值，让系统更容易触发压缩。

  然后再跑长消息场景。

  这样你肉眼最容易观察到：
  - 消息被裁剪
  - summary 被注入
  - state 被更新

  ---
  第三步：给 ContextManager.prepare_messages() 加临时调试打印

  比如打印：

  - 原始消息数
  - 微压缩后消息数
  - 初始 budget
  - auto-compaction 后 budget
  - 是否生成 summary
  - 最终消息数

  你会非常清楚地看到整个链路。

  最值得打印的字段是：

  - len(messages)
  - budget.estimated_tokens_used
  - budget.fill_ratio
  - updated_state.auto_compaction.fail_streak
  - updated_state.auto_compaction.circuit_open
  - updated_state.summary_snapshot is not None

  ---
  六、你测试时应该重点观察哪些“正确现象”

  ---
  现象 1：旧 tool 输出变短，但没完全消失

  说明 Tier1 生效。

  ---
  现象 2：消息总数下降 / fill_ratio 下降

  说明 Tier2 生效。

  ---
  现象 3：最前面多出一条 summary system message

  说明 Tier3 生效。

  ---
  现象 4：session reload 后还能拿到 context_state.summary_snapshot

  说明持久化生效。

  ---
  现象 5：planner 多 task 执行后 turn_count 递增

  说明 task 间状态传播生效。

  ---
  七、如果你想做“完整验收”，我建议你测这 5 个场景

  1. 长工具链场景
    - 连续很多 tool result
    - 看旧结果是否变 preview
  2. 接近预算场景
    - budget 调小
    - 看 auto-compaction 是否触发
  3. 超预算场景
    - 历史消息非常多
    - 看 full compaction 是否生成 summary
  4. session 持久化场景
    - 保存 session，再 reload
    - 看 context_state 是否还在
  5. planner 多任务场景
    - 多个 task 连续执行
    - 看 context_state 是否跨 task 传播




context_window_tokens = 200000
context_trigger_fill_ratio = 0.87
context_recover_fill_ratio = 0.82
context_circuit_breaker_failures = 3
context_recent_tool_results_keep = 5
context_tool_result_preview_chars = 400
context_summary_max_tokens = 4000
context_profile = "compact-default"
context_profile_version = "2026-05-12"
enable_auto_compaction = true
enable_full_compaction = true
repository_context_max_tokens = 6000