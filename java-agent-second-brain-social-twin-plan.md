# 组合 B：第二大脑 + 社交分身（Java 落地方案）

> 目标：构建一个 **Java 技术栈** 的 AI Agent 项目，融合 **第二大脑** 与 **社交分身** 两种能力，形成一个能理解任务、管理沟通、跟踪承诺、生成摘要的个人执行型 Agent。

---

## 1. 项目定位

### 1.1 一句话定义

这是一个：

**能理解你的任务、上下文、关系优先级，并主动帮你管理“事情 + 沟通”的个人执行型 Agent。**

它不只是聊天机器人，而是：

- 帮你从自然语言中提取待办、提醒和承诺
- 帮你分析消息是否值得优先回复
- 帮你生成合适语气的回复建议
- 帮你做每日/每周的任务与沟通摘要
- 帮你形成长期记忆和联系人画像

---

## 2. 产品命名建议

可选名字：

- MindMate
- ExecTwin
- InnerCircle Agent
- Loop
- Socius

### 推荐名

**ExecTwin：你的第二大脑 + 社交执行分身**

---

## 3. 核心产品定义

### 3.1 它解决什么问题

很多人的问题不是信息不够，而是：

- 待办分散在聊天、邮件、脑子里
- 忘记回复重要的人
- 事情知道要做，但没有拆解和推进
- 消息太多，不知道哪些先回
- 工作和生活的沟通节奏失控
- 每天很忙，但缺少掌控感

这个项目要解决的是：

**让 AI 帮用户持续管理任务流和沟通流。**

---

## 4. 两条核心能力主线

### 4.1 第二大脑

功能包括：

- 从自然语言里提取任务、提醒、目标、约定
- 自动归档、分类、拆解、排序
- 跟踪截止时间和依赖关系
- 提供每日/每周摘要
- 帮用户“记住”和“推进”

### 4.2 社交分身

功能包括：

- 汇总不同渠道的消息
- 判断优先级和是否应该回复
- 生成不同语气的回复建议
- 追踪未回复联系人
- 识别承诺、行动项、会议 follow-up

---

## 5. 目标用户与 MVP 场景

### 5.1 目标用户

优先推荐面向以下用户：

- 独立开发者
- 产品经理 / 运营
- 创作者 / 自媒体
- 小团队负责人
- 消息很多、任务碎片化严重的人

### 5.2 MVP 核心场景

第一版严格控制在 3 个核心场景内。

#### 场景 1：聊天转任务

用户输入：

> 下周三前把 Agent demo 做完，并提醒我周一联系设计同学。

系统自动：

- 创建任务
- 识别截止时间
- 拆子任务
- 添加提醒
- 记录相关联系人

#### 场景 2：消息优先级与回复建议

导入一条消息后，系统判断：

- 哪些必须回
- 哪些可以稍后回
- 哪些只是 FYI
- 哪些消息带行动项

并输出：

- 优先级
- 推荐回复
- 是否需要 follow-up

#### 场景 3：每日简报

每天固定时间生成：

- 今天要做的重点
- 哪些人没回
- 哪些任务快到期
- 哪些承诺需要兑现

---

## 6. 为什么用 Java 是合理的

你明确要求 Java，这完全可行，而且对于这个项目来说是合理的长期选择。

### 6.1 Java 的优势

- **Spring Boot 生态成熟**，适合做 API、调度、集成
- **企业集成能力强**：数据库、Webhook、消息平台、OAuth、邮件都成熟
- **类型系统强**，适合复杂业务模型和结构化输出
- **可维护性高**，适合长期演进
- **适合做服务型 Agent**，而不只是 demo 脚本

### 6.2 当前主流 Java AI 技术路线

推荐采用：

- Spring Boot 3
- Spring AI
- PostgreSQL + pgvector
- Redis
- Quartz Scheduler
- OpenTelemetry / Micrometer
- Langfuse（观测 Agent 行为）

### 6.3 推荐技术栈结论

> **Spring Boot + Spring AI + PostgreSQL + Redis + Quartz + OpenTelemetry**

