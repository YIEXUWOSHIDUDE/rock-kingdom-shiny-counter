# Repository instructions

## Project rules

开始本项目任务前，完整阅读根目录 `AGENTS.local.md`。它保存本仓库人工维护的工作规则；在不违反系统、开发者和用户当前明确要求的前提下，项目具体规则优先于通用模板。不要通过远端 bootstrap 自动覆盖这两份文件。

## Agent skills

### Issue tracker

本仓库使用本地 Markdown 跟踪需求和任务，文件存放在 `.scratch/<feature>/`。详见 `docs/agents/issue-tracker.md`。

### Triage labels

任务状态使用 `needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human` 和 `wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用单上下文结构：项目领域说明位于根目录 `CONTEXT.md`，架构决策位于 `docs/adr/`。详见 `docs/agents/domain.md`。
