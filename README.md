# Codex Tokens Skill

在 Codex 聊天中输入 `$tokens`，查询当前聊天的已记录 Token 累计用量，默认包含子任务。

显示总计、输入、输出、缓存输入、推理输出、子任务数量和记录更新时间。缓存输入已包含在输入中，推理输出已包含在输出中。

## 安装

仓库地址：https://github.com/Arthas-HN/codex-tokens-skill

在自己的 Codex 中输入：

```text
使用 $skill-installer 从 https://github.com/Arthas-HN/codex-tokens-skill 安装 tokens 技能，技能在仓库中的路径是 tokens。
```

安装后，在下一条对话中输入 `$tokens`。如果技能仍未出现，重新启动 Codex。

也可以通过 skills CLI 安装，按提示选择 Codex：

```text
npx skills add Arthas-HN/codex-tokens-skill --skill tokens
```

手动安装时，把完整的 `tokens` 文件夹放入自己的 Codex 技能目录；具体目录以当前 Codex 版本和配置为准。

## 文件结构

```text
README.md
.gitignore
tokens/
  SKILL.md
  agents/
    openai.yaml
  scripts/
    token_status.py
    token_source.py
```

## 运行条件与范围

- Python 3.10 或更新版本，只依赖标准库。技能会优先寻找 Windows 上的 Codex 自带 Python，也可使用其他可用的 Python。
- Codex 需要在本机保存聊天统计日志和线程索引。脚本使用 `CODEX_HOME`，未设置时读取用户主目录下的 `.codex`。
- 通过 `CODEX_THREAD_ID` 确定当前聊天；没有该变量时需要提供已确认的聊天 ID，不能用最近更新的聊天代替。
- 目前已在 Windows Codex 桌面环境验证。其他系统或 Codex 版本的日志结构可能不同，需要验证兼容性。
- 每次调用返回一次快照。新任务尚未写入统计时会保留缺失提示；不在聊天中持续自动刷新。
- 时间标为北京时间。统计覆盖当前聊天已记录的所有回合，不能用于推算订阅剩余额度或 API 费用。

## 数据与发布内容

分享包只包含技能说明和代码，不包含创建者的聊天记录、统计数据库、账号信息或密钥。运行时只读本机统计，不联网、不调用模型 API，也不修改 Codex 数据库。每位使用者查询的是自己电脑上的聊天统计。

相关说明：[Codex 技能文档](https://learn.chatgpt.com/docs/build-skills)。
