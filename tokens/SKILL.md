---
name: tokens
description: 查看当前 Codex 聊天的已记录 Token 累计用量，默认汇总子任务。用于 tokens 命令、Token 状态或本聊天消耗查询；不处理订阅额度和 API 费用估算。
---

读取一次本机统计，在聊天中返回简洁的状态摘要。不要打开小窗或浏览器，不要启动模型任务来估算 token，也不要改写内置 `/status`。

在当前聊天的执行环境中运行相邻的 [scripts/token_status.py](scripts/token_status.py)。以本次加载的 `SKILL.md` 所在目录解析脚本路径，不假设固定的技能安装目录。

使用 Python 3.10 或更新版本，脚本只依赖标准库。Windows 优先使用 Codex 自带的 Python：`$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`；该文件不存在时使用可用的 Python。其他系统使用可用的 `python3`。设置 `PYTHONIOENCODING=utf-8`，确保中文输出正常。没有可用的 Python 时说明缺少运行环境。

脚本默认从 `CODEX_THREAD_ID` 识别这条聊天，因此直接在主任务运行，不委派查询。若该变量不可用，可以用 `--thread <当前聊天的已确认ID>`；无法确认时报告缺少 ID，不用“最近更新的聊天”代替。用户明确只查看主任务时加 `--main-only`。需要结构化结果时加 `--json`。

将脚本结果直接用于回答：总计、输入、输出、缓存输入、推理输出、子任务数量和记录更新时间。金额与订阅剩余额度无法从该数据推出。缓存输入已经包含在输入中，推理输出已经包含在输出中，不再加一次。

状态摘要用中文，保持简短。统计覆盖这条聊天已记录的所有回合，并非只是刚发送的一条消息。存在缺失记录时保留“尚未取得统计”的提示，不把未知项当作零；没有统计则显示“等待记录”。这是一次快照，不会在聊天中持续自动刷新，查询过程中后续用量可能尚未写入。
