"""Launch Guard web app: scan a public repo, get a shareable report, buy an audit."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "guard") not in sys.path:
    sys.path.insert(0, str(ROOT / "guard"))

from guard.render import badge_svg  # noqa: E402

from . import pages, scanner, store  # noqa: E402

PAYPAL_ME = os.environ.get("PAYPAL_ME", "pinggu80")
PRICE = os.environ.get("PRICE_USD", "29")
AGENTPROOF_URL = os.environ.get("AGENTPROOF_URL", pages.AGENTPROOF_URL)

# A Payment Link (paypal.com/ncp/payment/...) is a real hosted checkout with
# buyer protection; paypal.me is a peer-to-peer transfer. Both work, so each
# tier takes whichever one is configured for it.
AUDIT_LINK = (
    os.environ.get("PAYPAL_LINK_29")
    or os.environ.get("PAYPAL_LINK")
    or f"https://www.paypal.me/{PAYPAL_ME}/{PRICE}USD"
)
TEAM_LINK = os.environ.get("PAYPAL_LINK_99") or f"https://www.paypal.me/{PAYPAL_ME}/99USD"

ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
ORDER_WEBHOOK_URL = os.environ.get("ORDER_WEBHOOK_URL", "")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "yepinggu@outlook.com")
PAYPAL_SANDBOX = os.environ.get("PAYPAL_SANDBOX", "").lower() in ("1", "true", "yes")
PAYPAL_RECEIVER = os.environ.get("PAYPAL_RECEIVER", "").strip().lower()
IPN_VERIFY_URL = (
    "https://ipnpb.sandbox.paypal.com/cgi-bin/webscr"
    if PAYPAL_SANDBOX
    else "https://ipnpb.paypal.com/cgi-bin/webscr"
)
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "6"))
RATE_WINDOW = 3600
BADGE_TTL = 6 * 3600

app = FastAPI(title="Launch Guard", docs_url=None, redoc_url=None)

_rate: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


@app.on_event("startup")
def _startup() -> None:
    store.init()


# --------------------------------------------------------------------------- helpers


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        stamps = [t for t in _rate.get(ip, []) if now - t < RATE_WINDOW]
        if len(stamps) >= RATE_LIMIT:
            _rate[ip] = stamps
            return False
        stamps.append(now)
        _rate[ip] = stamps
    return True


def _base(request: Request) -> str:
    url = str(request.base_url).rstrip("/")
    return url.replace("http://", "https://") if "railway.app" in url else url


class _BadgeView:
    """badge_svg only needs the grade and the blocker count."""

    def __init__(self, grade: str, blockers: int) -> None:
        self.grade = grade
        self.blockers = [None] * blockers


def _notify(order: dict) -> None:
    """Tell the seller an order landed. Fire-and-forget: a webhook that is down
    must never block the buyer's redirect."""
    if not ORDER_WEBHOOK_URL:
        return

    def run() -> None:
        try:
            request = urllib.request.Request(
                ORDER_WEBHOOK_URL,
                data=json.dumps(order).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "launchguard/1.0"},
            )
            urllib.request.urlopen(request, timeout=5).read()
        except Exception:  # noqa: BLE001 - notification is best-effort
            pass

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- pages


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return pages.home()


@app.post("/scan")
def scan_submit(request: Request, repo: str = Form(...)):
    if not _allow(_client_ip(request)):
        return HTMLResponse(
            pages.error_page(429, "Too many scans from this network. Try again later."),
            status_code=429,
        )
    try:
        owner, name = scanner.parse_repo(repo)
        payload = scanner.scan_github(owner, name)
    except scanner.ScanError as error:
        return HTMLResponse(pages.home(error=str(error), repo_value=repo), status_code=400)
    except Exception:  # noqa: BLE001 - never leak a traceback to a visitor
        return HTMLResponse(
            pages.home(error="The scan failed on our side. Try again in a minute.", repo_value=repo),
            status_code=500,
        )

    report_id = secrets.token_urlsafe(7)
    store.save_report(report_id, f"{owner}/{name}", payload)
    return RedirectResponse(f"/r/{report_id}", status_code=303)


@app.get("/r/{report_id}", response_class=HTMLResponse)
def report_page(request: Request, report_id: str):
    payload = store.get_report(report_id)
    if not payload:
        return HTMLResponse(pages.error_page(404, "That report is gone."), status_code=404)
    share = f"{_base(request)}/r/{report_id}"
    return HTMLResponse(pages.report_page(payload, share_url=share, noindex=True))


@app.get("/pricing", response_class=HTMLResponse)
def pricing() -> str:
    return pages.pricing_page(
        audit_link=AUDIT_LINK,
        team_link=TEAM_LINK,
        price=PRICE,
        agentproof_url=AGENTPROOF_URL,
    )


@app.post("/order")
def create_order(
    request: Request,
    repo: str = Form(...),
    email: str = Form(...),
    txn: str = Form(...),
):
    repo_value = repo.strip()
    email_value = email.strip()
    txn_value = txn.strip()
    if "@" not in email_value or "." not in email_value.split("@")[-1]:
        return HTMLResponse(pages.error_page(400, "That email does not look right."), status_code=400)
    if len(txn_value) < 6:
        return HTMLResponse(pages.error_page(400, "Paste the PayPal transaction id."), status_code=400)
    order_id = "LG-" + secrets.token_hex(3).upper()
    store.save_order(order_id, repo_value, email_value, txn_value)
    _notify(
        {
            "order_id": order_id,
            "repo": repo_value,
            "email": email_value,
            "txn": txn_value,
            "created_at": int(time.time()),
        }
    )
    return RedirectResponse(
        f"/thanks/{order_id}?repo={quote(repo_value)}&email={quote(email_value)}", status_code=303
    )


