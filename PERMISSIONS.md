Mengqing，本次改动我分成了 4 块：

  1. 新增了 Phase 5 的权限核心

  1.1 权限模型与数据结构

  新增了权限相关类型，定义了模式、决策结果、规则、请求与结果对象：

  - src/project_agent/runtime/permissions/types.py
    - PermissionMode：default / accept_edits / plan / dont_ask
    - PermissionDecision：allow / ask / deny
    - PermissionRule / PermissionRequest / PermissionOutcome

  这部分是整个 Phase 5 的基础数据模型。

  1.2 权限决策引擎

  核心逻辑在：

  - src/project_agent/runtime/permissions/policy.py:31

  这里实现了统一的 PermissionPolicy.evaluate()，执行顺序是：

  1. 请求归一化
  2. 模式硬限制
  3. deny 规则
  4. ask 规则
  5. 内建安全检查
  6. allow 规则
  7. 模式兜底
  8. fail-closed

  关键点：
  - plan 模式下禁止 write/execute：policy.py:102
  - 保护路径禁止写：policy.py:162
  - 危险命令前缀禁止执行：policy.py:173
  - 默认安全命令 allowlist：policy.py:24
  - 非交互场景遇到 ask 默认不放行，走 fail-closed

  1.3 路径级保护

  新增路径辅助逻辑：

  - src/project_agent/runtime/permissions/paths.py

  默认保护这些路径不能写：
  - .git/**
  - .project_agent/**
  - .claude/**

  这是通过 is_protected_path(...) 做的。

  ---
  2. 把权限系统接进了现有运行时

  2.1 配置接入

  在配置里新增了两个设置：

  - src/project_agent/config.py:44
    - permission_mode
    - permission_rules_file

  加载逻辑在：
  - src/project_agent/config.py:262
  - src/project_agent/config.py:268

  并且新增了模式校验：
  - src/project_agent/config.py 里的 _parse_permission_mode(...)

  也就是说，现在可以通过配置切换权限模式，并加载规则文件。

  2.2 CLI 构建权限策略

  在 CLI 启动时会构造权限策略对象：

  - src/project_agent/cli.py:342

  _build_permission_policy(settings) 会：
  - 根据 permission_mode 建策略
  - 如果配置了 permission_rules_file，就加载规则文件

  2.3 运行时拦截工具调用

  最关键的接入点在：

  - src/project_agent/runtime/agent.py:583

  这里的 _run_tool_call(...) 现在会先：
  1. 找到 tool
  2. 构造 PermissionRequest
  3. 调用 permission_policy.evaluate(...)
  4. 根据结果：
    - ALLOW：继续执行
    - ASK：如果有交互审批 callback 就确认，否则返回 permission_required
    - DENY：直接返回 permission_denied

  也就是说，现在所有工具调用都经过统一权限网关，不再是各工具各管各的。

  2.4 交互审批

  CLI 里加了审批回调：

  - src/project_agent/cli.py:232

  在交互模式下，会弹：
  - Approve action? ...

  在 --prompt 这种非交互场景下，不会审批，直接 fail-closed。

  对应逻辑：
  - src/project_agent/cli.py:133
  - src/project_agent/cli.py:154
  - src/project_agent/cli.py:268

  ---
  3. 给工具补了权限分类

  为了让权限引擎知道“这个工具是读、写、搜索还是执行”，我给 Tool 协议和具体工具加了 permission_category。

  3.1 Tool 协议扩展

  - src/project_agent/core/interfaces.py
    - Tool.permission_category

  3.2 具体工具分类

  已经补到这些工具里了：

  - read_file → READ
  - list_files → READ
  - search_code → SEARCH
  - write_file → WRITE
  - edit_file → WRITE
  - run_command → EXECUTE
  - echo → READ

  相关文件：
  - src/project_agent/runtime/local_tools/filesystem.py
  - src/project_agent/runtime/local_tools/search.py
  - src/project_agent/runtime/local_tools/command.py
  - src/project_agent/runtime/tools.py

  ---
  4. 加了可追踪结果与测试

  4.1 trace/audit 信息

  我没有额外造一个大而全的审计系统，而是先把权限决策写进 trace：

  - src/project_agent/core/types.py
    - AgentTraceStep 新增：
        - permission_decision
      - reason_code

  运行时写入位置：
  - src/project_agent/runtime/agent.py:293
  - src/project_agent/runtime/agent.py:419

  这样你开 --trace 时，能看到权限相关原因码。

  4.2 新增/更新测试

  新增：
  - tests/unit/test_permissions_policy.py
  - tests/unit/test_permissions_paths.py

  更新：
  - tests/unit/test_config.py
  - tests/unit/test_runtime_agent.py
  - tests/unit/test_cli.py
  - tests/unit/test_interfaces.py
  - tests/unit/test_tool_registry.py

  测试结果：
  - 91 passed

  ---
  你怎么测

  我建议你按 3 层来测：单元、CLI 非交互、CLI 交互。

  ---
  一、先跑自动化测试

  在项目根目录执行：

  python -m pytest "tests/unit/test_permissions_paths.py" "tests/unit/test_permissions_policy.py" "tests/unit/test_config.py"
  "tests/unit/test_runtime_agent.py" "tests/unit/test_cli.py" "tests/unit/test_tools_run_command.py"
  "tests/unit/test_interfaces.py" "tests/unit/test_tool_registry.py"

  预期：
  - 全部通过
  - 我这边结果是 91 passed

  如果你要跑全量：
  python -m pytest

  ---
  二、测试不同 permission mode

  你可以在配置文件里加：

  [project_agent]
  permission_mode = "default"

  或者改成：
  - "accept_edits"
  - "plan"
  - "dont_ask"

  1) default 模式

  预期：
  - 读/搜索直接允许
  - 写文件、执行命令会要求审批
  - 如果是 --prompt 非交互执行，则会 fail-closed

  可以测：

  project-agent run --prompt "请执行一个写文件操作"

  预期：
  - 不会静默写
  - 会返回权限要求/拒绝信息

  2) accept_edits 模式

  预期：
  - 写操作允许
  - 命令执行仍然受限/需审批

  3) plan 模式

  预期：
  - 只允许读和搜索
  - 写/执行被拒绝

  4) dont_ask 模式

  预期：
  - 没有显式 allow 的写/执行直接拒绝
  - 不会进入审批

  ---
  三、测试保护路径

  重点验证下面这些路径不能写：

  - .git/config
  - .project_agent/...
  - .claude/...

  你可以直接构造一个会尝试写这些路径的请求，或者通过模型提示诱导写入。

  期望行为：
  - 返回 permission_denied
  - reason_code 类似 permission_protected_path

  这个逻辑在：
  - src/project_agent/runtime/permissions/policy.py:162

  ---
  四、测试命令保护

  默认危险命令前缀会被拒绝：

  - rm
  - curl
  - wget
  - git reset --hard

  逻辑在：
  - src/project_agent/runtime/permissions/policy.py:18
  - src/project_agent/runtime/permissions/policy.py:173

  你可以重点测：

  应拒绝

  project-agent run --prompt "执行 rm -rf tmp"

  应允许或更宽松

  git status、git diff 在默认 allowlist 中：
  - src/project_agent/runtime/permissions/policy.py:24

  ---
  五、测试交互审批

  进入交互模式：

  project-agent run

  然后输入一个会触发写操作或命令执行的请求。

  预期：
  - CLI 会弹：
    - Approve action? ...
  - 你输入 y 才继续
  - 输入 n 会拒绝

  审批回调位置：
  - src/project_agent/cli.py:232

  ---
  六、测试规则文件 permission_rules_file

  你可以在配置里加：

  [project_agent]
  permission_mode = "default"
  permission_rules_file = "permission-rules.toml"

  然后新建 permission-rules.toml，例如：

  [[rule]]
  action = "deny"
  tool_name = "run_command"
  reason = "block all commands"

  [[rule]]
  action = "ask"
  tool_name = "write_file"
  reason = "manual approval for writes"

  规则加载逻辑：
  - src/project_agent/runtime/permissions/policy.py:236

  你可以验证：
  - deny 优先于 allow
  - ask 优先于 allow
  - 即使写了 allow，也不能覆盖内建保护路径和危险命令 deny

  ---
  我建议你重点验收的 6 个场景

  1. default 下普通读文件能通过
  2. default 下写文件在 --prompt 下被拒绝/要求审批
  3. interactive 下写文件会弹确认
  4. 写 .git/config 一定被拒绝
  5. 执行 rm / curl 一定被拒绝
  6. 自定义规则文件能生效，且不能绕过内建安全 deny

  ---
  如果你要，我下一条可以直接给你一份可复制的：
  1. config.toml
  2. permission-rules.toml
  3. 一组手工验收命令列表


  每条 [[rule]] 支持这些字段：

  - action: deny / ask / allow
  - tool_name: 比如 write_file、edit_file、run_command
  - tool_category: read / write / search / execute
  - path_prefix: 相对项目根目录的路径前缀
  - command_prefix: 命令前缀数组，比如 ["git", "status"]
  - reason: 原因说明

  注意：
  - 内建安全检查依然生效，不能靠 allow 绕过 .git / .project_agent / .claude 写保护
  - 危险命令前缀也有内建 deny

  ---
  2）怎么配置 permission_mode

  你现在是通过配置文件里的 [project_agent] 段来配。

  对应代码在：
  - src/project_agent/config.py:44
  - src/project_agent/config.py:262

  可用值现在是：

  - default
  - accept_edits
  - plan
  - dont_ask

  示例配置

  [project_agent]
  permission_mode = "default"
  permission_rules_file = ".project_agent/permission-rules.toml"

  ---
  3）配置文件在哪里？

  当前实现里，配置文件不是固定路径自动发现，而是你在启动时通过 --config 指定。

  对应代码：
  - src/project_agent/cli.py:29
  - src/project_agent/cli.py:48
  - src/project_agent/config.py:48

  用法示例

  假设你在项目根目录放一个 config.toml：

  [project_agent]
  permission_mode = "default"
  permission_rules_file = ".project_agent/permission-rules.toml"

  启动时这样用：

  project-agent --config ./config.toml run

  或者：

  project-agent --config ./config.toml run --prompt "帮我检查当前项目"

  ---
  4）如果不用配置文件，也可以用环境变量

  支持这两个环境变量：

  PROJECT_AGENT_PERMISSION_MODE
  PROJECT_AGENT_PERMISSION_RULES_FILE

  例如：

  export PROJECT_AGENT_PERMISSION_MODE=default
  export PROJECT_AGENT_PERMISSION_RULES_FILE=.project_agent/permission-rules.toml

  Windows bash 下同样可以这样设。

  ---
  5）我建议你的落地方式

  文件放置建议

  项目根目录下放：

  - config.toml
  - .project_agent/permission-rules.toml

  config.toml

  [project_agent]
  permission_mode = "default"
  permission_rules_file = ".project_agent/permission-rules.toml"

  启动命令

  project-agent --config ./config.toml run

  ---
  6）不同 mode 的含义

  default

  - 读/搜索：允许
  - 写/执行：通常 ask
  - 非交互下 ask 会 fail-closed

  accept_edits

  - 写文件/编辑：更宽松
  - 执行命令：仍受控

  plan

  - 只允许读和搜索
  - 禁止写和执行

  dont_ask

  - 不弹审批
  - 没被明确允许的写/执行直接拒绝

  ---
  如果你要，我下一条可以直接给你：
  1. 一份完整可复制的 config.toml
  2. 一份更严格版 permission-rules.toml
  3. 一组手工测试命令列表