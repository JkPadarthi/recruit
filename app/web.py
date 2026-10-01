"""Web page routes (HTML via Jinja). API lives in main.py."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import settings
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
        {"brand": settings.brand_name, "authed": _authed(request)})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"brand": settings.brand_name})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {"brand": settings.brand_name})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if not _authed(request):
        return templates.TemplateResponse(request, "login.html", {"brand": settings.brand_name})
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
         "is_admin": is_admin})


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if not _authed(request):
        return templates.TemplateResponse(request, "login.html", {"brand": settings.brand_name})
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
         "is_admin": is_admin})


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
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#07070b",
        "theme_color": "#07070b",
        "icons": [
            {"src": "/static/icon-192.png?v=2", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-384.png?v=2", "sizes": "384x384", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-512.png?v=2", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    })