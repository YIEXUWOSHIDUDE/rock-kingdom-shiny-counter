# 问题跟踪：本地 Markdown

本仓库的需求、规格和实施任务均使用 `.scratch/` 下的 Markdown 文件管理。

## 文件约定

- 每项功能使用一个目录：`.scratch/<feature-slug>/`
- 功能规格写入 `.scratch/<feature-slug>/PRD.md`
- 实施任务写入 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`
- 任务编号从 `01` 开始
- 每个任务文件顶部使用 `Status:` 记录当前状态
- 状态值遵循 `triage-labels.md`
- 补充说明和讨论追加到任务文件底部的 `## Comments`

## 发布任务

当技能要求“发布到问题跟踪器”时，在 `.scratch/<feature-slug>/` 下创建相应文件及目录。

## 读取任务

当技能要求“读取相关任务”时，读取用户指定的文件路径或任务编号。

## 依赖关系

任务之间的阻塞和依赖关系直接写入任务正文，必须引用对应任务文件。