这是当前足够主流、稳定、可扩展的 Java AI Agent 方案。

---

## 7. 产品功能拆分

### 7.1 模块一：Inbox / 统一输入层

所有信息先进入统一收件箱。

#### 输入来源

- Web 输入
- 手动粘贴聊天记录
- Telegram / Slack / Discord Webhook
- 邮件解析
- 日历事件同步
- 后续扩展 WhatsApp / 飞书 / 企业微信

#### 统一输入结构示例

```json
{
  "source": "telegram",
  "sourceThreadId": "abc",
  "sourceMessageId": "msg_123",
  "senderId": "u_001",
  "senderName": "Alice",
  "content": "下周前把方案给我，另外你记得回复 Bob",
  "timestamp": "2026-04-07T20:00:00+08:00"
}
```

---

### 7.2 模块二：任务抽取与第二大脑

#### 职责

从输入中抽取：

- 待办
- 截止时间
- 提醒需求
- 相关人
- 优先级
- 项目归属
- 承诺 / 约定

#### 输出结构示例

```json
{
  "tasks": [
    {
      "title": "完成方案",
      "dueAt": "2026-04-14T18:00:00+08:00",
      "priority": "HIGH",
      "project": "Agent Demo",
      "contacts": ["Bob"]
    }
  ],
  "reminders": [
    {
      "content": "回复 Bob",
      "remindAt": "2026-04-08T10:00:00+08:00"
    }
  ]
}
```

#### 能力要求

- 自然语言任务解析
- 时间表达解析
- 自动打标签
- 去重
- 任务状态流转
- 任务摘要

---

### 7.3 模块三：社交分身

#### 职责

把消息变成可处理的“关系与行动流”。

#### 能力要求

- 消息优先级评分
- 判断是否需要回复
- 识别是否带请求 / 承诺 / 问题
- 判断回复时机
- 生成回复草稿
- 语气切换

#### 回复风格档位

- 简洁专业
- 友好随和
- 正式商务
- 轻松熟人
- 延迟回复型（例如“先确认后再回”）

#### 输出示例

```json
{
  "replyNeeded": true,
  "priority": "HIGH",
  "reason": "对方明确提出交付请求，且有时间要求",
  "suggestedReply": "收到，我会在下周前给你一版完整方案。如果中间有调整我也会同步你。",
  "followUpNeeded": true
}
```

---

### 7.4 模块四：每日 / 每周简报

#### 每日简报内容

- 今日重点任务 Top 3
- 快到期任务
- 今日应回复联系人
- 未完成承诺
- 今日会议 / 事件
- 风险提醒

#### 每周简报内容

- 本周完成任务
- 延迟任务
- 沟通热点联系人
- 最常见打断源
- 下周重点建议

---

### 7.5 模块五：长期记忆

#### 长期记忆保存内容

- 用户常见项目
- 重要联系人
- 沟通风格偏好
- 工作节奏习惯
- 常用回复风格
- 经常被延误的事项类型

#### 示例

- Bob 是高优先级合作人
- 用户更喜欢简洁直接的回复风格
- 每周三常有例会
- 用户不喜欢晚上 23:00 后被提醒

---

## 8. Java 技术栈建议

### 8.1 后端框架

**Spring Boot 3.x**

推荐模块：

- `spring-boot-starter-web`
- `spring-boot-starter-validation`
- `spring-boot-starter-data-jpa`
- `spring-boot-starter-security`（后续）
- `spring-boot-starter-actuator`
- `spring-boot-starter-cache`
- `spring-boot-starter-aop`
- `spring-boot-starter-quartz`

### 8.2 AI 集成

**Spring AI**

用途：

- 对接 OpenAI / Anthropic / Azure OpenAI / Ollama
- Prompt 管理
- Tool Calling
- Embedding
- Vector Store 对接

为什么选它：

- 比手搓 SDK 管理更舒服
- 比冷门 Java Agent 框架更主流
- 与 Spring 体系整合自然

### 8.3 数据库

**PostgreSQL**

原因：