@app.get("/thanks/{order_id}", response_class=HTMLResponse)
def thanks(order_id: str, repo: str = "", email: str = "") -> str:
    return pages.thanks_page(order_id=order_id, repo=repo or "your repository", email=email)


@app.get("/terms", response_class=HTMLResponse)
def terms() -> str:
    return pages.terms_page(contact=CONTACT_EMAIL)


@app.get("/privacy", response_class=HTMLResponse)
def privacy() -> str:
    return pages.privacy_page(contact=CONTACT_EMAIL)


# --------------------------------------------------------------------------- admin


def _admin_ok(key: str) -> bool:
    return bool(ADMIN_KEY) and secrets.compare_digest(key, ADMIN_KEY)


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(key: str = ""):
    if not _admin_ok(key):
        return HTMLResponse(pages.error_page(404, "Not found."), status_code=404)
    return HTMLResponse(pages.admin_page(orders=store.list_orders(), key=key))


@app.post("/admin/orders/{order_id}")
def admin_set_status(order_id: str, key: str = Form(""), status: str = Form("delivered")):
    if not _admin_ok(key):
        return HTMLResponse(pages.error_page(404, "Not found."), status_code=404)
    store.set_order_status(order_id, status.strip()[:20] or "delivered")
    return RedirectResponse(f"/admin/orders?key={quote(key)}", status_code=303)


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, **store.stats()})


# --------------------------------------------------------------------------- api


@app.post("/api/scan")
def api_scan(request: Request, body: dict):
    if not _allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="rate limited")
    try:
        if body.get("repo"):
            owner, name = scanner.parse_repo(str(body["repo"]))
            return store_and_return(scanner.scan_github(owner, name), f"{owner}/{name}")
        if body.get("code"):
            payload = scanner.scan_snippet(str(body["code"]), str(body.get("filename") or "code.py"))
            return store_and_return(payload, str(payload["target"]))
    except scanner.ScanError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=400, detail="send {repo} or {code}")


def store_and_return(payload: dict, source: str) -> JSONResponse:
    report_id = secrets.token_urlsafe(7)
    store.save_report(report_id, source, payload)
    return JSONResponse({"id": report_id, "report": payload})


# --------------------------------------------------------------------------- paypal


def _verify_ipn(raw: bytes) -> bool:
    """PayPal only tells the truth if you ask it back. Echo the body to the
    verification endpoint and require the literal word VERIFIED."""
    payload = b"cmd=_notify-validate&" + raw
    request = urllib.request.Request(
        IPN_VERIFY_URL,
        data=payload,
        headers={
            "User-Agent": "launchguard/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", "replace").strip() == "VERIFIED"
    except Exception:  # noqa: BLE001 - a network blip must not create an order
        return False


@app.post("/api/paypal/ipn")
async def paypal_ipn(request: Request):
    raw = await request.body()
    if not raw:
        return Response("empty", status_code=400)
    if not await run_in_threadpool(_verify_ipn, raw):
        return Response("invalid", status_code=400)

    form = parse_qs(raw.decode("utf-8", "replace"))

    def get(key: str, default: str = "") -> str:
        return (form.get(key) or [default])[0]

    if get("payment_status") != "Completed":
        return Response("ignored", status_code=200)
    if get("mc_currency", "USD").upper() != "USD":
        return Response("ignored", status_code=200)
    try:
        gross = float(get("mc_gross") or 0)
    except ValueError:
        gross = 0.0
    if gross + 0.5 < float(PRICE):
        return Response("underpaid", status_code=200)
    if PAYPAL_RECEIVER and PAYPAL_RECEIVER not in (
        get("receiver_email").lower(),
        get("business").lower(),
    ):
        return Response("wrong receiver", status_code=200)

    txn = get("txn_id")
    if not txn:
        return Response("no txn", status_code=200)
    if store.order_exists_txn(txn):
        return Response("duplicate", status_code=200)

    order_id = "PP-" + txn[-8:].upper()
    # The button's "custom message box" lands in `memo`; a hosted button can also
    # carry `custom`. Either one is the buyer telling us which repo to review,
    # which is the only thing PayPal cannot know on its own.
    repo = (get("memo") or get("custom") or get("item_name") or "paypal button").strip()[:200]
    store.save_order(
        order_id,
        repo,
        get("payer_email") or "unknown",
        txn,
        status="paid",
    )
    _notify(
        {
            "order_id": order_id,
            "repo": repo,
            "email": get("payer_email"),
            "txn": txn,
            "gross": gross,
            "source": "paypal-ipn",
            "created_at": int(time.time()),
        }
    )
    return Response("ok", status_code=200)


@app.get("/badge/{owner}/{repo}.svg")
def badge(owner: str, repo: str):
    key = f"badge-{owner}-{repo}"
    payload = store.get_report(key)
    if not payload or store.get_report_age(key) > BADGE_TTL:
        try:
            payload = scanner.scan_github(owner, repo)
        except scanner.ScanError:
            return Response(status_code=404)
        store.save_report(key, f"badge:{owner}/{repo}", payload)
    counts = payload["summary"]["by_severity"]
    view = _BadgeView(payload["grade"], counts["critical"] + counts["high"])
    return Response(
        content=badge_svg(view),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.exception_handler(404)
def not_found(request: Request, exc):  # noqa: ANN001
    return HTMLResponse(pages.error_page(404, "Not found."), status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8788")))
