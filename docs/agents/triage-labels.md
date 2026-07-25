# 任务状态

| 标准状态 | 本仓库使用的值 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 等待维护者评估 |
| `needs-info` | `needs-info` | 等待报告者补充信息 |
| `ready-for-agent` | `ready-for-agent` | 信息完整，可由 AI 代理实施 |
| `ready-for-human` | `ready-for-human` | 需要人工处理或决策 |
| `wontfix` | `wontfix` | 确认不处理 |

任务文件通过顶部的 `Status:` 字段记录状态。工程技能提及某个标准状态时，必须使用表中对应的值。