- pgvector 生态更好
- JSONB 非常适合 AI 项目
- 复杂查询舒服
- AI 项目很适合 Postgres 一把梭

#### 向量检索

**pgvector**

用于：

- 长期记忆
- 语义检索
- 联系人上下文召回

### 8.4 缓存与短期状态

**Redis**

用途：

- Session 上下文缓存
- Rate limit
- 临时任务状态
- 消息去重
- 最近活跃联系人缓存

### 8.5 定时调度

**Quartz**

用途：

- 每日简报
- 定时提醒
- 未回复催办
- 定时同步消息

> MVP 早期也可以先用 Spring Scheduler，但如果目标是做真正的任务调度型 Agent，Quartz 更适合。

### 8.6 ORM

**Spring Data JPA + Hibernate**

> 如果后期更强调 SQL 控制，可以再考虑 jOOQ。MVP 阶段建议先 JPA。

### 8.7 可观测性

推荐组合：

- Micrometer
- OpenTelemetry
- Prometheus
- Grafana
- Langfuse

#### Langfuse 作用

- Prompt tracing
- Tool call tracing
- Token / latency 统计
- 对话链路观测
- 调试模型行为

### 8.8 消息接入建议顺序

1. 先做 Web UI / REST API
2. 再接 Telegram Bot API
3. 再接 Slack / Discord

> 不要一开始就接很多平台。

---

## 9. 整体系统架构

### 9.1 架构原则

建议采用：

**分层 + 可扩展模块化单体**

不要一上来拆微服务。

### 9.2 架构图

```text
[Frontend / IM Connectors / Webhook]
                |
                v
        [Inbox API Layer]
                |
                v
      [Orchestration / Agent Service]
        |         |          |
        |         |          |
        v         v          v
 [Task Brain] [Social Brain] [Memory Service]
        |         |          |
        +---------+----------+
                  |
                  v
            [LLM Gateway]
                  |
                  v
      [PostgreSQL / pgvector / Redis]
                  |
                  v
       [Quartz Jobs / Notification Service]
```

### 9.3 分层说明

#### API 层

- REST API
- Webhook 接入
- Auth
- DTO 校验

#### Application 层

- 用例编排
- 事务边界
- 任务流转
- Agent 调用入口

#### Domain 层

核心对象：

- Task
- Contact
- Conversation
- Reminder
- Memory
- MessageInsight

#### Infrastructure 层

- LLM Provider
- Redis
- PostgreSQL
- Vector Search
- Telegram / Slack Connector
- Quartz Jobs

---

## 10. Agent 设计原则

### 10.1 不要做成“一个大 Prompt”

这个项目不要做成一个“大一统提示词机器人”，而要拆成多个明确职责的 Agent / Service。

### 10.2 推荐的角色拆分

#### A. Intake Agent

负责理解输入内容，判断：

- 这是任务？
- 这是消息？
- 这是提醒？
- 这是信息记录？
- 这是要回复？

#### B. Task Extraction Agent

负责：

- 任务抽取
- 时间解析
- 优先级推断
- 项目归属
- 联系人关联

#### C. Social Analysis Agent

负责：

- 消息意图分析
- 是否需要回复
- 优先级评分
- 回复建议生成
- 沟通风险判断

#### D. Summary Agent

负责：

- 每日 / 每周摘要
- 汇总风险
- 给出行动建议

#### E. Memory Retrieval Service

可以不做成 LLM Agent，而是服务模块：

- 召回联系人画像
- 召回历史任务
- 召回用户偏好
- 召回近期相关对话

### 10.3 这样拆的好处

- 更易调试
- 更容易替换 Prompt
- 每个模块输入输出清晰
- 后续可做 A/B Test
- 更适合 structured output

---

## 11. Structured Output 设计

Java Agent 项目要稳定，必须采用结构化输出。

### 11.1 任务抽取输出 DTO

```java
public record TaskExtractionResult(
    List<ExtractedTask> tasks,
    List<ExtractedReminder> reminders,
    List<String> mentionedContacts,
    String summary
) {}
```

