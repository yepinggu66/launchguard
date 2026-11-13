# 发布文案（英文为主，直接可发）

站点：`https://launchguard-production-e3a01252.up.railway.app`
仓库：`https://github.com/yepinggu66/launchguard`
视频：`video/out/launchguard-promo.mp4`（61 秒，1920×1080，有配音）

---

## 主贴（配视频）

> Six lines of Python. No bug, no CVE, passes code review.
>
> Still runs until the invoice arrives.
>
> I wrote three checks for the failure modes that only exist once an AI writes your code.
> Free, on any public repo — 20 seconds, nothing uploaded:
>
> https://launchguard-production-e3a01252.up.railway.app

**Alt text**（发布时填在视频的可访问性描述里）：
> Dark screen: a Python function loops `while True` around an OpenAI call with no break and no max_tokens; a $4,183.44 invoice counter; three check cards labelled LEAK, COST, PERM; a scanner report page grading a real repo C at 16/100.

---

## 跟帖（7 条，按这个顺序发）

**1/**
The specific bug, because "AI code is risky" is not a useful sentence:

```python
while True:
    out = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
    yield out.choices[0].delta.content
```

No `break`. No `max_tokens`. SDK default timeout and 2 retries.

That is a generator that retries forever, at your expense.

**2/**
Nothing in the normal toolchain catches it.

Linters check syntax.
Dependency bots check versions.
Reviewers check intent.
Nobody checks the invoice.

**3/**
So: three checks, one PR comment.

LEAK — a key committed, or wired into `NEXT_PUBLIC_` / `VITE_` / a file that ships to the browser.
COST — model calls in loops with no exit, or with no output cap.
PERM — `dangerouslySkipPermissions`, `allowedTools: ["*"]`, a policy that allows `*`.

**4/**
It's not theoretical. I ran it over 9 widely used agent/MCP repos — 10,872 files:

1 hardcoded credential
18 uncapped model calls
2 committed dotenv files
0 CVEs

The libraries are clean. The app layer is not.

**5/**
The libraries are clean because adapters forward `**kwargs` and vendors pass budgets explicitly.

The bugs live in the code you and I write at 2am with an agent — which is exactly the code nobody has a linter for yet.

**6/**
Free on any public repo, no signup:

https://launchguard-production-e3a01252.up.railway.app

Or add it to CI — one comment per PR, edited in place, with a paste-ready fix prompt for Cursor / Claude Code:

`uses: yepinggu66/launchguard/guard@main`

**7/**
If you'd rather have a human read the output: $29, one repo, I confirm every finding against the source, drop the false positives, and send a fix PR.

(PayPal. 24h.)

https://launchguard-production-e3a01252.up.railway.app/pricing

---

## 中文版（即刻 / 朋友圈）

> 六行 Python，没有 bug、没有 CVE、code review 也能过，但它在一直烧钱。
>
> 给 AI 写的代码做了三个检查：泄露的 key、没有出口的模型调用、被关掉的审批开关。
>
> 公开仓库免费扫，20 秒，代码不出你的机器。

---

## 发之前必须做

1. **crawl4ai 那个 key 不要提原值**。先查是否已吊销，走 GitHub 安全渠道披露。文案里只说"in a public docs file of a crawling project"，不带字符串。
2. 视频里出现的每个数字都要能对得上 `guard-out/index.json`（9 / 10,872 / 1 / 18 都是真实跑出来的）。
3. 第一条推文不放产品名和链接，只放"发现"——链接放第 6 条。X 上带链接的首帖触达会被压。
4. 发布后 24 小时内，把每条带具体质疑的回复都查一遍源码再回。这个品类的全部信用在于"你说的每一条都对得上 file:line"。

## 不要做

- 不要写"我发现了 27 个漏洞"。真实是 1 个。
- 不要用"最流行的 10 个仓库"这种说法，说"widely used"。
- 不要在首帖里 @ 任何大 V。
