---
name: explain-code
description: Explain a code path or file using the current repository context
when_to_use: Use when the user wants a concise explanation of code with optional focus text
user_invocable: true
version: "1"
shell_interpolation: false
---

Explain the requested code using the current repository context.

Focus request: {{args}}

If a specific file or symbol is mentioned, explain how it works, what it depends on, and any important execution flow.
