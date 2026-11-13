"""HTML for the public app. Plain strings, no template engine, no build step."""

from __future__ import annotations

from html import escape

CSS = """
:root{
  --bg:#0b0e14; --panel:#11161f; --line:#1f2634; --fg:#e6edf3; --muted:#8b949e;
  --dim:#6e7681; --green:#3fb950; --red:#f85149; --amber:#d29922; --orange:#db6d28;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg)}
body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--fg);text-decoration:none}
a:hover{color:#fff}
code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}
.wrap{max-width:960px;margin:0 auto;padding:0 24px}
nav{display:flex;align-items:center;justify-content:space-between;padding:22px 0;border-bottom:1px solid var(--line)}
nav .brand{font-weight:600;letter-spacing:.14em;font-size:13px;text-transform:uppercase;color:var(--muted)}
nav .brand b{color:var(--green)}
nav a.link{font-size:14px;color:var(--muted);margin-left:22px}
.eyebrow{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--green);margin:64px 0 18px}
h1{font-size:clamp(34px,5vw,56px);line-height:1.05;letter-spacing:-.02em;margin:0 0 20px;font-weight:700}
h1 .fade{color:var(--muted)}
.lede{font-size:19px;color:var(--muted);max-width:640px;margin:0 0 34px}
form.scan{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 12px}
form.scan input[type=text]{flex:1;min-width:260px;background:var(--panel);border:1px solid var(--line);
  color:var(--fg);padding:15px 16px;border-radius:10px;font-size:16px;outline:none}
form.scan input[type=text]:focus{border-color:var(--green)}
button{background:var(--green);color:#04140a;border:0;border-radius:10px;padding:15px 22px;
  font-size:16px;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.08)}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--fg);font-weight:500}
.hint{color:var(--dim);font-size:13px;margin:0 0 56px}
.proof{display:flex;gap:34px;flex-wrap:wrap;padding:22px 0;border-top:1px solid var(--line);
  border-bottom:1px solid var(--line);margin-bottom:64px}
.proof div{font-size:13px;color:var(--dim)}
.proof b{display:block;font-size:26px;color:var(--fg);font-weight:600;letter-spacing:-.01em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-bottom:72px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px}
.card .k{font-size:12px;letter-spacing:.18em;color:var(--dim);text-transform:uppercase}
.card h3{margin:10px 0 8px;font-size:17px;font-weight:600}
.card p{margin:0;color:var(--muted);font-size:14px}
pre{background:#070a10;border:1px solid var(--line);border-radius:12px;padding:18px;overflow:auto;
  font-size:13px;line-height:1.55;color:#c9d1d9}
h2{font-size:26px;letter-spacing:-.01em;margin:0 0 16px;font-weight:650}
section{margin-bottom:72px}
.price{display:flex;align-items:baseline;gap:12px;margin:8px 0 18px}
.price b{font-size:44px;letter-spacing:-.02em}
.price span{color:var(--dim);font-size:14px}
.pay{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.pay .pp{background:#ffc439;color:#111;font-weight:700;padding:14px 22px;border-radius:10px;display:inline-block}
.report-head{display:flex;gap:26px;align-items:center;margin:44px 0 26px;flex-wrap:wrap}
.grade{width:92px;height:92px;border-radius:16px;display:grid;place-items:center;font-size:44px;
  font-weight:700;color:#04140a}
.grade.A{background:#2ea043}.grade.B{background:#3fb950}.grade.C{background:#d29922}
.grade.D{background:#db6d28}.grade.F{background:#f85149}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:11px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:500;font-size:12px;letter-spacing:.1em;text-transform:uppercase}
.sev{font-size:11px;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:999px;
  border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.sev.critical{color:#ff7b72;border-color:#5c2b29}
.sev.high{color:#ff9e64;border-color:#5a3a1e}
.sev.medium{color:#e3b341;border-color:#4d3d14}
.sev.low{color:#8b949e}
.loc{font-size:12.5px;color:#a5b4fc;word-break:break-all}
.share{display:flex;gap:10px;margin:26px 0}
.share input{flex:1;background:var(--panel);border:1px solid var(--line);color:var(--fg);
  padding:12px 14px;border-radius:9px;font-size:13px}
footer{border-top:1px solid var(--line);padding:32px 0 60px;color:var(--dim);font-size:13px;
  display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}
.err{background:#2b0f0f;border:1px solid #5c2b29;color:#ffb4ae;padding:14px 16px;border-radius:10px;margin:20px 0}
.tag{font-size:12px;color:var(--dim)}
"""