```java
public record ExtractedTask(
    String title,
    String description,
    String priority,
    String dueAt,
    String project,
    List<String> contacts,
    boolean needsFollowUp
) {}
```

### 11.2 社交分析输出 DTO

```java
public record SocialAnalysisResult(
    boolean replyNeeded,
    String priority,
    String sentiment,
    String intentType,
    String reason,
    String suggestedReply,
    boolean followUpNeeded,
    String recommendedFollowUpAt
) {}
```

### 11.3 实践建议

- 使用 Spring AI 或模型原生 JSON Schema / Tool Calling 能力
- 尽量让模型直接输出 JSON
- 再将 JSON 映射为 DTO

---

## 12. 数据模型设计

### 12.1 User

```java
class User {
    UUID id;
    String displayName;
    String timezone;
    String preferredReplyStyle;
    boolean summaryEnabled;
}
```

### 12.2 Contact

```java
class Contact {
    UUID id;
    UUID userId;
    String name;
    String channel;
    String externalId;
    String relationshipType;
    Integer priorityScore;
    String notes;
}
```

### 12.3 ConversationMessage

```java
class ConversationMessage {
    UUID id;
    UUID userId;
    UUID contactId;
    String source;
    String sourceMessageId;
    String role;
    String content;
    Instant sentAt;
    boolean replyNeeded;
    boolean replied;
}
```

### 12.4 TaskItem

```java
class TaskItem {
    UUID id;
    UUID userId;
    String title;
    String description;
    String status;
    String priority;
    Instant dueAt;
    String project;
    UUID relatedContactId;
    Instant createdAt;
    Instant updatedAt;
}
```

### 12.5 Reminder

```java
class Reminder {
    UUID id;
    UUID userId;
    UUID taskId;
    String reminderType;
    Instant remindAt;
    String status;
}
```

### 12.6 MemoryEntry

```java
class MemoryEntry {
    UUID id;
    UUID userId;
    String memoryType;
    String content;
    String metadataJson;
    Instant createdAt;
}
```

### 12.7 DailyDigest

```java
class DailyDigest {
    UUID id;
    UUID userId;
    LocalDate digestDate;
    String content;
    Instant generatedAt;
}
```

---

## 13. 记忆系统设计

### 13.1 短期记忆

放 Redis / DB 中最近 N 条：

- 最近几轮消息
- 最近任务变化
- 最近联系人互动

### 13.2 长期记忆

放 PostgreSQL + pgvector：

- 联系人画像
- 用户偏好
- 历史项目背景
- 沟通习惯总结
- 常见承诺模式

### 13.3 典型召回查询

- “Bob 以前通常是什么语气沟通？”
- “最近和 Alice 有哪些未完成事项？”
- “我上周答应过谁什么事？”
- “用户通常怎么回复合作伙伴？”

---

## 14. 核心业务流程

### 14.1 流程 A：新消息进入

```text
接收消息
 -> 去重
 -> 联系人匹配
 -> SocialAnalysisAgent 分析
 -> 判断是否需要生成回复建议
 -> 若包含行动项，再触发 TaskExtractionAgent
 -> 存储消息、任务、分析结果
 -> 更新联系人画像
```

### 14.2 流程 B：用户输入自然语言任务

```text
接收自然语言
 -> IntakeAgent 分类
 -> TaskExtractionAgent 抽取任务
 -> 解析时间
 -> 存库
 -> 创建提醒
 -> 返回任务卡片
```

### 14.3 流程 C：每日摘要

```text
定时任务触发
 -> 查询今日任务 / 未回复消息 / 快到期事项
 -> 召回近期记忆
 -> SummaryAgent 生成摘要
 -> 存档 + 推送
```

---

## 15. API 设计建议

### 15.1 Tasks

- `POST /api/tasks/parse`  
  输入自然语言，返回抽取结果
- `POST /api/tasks`  
  创建任务
- `GET /api/tasks/today`
- `GET /api/tasks/upcoming`
- `PATCH /api/tasks/{id}/status`

### 15.2 Messages

