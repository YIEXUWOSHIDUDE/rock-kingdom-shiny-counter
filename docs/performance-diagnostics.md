# 隔离性能诊断

仅供开发者手动运行，不是自动计数新模式。入口不使用 `DataStore`，不会读写用户计数库；不保存截图或 OCR 原文。完整识别继续只用 GPU，模型缺失会失败而非联网下载或回退 CPU。

从仓库根目录使用已有 GPU Python 运行：

```powershell
& release/.venv-cuda128/Scripts/python.exe -B -m tools.performance_probe --hwnd <用户选定游戏窗口的数字句柄> --mode full --seconds 60 --output .scratch/performance/live-full.json
```

`--mode paused`、`--mode capture`、`--mode full` 分别为暂停、仅截图缓冲、完整 GPU 识别；仅截图没有消费者，队列过期不等于完整识别漏计。默认沿用项目设置（50ms 截图、200ms OCR），不加载真实用户设置。首个 5 秒区间可能含截图初始化，应与后续稳定区间区分。

也可用 `--video <获授权的录屏绝对路径>` 替代 `--hwnd`；视频适配器先完整解码，不代表真实桌面截取性能。用 `--start 20 --clip-seconds 8 --repeats 2 --seconds 21` 回放标注片段两次并留尾部排空时间，需人工核实标注计数和安静尾帧；不要对任意素材照搬预期值。

对已标注素材增加 `--expected-count 2`，计数不符将写入报告并以失败退出，不仅检查进程有没有报错。`--capture-path full` 可对照旧的整窗后裁剪路径（仅诊断入口），默认 `banner` 为区域路径。偶发问题可加 `--trace-decisions`，最多保留 4096 个样本的相对时间、接受/命中/计数布尔值及匹配置信度；仍不保存 OCR 原文或图像，诊断结果不进入发布包。

每次新进程仅改变一个实验参数：

- `--cv-threads 1` 或 `2`：OpenCV CPU 线程。
- `--torch-threads 1` 或 `2`：PyTorch CPU intra-op 线程，CUDA OCR 不变。
- `--batch-size 1`、`4`、`8`：同幅截图中文字框批量，不等待攒多张截图。

省略参数保持库默认。两轮以上交替/反向顺序，保持窗口/素材/时长/电源条件一致；不要同时跑测试或其他负载干扰测量。CPU 下降但延迟、过期或计数变差的配置不采用。无实机证据时只列候选，不改变生产默认。

输出包括环境、初始化/预热时间、GPU 峰值分配/缓存显存，以及每 5 秒汇总的进程 CPU 时间、RSS、捕获/OCR 吞吐、阶段 mean/P95、队列和丢帧。显存是本进程 Torch 分配/保留量，不等于整卡/驱动总占用；CPU 分别给出一核=100%和按逻辑核数归一化的口径。

`capture_total` 包含 `window_check_and_grab` 与 `image_conversion`，不能把这些重复相加；`buffer_offer` 包含裁剪入口/灰度比较/独立快照，`ocr_call` 为完整同步返回调用，`queue_wait` 从捕获完成时间起算。视频模式改为单列 `video_decode`，没有真实窗口检查/抓屏分阶段数据。P95 为每区间最近最多 4096 样本，均值涵盖区间全部样本。JSON 中缺少的事件表示该区间没有发生，不是未检测。

`python -m tools.capture_microbench --output .scratch/performance/conversion.json` 可独立对照固定输入的整窗/区域转换+缓冲。它不调用真实截图后端，不能用结果宣称整程序 CPU 降幅。

最终仍须在真实 Windows + GPU + 游戏环境重复暂停、安静画面、动态背景、连续横幅，并观察游戏流畅度；合成和回放不能代替这一步。