def layout(title: str, body: str, *, description: str = "") -> str:
    desc = description or (
        "Launch Guard scans a repository for the three failure modes AI-written code ships with: "
        "credentials that end up public, model calls in loops with no exit, and permission prompts "
        "that got switched off."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<nav>
  <div class="brand"><b>\u25a0</b> Launch Guard</div>
  <div>
    <a class="link" href="/">Scan</a>
    <a class="link" href="/pricing">Pricing</a>
    <a class="link" href="https://github.com/yepinggu66/launchguard">GitHub</a>
  </div>
</nav>
{body}
<footer>
  <div>Launch Guard \u2014 static analysis, no upload, no telemetry.</div>
  <div><a href="/pricing">$29 audit</a> \u00b7 <a href="https://github.com/yepinggu66/launchguard">source</a></div>
</footer>
</div>
</body>
</html>"""


def home(*, error: str = "", repo_value: str = "") -> str:
    err = f'<div class="err">{escape(error)}</div>' if error else ""
    body = f"""
<div class="eyebrow">Static scan \u00b7 public repos \u00b7 ~20s</div>
<h1>The three bugs that<br>AI-written code ships with.</h1>
<p class="lede">A credential that ends up in a file the browser downloads. A model call inside a
loop that has no exit. A permission prompt that got switched off. None of them is a CVE. All three
are billed to you.</p>

{err}
<form class="scan" method="post" action="/scan">
  <input type="text" name="repo" placeholder="owner/repo  \u2014 e.g. unclecode/crawl4ai"
         value="{escape(repo_value)}" autocomplete="off" spellcheck="false">
  <button type="submit">Scan repo</button>
</form>
<p class="hint">Public repositories only. We read the tarball, we do not execute anything.
The report link is the only thing stored.</p>

<div class="proof">
  <div><b>9</b>repos scanned</div>
  <div><b>10,872</b>files</div>
  <div><b>1</b>hardcoded credential</div>
  <div><b>18</b>uncapped model calls</div>
  <div><b>0</b>CVEs involved</div>
</div>

<section class="grid">
  <div class="card"><div class="k">Leak</div><h3>Keys that can be read</h3>
    <p>Provider keys committed, or wired into <code>NEXT_PUBLIC_</code> / <code>VITE_</code> /
    a file that ships to the browser. A key is billable the moment it is public.</p></div>
  <div class="card"><div class="k">Cost</div><h3>Loops with no exit</h3>
    <p><code>while True</code> around a model call, no <code>break</code>, no
    <code>max_tokens</code>, SDK default retries. Valid Python. Passes review.</p></div>
  <div class="card"><div class="k">Perm</div><h3>Approvals switched off</h3>
    <p><code>dangerouslySkipPermissions</code>, <code>allowedTools: ["*"]</code>, a policy that
    allows <code>*</code> by default. A log instead of a gate.</p></div>
</section>

<section>
  <h2>Run it on every pull request</h2>
  <p class="lede" style="margin-bottom:18px">The same engine as a GitHub Action: one comment per PR,
  edited in place, with a paste-ready fix prompt for Cursor or Claude Code.</p>
  <pre>.github/workflows/guard.yml

name: Launch guard
on: pull_request
permissions: {{ contents: read, pull-requests: write }}
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: yepinggu66/launchguard/guard@main
        with: {{ fail-on: critical }}</pre>
</section>

<section>
  <h2>What $29 buys</h2>
  <p class="lede" style="margin-bottom:8px">A human reads the scan, confirms every finding against
  your source, and sends back a fix PR. One repo, one round, 24h turnaround.</p>
  <div class="price"><b>$29</b><span>one-time \u00b7 PayPal \u00b7 per repository</span></div>
  <div class="pay">
    <a class="pp" href="/pricing">Get the audit \u2192</a>
    <span class="tag">or add the Action above \u2014 free for public repos</span>
  </div>
</section>
"""
    return layout("Launch Guard \u2014 the three bugs AI-written code ships with", body)


def report_page(report: dict, *, share_url: str) -> str:
    grade = report["grade"]
    counts = report["summary"]["by_severity"]
    findings = report["findings"]
    rows = []
    for f in findings[:40]:
        rows.append(
            f'<tr><td><span class="sev {escape(f["severity"])}">{escape(f["severity"])}</span></td>'
            f'<td><div class="loc">{escape(f["location"])}</div>'
            f'<div style="color:var(--muted);margin-top:4px">{escape(f["title"])}</div></td>'
            f"<td style=\"color:var(--muted);font-size:13px\">{escape(f['fix'])}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="3" style="color:var(--muted)">Nothing found. That is the point.</td></tr>')

    body = f"""
<div class="report-head">
  <div class="grade {escape(grade)}">{escape(grade)}</div>
  <div>
    <div class="tag">{escape(report['files_scanned'].__str__())} files \u00b7
      {escape(report['duration_ms'].__str__())} ms \u00b7 {escape(report['target'])}</div>
    <h2 style="margin:6px 0 4px">risk {escape(report['risk_score'].__str__())}/100</h2>
    <div class="tag">
      {counts['critical']} critical \u00b7 {counts['high']} high \u00b7
      {counts['medium']} medium \u00b7 {counts['low']} low
    </div>
  </div>
</div>

<h2>Findings</h2>
<table>
<thead><tr><th>Severity</th><th>Where</th><th>Fix</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>

<h2 style="margin-top:48px">Share this report</h2>
<div class="share">
  <input id="share" type="text" value="{escape(share_url)}" readonly>
  <button class="ghost" onclick="navigator.clipboard.writeText(document.getElementById('share').value)">Copy</button>
</div>
<p class="hint" style="margin-bottom:40px">Send it to whoever reviews your PRs. The link is public and read-only.</p>

<div class="card" style="margin-bottom:40px">
  <div class="k">Next</div>
  <h3>Want this before every merge?</h3>
  <p style="margin-bottom:12px">Add the Action below \u2014 free for public repos. Or have a human
  confirm every finding and send back a fix PR for $29.</p>
  <pre>{"- uses: yepinggu66/launchguard/guard@main\n  with: { fail-on: critical }"}</pre>
  <p style="margin-top:14px"><a class="pp" href="/pricing">$29 human audit \u2192</a></p>
</div>
"""
    return layout(f"Launch Guard \u2014 {grade} \u00b7 {report['risk_score']}/100", body)


def pricing_page(*, paypal_me: str, price: str) -> str:
    body = f"""
<div class="eyebrow">Pricing</div>
<h1>Free to scan.<br>Pay for the review.</h1>
<p class="lede">The scanner is open source and runs in your runner for free. What you cannot get
for free is someone reading the output carefully and telling you which three of the twelve findings
actually matter.</p>

<section class="grid">
  <div class="card">
    <div class="k">Free</div>
    <h3>$0 \u00b7 self-serve</h3>
    <p>Scan any public repo on this site. Run the GitHub Action on unlimited repos.
    Badge for your README.</p>
  </div>
  <div class="card" style="border-color:#2ea043">
    <div class="k">Audit</div>
    <h3>$29 \u00b7 one repo</h3>
    <p>I run the scan, verify every finding against your source by hand, drop the false positives,
    and send a fix PR. 24h turnaround.</p>
  </div>
  <div class="card">
    <div class="k">Team</div>
    <h3>$99 \u00b7 up to 5 repos</h3>
    <p>Same review across a monorepo or several services, plus a
    <code>policy.yaml</code> generated from what you actually use.</p>
  </div>
</section>

<section>
  <h2>Pay with PayPal</h2>
  <p class="lede" style="margin-bottom:18px">No account needed \u2014 PayPal handles cards too.
  After paying, put the repository URL and the PayPal transaction id in the form and you will get
  the review by email within 24 hours.</p>
  <div class="pay" style="margin-bottom:26px">
    <a class="pp" target="_blank" rel="noopener"
       href="https://www.paypal.me/{escape(paypal_me)}/{escape(price)}USD">Pay ${escape(price)} with PayPal</a>
    <span class="tag">opens PayPal \u00b7 amount pre-filled \u00b7 USD</span>
  </div>

  <form method="post" action="/order" style="display:grid;gap:12px;max-width:560px">
    <input type="text" name="repo" placeholder="owner/repo you want reviewed" required
           style="background:var(--panel);border:1px solid var(--line);color:var(--fg);padding:14px;border-radius:10px">
    <input type="email" name="email" placeholder="where to send the review" required
           style="background:var(--panel);border:1px solid var(--line);color:var(--fg);padding:14px;border-radius:10px">
    <input type="text" name="txn" placeholder="PayPal transaction id (starts with a letter, 17 chars)" required
           style="background:var(--panel);border:1px solid var(--line);color:var(--fg);padding:14px;border-radius:10px">
    <button type="submit">Submit order</button>
  </form>
</section>
"""
    return layout("Pricing \u2014 Launch Guard", body)


def thanks_page(*, order_id: str, repo: str) -> str:
    body = f"""
<div class="eyebrow">Order received</div>
<h1>Thanks \u2014 order <span class="mono">{escape(order_id)}</span></h1>
<p class="lede">I will verify the payment against PayPal and send the reviewed report for
<span class="mono">{escape(repo)}</span> to your email within 24 hours. If you do not hear back,
reply with the order id above.</p>
<p><a href="/">\u2190 scan another repository</a></p>
"""
    return layout("Order received \u2014 Launch Guard", body)


def error_page(code: int, message: str) -> str:
    body = f"""
<div class="eyebrow">{code}</div>
<h1>{escape(message)}</h1>
<p class="lede"><a href="/">\u2190 back to the scanner</a></p>
"""
    return layout(f"{code} \u2014 Launch Guard", body)
