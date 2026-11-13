# Launch Guard

上线前 30 秒的三种检查——专门抓 **AI 写代码之后才大量出现的**事故，而不是 CVE。

一条命令，零依赖（纯标准库），代码不出 runner：

```bash
cd guard
python -m guard.cli scan ../your-repo --comment out.md --badge badge.svg
```

```
grade D (47/100) | 812 files | 1400ms | critical=1 high=2 medium=3 low=0
  [CRITICAL] LEAK-01 public/config.js:12 - openai-project-key hardcoded in a file that ships to the browser
  [HIGH    ] COST-01 app/agent.py:88 - model call inside a `while True` with no exit
  [HIGH    ] PERM-01 .claude/settings.json:3 - agent runs with permission prompts disabled
```

## 先看它长什么样

不想先扫自己的仓库，就直接生成一个反面教材：

```bash
python -m guard.cli demo --out guard-out/demo
```

它会在 `guard-out/demo/demo-app/` 造一个"典型 AI 写出来的应用"（前端里硬编码 key、`while True` 包着模型调用、MCP 全放行、审批开关关掉），扫完把 PR 评论、徽章、JSON 一起写出来。里面的 key 是重复的 `demo` 串，任何 provider 都不会签发，也永远不会被提交。

## 为什么不是又一个 SAST

| | 传统 SAST / 依赖扫描 | Launch Guard |
|---|---|---|
| 查什么 | CVE、已知漏洞模式 | 会被**计费**的东西、会**失控**的循环、被**关掉的审批** |
| 谁在买 | 安全团队 | 用 AI 写完就直接上线的人 |
| 误报代价 | 忽略告警 | 卸载机器人（所以这里宁可漏报） |
| 输出 | 一个 ID + 一段解释 | `file:line` + 一段能直接粘进 Cursor 的修复 prompt |

这三类问题没有任何 CVE 编号可以描述：一个 `while True` 包着 `client.chat.completions.create(...)`、没有 `max_tokens`、没有 `break`——合法 Python，通过 review，跑一整夜。

## 三条检查

### 1. LEAK — 会被读到、会被计费的凭据

| 规则 | 级别 | 抓什么 |
|---|---|---|
| `LEAK-01` | CRITICAL / HIGH | 硬编码的 key（OpenAI / Anthropic / Google / AWS / GitHub / Slack / Stripe / HF / Groq …）。命中在**会发送到浏览器**的文件（`public/`、`static/`、`.html`、`.tsx`、带 `"use client"`）为 CRITICAL，普通源码为 HIGH |
| `LEAK-02` | MEDIUM | `.env` 被提交进仓库（`.env.example` 等模板不算） |
| `LEAK-03` | LOW | 凭据出现在 URL query 里（会进日志、代理、Referer） |

证据永远**打码**：报告里只出现 `sk-proj-… (164 chars)`，不出现 key 本身。

### 2. COST — 会自己把账单跑爆的循环

| 规则 | 级别 | 抓什么 |
|---|---|---|
| `COST-01` | HIGH | `while True` 里调用模型，且循环体内没有 `break` / `return` / `raise` |
| `COST-02` | MEDIUM | 调用没给 `max_tokens` / `max_completion_tokens` / `max_output_tokens`（有 `**kwargs` 时保持沉默，不猜） |
| `COST-03` | LOW | 客户端构造时没给 `timeout=` / `max_retries=`（同一个仓库折叠成一条，不刷屏） |
| `COST-04` | HIGH | `AgentExecutor` / `initialize_agent` 没有 `max_iterations`，或设成 ≥100 |

### 3. PERM — 把审批关掉的开关

| 规则 | 级别 | 抓什么 |
|---|---|---|
| `PERM-01` | CRITICAL | `dangerouslySkipPermissions: true`，或脚本里的 `--dangerously-skip-permissions` |
| `PERM-02` | HIGH | MCP server 的 `allowedTools: ["*"]`、`autoApprove: true`、`permissions.allow: ["*"]` |
| `PERM-03` | CRITICAL | `policy.yaml` 里 `action: "*"` + `effect: allow`（默认放行 = 记账本，不是闸门） |
| `PERM-04` | MEDIUM | 通过 `env` 把长期凭据明文塞给第三方 MCP server（同一处已报 LEAK-01 时不重复） |

## 作为 GitHub Action

```yaml
name: Launch guard
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: yepinggu66/agentproof-cloud/guard@main
        with:
          fail-on: critical      # none | critical | high | medium
          comment: "true"
          badge-path: agentproof-guard.svg
```

它做三件事，顺序经过设计：

1. **扫**（`--fail-on none`，保证下面两步一定执行）
2. **评论**：一个隐藏标记 `<!-- agentproof-guard:v1 -->` 定位旧评论，有则改、无则建——**永远只有一条**，不会每推一次就刷一层
3. **判定**：只有最后一步按 `fail-on` 返回非零，所以 PR 变红时评论已经在上面了

