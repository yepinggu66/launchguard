"""Launch Guard web app: scan a public repo, get a shareable report, buy an audit."""

from __future__ import annotations

import os
import secrets
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "guard") not in sys.path:
    sys.path.insert(0, str(ROOT / "guard"))

from guard.render import badge_svg  # noqa: E402

from . import pages, scanner, store  # noqa: E402

PAYPAL_ME = os.environ.get("PAYPAL_ME", "pinggu80")
PRICE = os.environ.get("PRICE_USD", "29")
# A Payment Link (paypal.com/ncp/payment/...) is a real hosted checkout with
# buyer protection; paypal.me is a peer-to-peer transfer. Both work, so the app
# takes whichever one is configured.
PAYPAL_LINK = os.environ.get("PAYPAL_LINK") or f"https://www.paypal.me/{PAYPAL_ME}/{PRICE}USD"
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
    return HTMLResponse(pages.report_page(payload, share_url=share))


@app.get("/pricing", response_class=HTMLResponse)
def pricing() -> str:
    return pages.pricing_page(paypal_link=PAYPAL_LINK, price=PRICE)


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
    return RedirectResponse(f"/thanks/{order_id}?repo={quote(repo_value)}", status_code=303)


@app.get("/thanks/{order_id}", response_class=HTMLResponse)
def thanks(order_id: str, repo: str = "") -> str:
    return pages.thanks_page(order_id=order_id, repo=repo or "your repository")


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