- `POST /api/messages/import`
- `POST /api/messages/analyze`
- `GET /api/messages/needs-reply`
- `POST /api/messages/{id}/suggest-reply`

### 15.3 Digests

- `POST /api/digests/generate`
- `GET /api/digests/today`

### 15.4 Memories

- `GET /api/memories/search`
- `POST /api/memories/rebuild`

### 15.5 Contacts

- `GET /api/contacts`
- `GET /api/contacts/{id}`
- `PATCH /api/contacts/{id}`

---

## 16. Prompt / Agent 设计原则

### 16.1 每个 Agent Prompt 必须写清楚

- 角色
- 任务边界
- 输入结构
- 输出 JSON 结构
- 规则
- 禁止事项

### 16.2 Task Extraction Agent Prompt 要点

职责：

- 找任务
- 找时间
- 找联系人
- 找优先级
- 不做闲聊

规则：

- 没有明确任务，不要臆造任务
- 时间不确定时返回 `null`，并标记 `needsClarification`
- 联系人必须来自输入或记忆，不要猜

### 16.3 Social Analysis Agent Prompt 要点

规则：

- 判断是否需要回复
- 判断急迫程度
- 生成回复建议
- 不能编造事实
- 不得承诺用户没有确认的事情
- 对高风险消息只输出“建议人工处理”

#### 高风险消息示例

- 法律 / 医疗 / 财务承诺
- 情绪冲突
- 合同变更
- 对外报价
- 敏感私人关系

> 这一点非常关键，否则“社交分身”很容易翻车。

---

## 17. 安全边界

### 17.1 MVP 只做建议，不自动发送

MVP 阶段：

- 只生成回复草稿
- 不自动代表用户发消息
- 不自动接受 / 承诺事项

### 17.2 高风险场景必须人工确认

包括：

- 金额、报价、合同
- 负面反馈
- 关系敏感对象
- 重要工作承诺
- 带情绪冲突的回复

### 17.3 数据隐私

- 敏感消息加密存储
- 日志脱敏
- 模型调用前做 PII masking（后续可加）
- 提供 memory 删除能力

---

## 18. 开发路线图

### Phase 1：MVP 核心闭环

#### 目标

先让系统能：

- 理解任务
- 分析消息
- 生成每日摘要

#### 功能范围

- Spring Boot 项目骨架
- PostgreSQL + Redis
- Spring AI 接大模型
- Task parsing
- Message analysis
- Reply suggestion
- Daily digest
- Swagger API

#### 不做

- 多平台消息同步
- 自动发消息
- 复杂向量召回
- 多 Agent 协调器
- 多租户

#### 验收标准

- 输入一句自然语言能建任务
- 导入一条消息能给回复建议
- 能生成今日简报

---

### Phase 2：记忆与联系人画像

#### 功能范围

- 联系人画像提取
- 历史消息摘要
- pgvector 检索
- 用户风格偏好存储
- 任务与联系人关联增强

#### 验收标准

- 回复建议能参考历史沟通风格
- 每日简报能提取长期趋势

---

### Phase 3：多渠道接入

#### 功能范围

- Telegram / Slack 接入
- Webhook 消息摄取
- 通知推送
- 定时提醒

#### 验收标准

- 能从 IM 接收消息
- 能看到“待回复”列表
- 能发送提醒通知

---

### Phase 4：主动性提升

#### 功能范围

- 未回复联系人跟进
- 承诺追踪
- 周报生成
- 轻量工作流
- 优先级自适应

#### 验收标准

- 能主动提醒“该回谁了”
- 能总结“本周承诺未兑现项”

---

## 19. 工程目录结构建议