权限不够（fork PR）或 token 缺失时，评论步骤**静默跳过并以 0 退出**，绝不因为发不出评论而让构建失败。评论同时写进 job summary，不进 PR 也能看到。

## 批量出传播素材

把仓库（本地路径，克隆好的）批量扫，产出可直接发的东西：

```bash
python -m guard.cli batch ../.tmp/guard-repos/* --out guard-out
```

```
guard-out/
  index.md          # 总表：每个仓库的评级 / blockers / 文件数
  index.json
  card.svg          # 1200x630 分享卡（给 X 用的那张图）
  thread.md         # 6 条推文的草稿，数字自动填
  <owner__repo>/
    comment.md      # 这个仓库的 PR 评论长什么样
    badge.svg
    report.json     # 机器可读，含全部 file:line
```

`thread.md` 里的每个数字都来自 `index.json`，所以重新跑一遍批量，文案跟着变——不会出现"文章说 27 个，其实是上一版"的情况。

要发 X 的话，SVG 换成 PNG（Pillow，只在这个开发脚本里用，不进 Action）：

```bash
python tools/render_card_png.py guard-out/index.json guard-out/card.png
```

## 首跑结果（2026-11-13，9 个真实仓库）

浅克隆 9 个广泛使用的 agent / MCP 仓库，`10,872` 个文件，31 秒：

| 仓库 | 评级 | 发现 |
|---|---|---|
| `unclecode/crawl4ai` | C | 1 个真实形态的 provider key 写在公开文档里（**已按负责任披露处理，不在任何产物里输出原值**） |
| `BerriAI/litellm` | C | 2 个 `.env` 被提交 + 15 条（含 11 条未封顶的模型调用） |
| `crewAIInc/crewAI` | C | 7 条（含 6 条 devtools 里未封顶的 `chat.completions.create`） |
| `geekan/MetaGPT`、`modelcontextprotocol/python-sdk`、`openai/openai-agents-python`、`openai/swarm` | B | 各 1 条 |
| `langchain-ai/langgraph`、`modelcontextprotocol/servers` | A | 无 |

结论比数字重要：**库本身是干净的**——适配器转发 `**kwargs`，厂商显式传 budget，没人把 key 写进发布的包里。三类问题都长在应用代码里，也就是每个人用 agent 现写的那层。

### 首跑顺手修掉的三个误报

这三次都是真仓库教我的，不是测试写的：

| 误报 | 真相 | 修法 |
|---|---|---|
| litellm 报 30 条"while True 里调模型" | 文件里 import 了 openai，于是 `self.flush_queue()` 被当成模型调用 | 循环内必须同时命中调用名正则 |
| litellm 报 key | CI 里故意写的 `sk-ant-replay-must-never-reach-a-provider`，用来保证录像回放永远打不到真 API | 加"像句子不像 key"的判据 |
| crewAI 报无迭代上限 | 它用的是 `max_iter=`，不是 `max_iterations=` | 补上这个拼写 |

还有两个误报是同一类：`self.completion(...)` / `super().completion(...)`（库在*实现*调用）和 `AgentExecutor` 里参数名不同。都是"库代码 vs 应用代码"的区别，规则里现在写清楚了。

## 精度承诺

这是这个产品的全部资产，所以规则写在代码里而不是文档里：

- **宁可漏报**：`**kwargs` 存在时不下"缺 max_tokens"的结论；非 SDK 的 `.completion()` 不当模型调用；`create_react_agent` 这种"参数在别处"的 API 不报。
- **占位符过滤**：`sk-your-key-here`、`xxxx`、`--- example ---` 一律不算。
- **不扫噪音目录**：`tests/`、`fixtures/`、`docs/`、`node_modules/`、`dist/`、`build/`、`.venv/`。
- **证据可点**：每条必须是 `path:line`，不能是"某处可能有"。
- **凭据打码**：任何输出路径（console / json / markdown / svg）都不含完整 key。

### 已知盲区（下一版）

- JS/TS 的 COST 检查还没有——先保证 Python 的精度，再上 JS AST。
- "客户端可达"靠目录与 `"use client"` 推断，不做 bundler 级分析（会误判 server-only 的 `src/lib`）。
- 只看当前代码，不看 git 历史（历史里的 key 要另跑一遍 `git log -p`）。
- 单仓库 6000 文件上限，超过会标 `truncated`。

## 48 小时验证

1. 在本机随便挑 10 个 clone 下来的 agent 仓库跑 `batch`，看 `index.md`。
2. 挑 3 条最容易被人反驳的，逐条打开 `file:line` 确认——**必须能对着源码解释**。
3. 只发有把握的那几条，配 `card.svg`。第一条推文不要放产品链接，放发现。
4. 有人问"能不能扫我的仓库"再给 Action。

**淘汰线**：批量跑完，若"确认为真"的发现 < 5 条，说明这套规则在真实代码上的检出率不够，先补规则，不要发。
