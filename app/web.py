"""Web page routes (HTML via Jinja). API lives in main.py."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .apk import apk_info
from .security import verify_session_token

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web"])


def _authed(request: Request) -> bool:
    token = request.cookies.get(settings.session_cookie_name, "")
    return verify_session_token(token) is not None


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(
        request, "landing.html",
        {"brand": settings.brand_name, "authed": _authed(request), "apk": apk_info()})


@router.get("/app", response_class=HTMLResponse)
def app_page(request: Request):
    """The Android download page.

    Its own page rather than a block inside the login form: a sideload is a decision
    that needs the three steps spelled out, and burying that under a password field
    made it read as clutter.
    """
    return templates.TemplateResponse(
        request, "app_download.html",
        {"brand": settings.brand_name, "authed": _authed(request), "apk": apk_info()})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request, "login.html", {"brand": settings.brand_name, "apk": apk_info()})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        request, "register.html", {"brand": settings.brand_name, "apk": apk_info()})


@router.get("/verify", response_class=HTMLResponse)
def verify_page(request: Request):
    return templates.TemplateResponse(
        request, "verify.html", {"brand": settings.brand_name, "apk": apk_info()})


def _needs_verification(request: Request) -> bool:
    """True when the cookie is valid but the address was never proven."""
    if not _authed(request):
        return False
    from app.main import _current_user, db as module_db
    try:
        with module_db.session() as s:
            return not _current_user(request, s).email_verified
    except Exception:
        return False


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if _needs_verification(request):
        return RedirectResponse("/verify", status_code=303)
    if not _authed(request):
        return templates.TemplateResponse(
        request, "login.html", {"brand": settings.brand_name, "apk": apk_info()})
    from app.main import _current_user, db as module_db
    is_admin = False
    try:
        with module_db.session() as s:
            is_admin = _current_user(request, s).is_admin
    except Exception:
        is_admin = False
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"brand": settings.brand_name,
         "vapid_public_key": settings.vapid_public_key,
         "public_base_url": settings.public_base_url,
         "is_admin": is_admin,
         "apk": apk_info()})


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if _needs_verification(request):
        return RedirectResponse("/verify", status_code=303)
    if not _authed(request):
        return templates.TemplateResponse(
        request, "login.html", {"brand": settings.brand_name, "apk": apk_info()})
    from app.main import _current_user, db as module_db
    is_admin = False
    try:
        with module_db.session() as s:
            is_admin = bool(getattr(_current_user(request, s), "is_admin", False))
    except Exception:
        is_admin = False
    return templates.TemplateResponse(
        request, "profile.html",
        {"brand": settings.brand_name,
         "vapid_public_key": settings.vapid_public_key,
         "public_base_url": settings.public_base_url,
         "is_admin": is_admin,
         "apk": apk_info()})


@router.get("/sw.js")
def service_worker():
    # Serve the service worker from root scope (/) so it controls /dashboard
    p = Path(__file__).resolve().parent.parent / "static" / "sw.js"
    return HTMLResponse(p.read_text(), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.get("/manifest.json")
def manifest():
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "name": settings.brand_name,
        "short_name": settings.brand_name,
        "start_url": "/dashboard#hits",
        "display": "standalone",
        "background_color": "#0E1715",
        "theme_color": "#0E1715",
        "icons": [
            {"src": "/static/icon-192.png?v=3", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icon-384.png?v=3", "sizes": "384x384", "type": "image/png", "purpose": "any"},
            {"src": "/static/icon-512.png?v=3", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            # Separate file, padded into the middle 80% circle: Android masks a
            # maskable icon and would otherwise crop the dot off the corner.
            {"src": "/static/icon-maskable-512.png?v=3", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    })