```text
exec-twin/
├─ apps/
│  └─ api-server/
│     ├─ src/main/java/com/example/exectwin/
│     │  ├─ api/
│     │  │  ├─ controller/
│     │  │  ├─ dto/
│     │  │  └─ advice/
│     │  ├─ application/
│     │  │  ├─ service/
│     │  │  ├─ usecase/
│     │  │  └─ scheduler/
│     │  ├─ domain/
│     │  │  ├─ task/
│     │  │  ├─ social/
│     │  │  ├─ memory/
│     │  │  ├─ contact/
│     │  │  └─ digest/
│     │  ├─ infrastructure/
│     │  │  ├─ persistence/
│     │  │  ├─ redis/
│     │  │  ├─ ai/
│     │  │  ├─ vector/
│     │  │  ├─ messaging/
│     │  │  └─ telemetry/
│     │  ├─ config/
│     │  └─ ExecTwinApplication.java
│     ├─ src/main/resources/
│     │  ├─ application.yml
│     │  └─ db/migration/
│     └─ pom.xml
├─ docs/
│  ├─ architecture.md
│  ├─ prompts.md
│  └─ api.md
├─ docker/
│  └─ docker-compose.yml
├─ .env.example
├─ README.md
```

---

## 20. 数据库表建议

MVP 至少需要这些表：

- `users`
- `contacts`
- `conversation_messages`
- `message_analysis`
- `tasks`
- `task_events`
- `reminders`
- `memory_entries`
- `daily_digests`

后续可扩展：

- `message_channels`
- `sync_jobs`
- `embeddings`
- `user_preferences`

---

## 21. 前端建议

虽然后端用 Java，但前端不必用 Java。

### 主流建议

- 后端：Java
- 前端：Next.js / React

### 如果先求快

- 暂时不上前端
- 直接 Swagger + Postman + 简单管理页

### 如果要做出彩 Demo

建议后面补三个核心视图：

#### 1. Today Dashboard

- 今日重点任务
- 待回复联系人
- 风险提醒

#### 2. Inbox

- 新消息
- 优先级
- 一键生成回复建议

#### 3. Memory / Contacts

- 联系人画像
- 历史上下文
- 推荐沟通风格

---

## 22. 模型建议

### 主流稳定选择

- Anthropic Claude
- OpenAI GPT-4.1 / 4o / 5 系可用版本
- Gemini 2.5 系
- 本地 Ollama（开发测试）

### 建议分工

- 任务抽取 / 结构化输出：Claude / GPT 都适合
- 社交回复建议：Claude 在语气和上下文理解上通常较强
- 记忆摘要：GPT / Claude 都可

### 建议做 Provider 抽象

做一个 `LLMProvider` 抽象层，底层支持多模型切换。

---

## 23. 核心接口设计建议

### 23.1 LLM 网关

```java
public interface LlmGateway {
    <T> T generateStructured(
        String systemPrompt,
        String userPrompt,
        Class<T> outputClass
    );

    String generateText(
        String systemPrompt,
        String userPrompt
    );
}
```

### 23.2 任务抽取服务

```java
public interface TaskExtractionService {
    TaskExtractionResult extract(String rawInput, UserContext context);
}
```

### 23.3 社交分析服务

```java
public interface SocialAnalysisService {
    SocialAnalysisResult analyze(MessageContext messageContext);
}
```

### 23.4 记忆服务

```java
public interface MemoryService {
    List<MemorySnippet> retrieveRelevantMemories(UUID userId, String query);
    void storeMemory(UUID userId, String type, String content, Map<String, Object> metadata);
}
```

---

## 24. 测试策略

这个项目非常需要测试，否则模型一变就容易崩。

### 24.1 单元测试

- 时间表达解析
- 优先级映射
- 去重逻辑
- 联系人匹配

### 24.2 集成测试

- API 调用
- PostgreSQL / Redis
- Quartz 任务

### 24.3 Agent 测试

给固定输入，断言结构化输出是否符合预期：

- 是否抽取出任务
- 是否识别 `replyNeeded`
- 是否生成摘要字段

### 24.4 Prompt 回归测试

保留一组 benchmark case：

- 模棱两可消息
- 多任务混合输入
- 敏感关系回复
- 不明确时间表达

---

## 25. 需要避免的坑

- 一上来就做自动代发消息
- 把所有逻辑塞进一个 Agent
- 不做 structured output
- 没有观测与 tracing
- MVP 范围过重
- 一开始就接邮箱、Telegram、Slack、日历、RAG、语音、前端全家桶

