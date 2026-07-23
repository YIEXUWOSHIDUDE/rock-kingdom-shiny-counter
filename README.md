# 洛克王国异色保底计数悬浮工具

这是一个 Windows 计数器。它截取游戏客户端窗口，使用中文 OCR 寻找你设置的结算关键词，并在悬浮窗中累计保底次数。默认保底为 80 次。

程序不会访问游戏数据库，不读取游戏进程内存，不注入游戏，不模拟按键，也不执行自动战斗。正式安装包已经内置 EasyOCR 中文模型，首次启动不需要联网下载。源代码运行时若模型缺失，会优先使用已校验的 ModelScope / GitCode 国内镜像，失败后才回退到 EasyOCR 官方 GitHub 源。计数、设置、OCR 模型和历史记录保存在 `%APPDATA%\RockKingdomShinyCounter\`。

> 风险提示：官方公开口径禁止第三方辅助工具。即使本程序只读取屏幕，也不能保证账号不会受到处罚。请先向腾讯客服确认，主账号谨慎使用。

## 最低运行要求

- Windows 10 22H2 或 Windows 11（64 位）
- NVIDIA GeForce RTX 20/30/40/50 系显卡，CUDA 计算能力不低于 7.5
- NVIDIA Windows 驱动 580.88 或更高版本
- 至少 4 GB 显存、8 GB 内存，建议 16 GB 内存
- 安装时至少预留 8 GB 磁盘空间

程序只支持 NVIDIA GPU OCR，不提供 CPU 降级模式。显卡、驱动或安装包 CUDA 架构不满足要求时，会直接显示具体原因。

## 源代码环境与安装

- 64 位 Python 3.14
- 洛克王国使用窗口化或无边框窗口模式

如果你安装过旧的模板识别版，建议先删除旧 `.venv`，再按下列步骤重建环境，避免 `opencv-python` 与 `opencv-python-headless` 同时存在。原有 `%APPDATA%\RockKingdomShinyCounter\data.json` 可以继续使用。

在 PowerShell 中执行：

```powershell
cd rock-kingdom-shiny-counter
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

安装 PyTorch 2.13 的默认 CUDA 13.0 构建，然后继续安装其余依赖：

```powershell
python -m pip install torch torchvision
python -m pip install -r requirements.txt
python -c "import torch; print('CUDA available:', torch.cuda.is_available(), 'CUDA:', torch.version.cuda, 'architectures:', torch.cuda.get_arch_list())"
python -m shiny_counter
```

必须输出 `CUDA available: True`。RTX 50 系还必须在架构列表中看到 `sm_120`；如果缺失，请确认安装的是 CUDA 13.0 构建。

完成上述安装后，可以直接双击 `run.bat`。脚本会优先使用项目内的 `.venv`。

## 首次使用 OCR

1. 启动洛克王国客户端，使用窗口化或无边框窗口模式。
2. 启动计数器，点击“选窗口”，选择游戏客户端。无需框选截图区域。
3. 安装版会从安装包复制并加载 EasyOCR 中文模型，请等待状态栏显示 OCR 结果。
4. 进入一次有效结算画面，点击“查看文字”。
5. 从识别结果里找一个只在该结算画面出现的短语。
6. 打开“设置”，把短语填入“OCR 关键词”。多个关键词用逗号分隔。

默认在顶部中央横幅区域扫描。一次 OCR 发现关键词后计数一次；关键词持续显示时不会重复计数，连续两次消失后才重新布防。OCR 默认每 200 ms 扫描一次，最低置信度为 0.55。

游戏窗口可以移动。窗口尺寸、系统缩放或游戏界面发生变化时，工具会暂停并要求重新选择窗口。

## 使用说明

- “补一”：修正漏识别。
- “撤销”：将当前计数减一并写入历史。
- “暂停”：停止截图识别，手动操作仍可用。
- “解锁位置/锁定位置”：默认锁定悬浮窗，解锁后才允许鼠标拖动。
- “重置”：确认后结束当前轮次并开始新一轮，自动记录本轮次数、保底上限和是否达到保底。
- “查看文字”：查看最近一次顶部横幅 OCR 识别到的文字，用于选择关键词。
- “历史”：先查看每轮保底次数汇总，再查看自动计数、手动计数、撤销、重置和到达保底事件。
- “导出”：生成包含 `data.json` 的 ZIP；OCR 模型不会打包。
- “导入”：验证 ZIP 后替换当前数据，并在数据目录中生成导入前备份。

默认全局快捷键：

| 操作 | 快捷键 |
|---|---|
| 切换点击穿透 | `Ctrl+Alt+T` |
| 手动补一 | `Ctrl+Alt+Up` |
| 撤销 | `Ctrl+Alt+Down` |
| 暂停或继续 | `Ctrl+Alt+P` |

快捷键被其他程序占用时，悬浮窗会提示更换。开启点击穿透后，需要使用全局快捷键关闭穿透。

## 测试

核心逻辑不依赖 Windows GUI，可以直接运行：

```powershell
python -m unittest discover -s tests -v
```

测试覆盖 OCR 关键词匹配、跨文字框匹配、结算画面去重、重新布防、保底状态、位置锁定设置、每轮次数记录、撤销、重置、原子保存和 ZIP 导入导出。Windows 截屏、CUDA、全局快捷键、声音和真实游戏画面仍需在目标电脑上人工验收。

## 识别边界

OCR 可能漏字或识别错字。低置信度文字按设计不计数，因此建议先用“查看文字”确定稳定关键词，并偶尔核对当前次数。若关键词在非结算画面也出现，会造成误计；应换成更独特的短语。遮挡、独占全屏、过小字体和游戏更新都可能影响识别。工具不会自动重置已达到保底的计数。