---

## 26. 如何让项目更抓眼球

建议加入这些展示点：

### 26.1 今天你最该回的 3 个人

这是非常直观、很有产品感的视图。

### 26.2 你答应了但还没做的事

很有冲击力，也容易形成记忆点。

### 26.3 同一消息切换不同语气

例如输出：

- 专业版
- 熟人版
- 简洁版

非常适合 Demo 演示。

### 26.4 Agent 为什么这样建议

建议同时给出解释，例如：

- 因为对方高优先级
- 因为消息中有明确请求
- 因为你过去平均 2 天内会回复此人
- 因为该任务 48 小时内到期

---

## 27. MVP 功能清单

### 27.1 MVP 必做

- [x] 用户输入自然语言 → 自动抽取任务
- [x] 导入消息 → 判断是否需要回复
- [x] 生成回复建议
- [x] 每日摘要生成
- [x] PostgreSQL 持久化
- [x] Redis 做短期缓存
- [x] Spring AI 接 LLM
- [x] Langfuse / OpenTelemetry tracing
- [x] Swagger API

### 27.2 MVP 暂缓

- [ ] 自动发送消息
- [ ] 多平台完整同步
- [ ] 复杂多 Agent 协调
- [ ] 多租户
- [ ] 高级权限系统
- [ ] 语音输入
- [ ] 浏览器自动化

---

## 28. 可直接交给 Claude Code 的启动 Prompt

下面这段可以直接丢给 Claude Code：

```text
请从零开始创建一个 Java AI Agent 项目，项目目标是做“第二大脑 + 社交分身”的个人执行型 Agent。

技术栈要求：
- Java 21
- Spring Boot 3.x
- Spring AI
- PostgreSQL
- Redis
- Quartz Scheduler
- Spring Data JPA
- Flyway
- OpenAPI / Swagger
- Micrometer + OpenTelemetry
- 预留 pgvector 扩展能力

项目目标：
构建一个可扩展的 Agent 系统，具备两类核心能力：
1. 第二大脑：从自然语言中抽取任务、提醒、截止时间、联系人、优先级
2. 社交分身：分析消息是否需要回复、优先级如何、生成回复建议、识别 follow-up

MVP 功能范围：
1. 提供 REST API
2. 支持输入自然语言并解析任务
3. 支持导入消息并分析：
   - 是否需要回复
   - 优先级
   - 原因
   - 建议回复
4. 支持生成每日摘要
5. 持久化存储用户、联系人、消息、任务、提醒、摘要
6. 为未来长期记忆和向量检索预留接口
7. 所有 Agent 输出优先使用结构化 JSON
8. 要有清晰分层架构：api / application / domain / infrastructure
9. 写 README，说明如何启动 PostgreSQL、Redis、运行项目、配置模型 API Key
10. 写基础测试

重要约束：
- 不要做前端
- 不要做自动发送消息
- 不要引入复杂微服务
- 不要做过度抽象
- 不要把所有逻辑塞进一个类或一个 prompt
- 优先保证代码结构清晰、项目能运行、后续可扩展

请按下面步骤输出：
1. 先给出项目目录结构
2. 再给出架构设计说明
3. 再给出数据库表设计
4. 然后逐步创建代码
5. 最后给出本地运行步骤和后续迭代建议
```

---

## 29. 下一步建议

最合理的下一步不是继续空聊，而是把方案推进到“可开工”的程度。

你可以继续让我输出下面任意一个：

### 方案 A

继续细化成：

- 完整 PRD
- 数据库 ER 图
- API 文档草案
- Prompt 设计稿

### 方案 B

直接产出：

- Java 项目目录模板
- `pom.xml` 依赖清单
- 核心实体与接口骨架

### 方案 C

直接整理：

- Phase 1 详细开发任务拆解清单
- 适合喂给 Claude Code 分阶段开发的 Prompt 包

---

## 30. 最推荐的下一步

如果你想最高效，建议直接继续：

> **给我 Phase 1 的详细开发清单 + Java 项目骨架**

这样就能直接进入开发阶段。