"""face-swap: put your own face into your own videos, always labelled as AI-generated."""
import logging
import secrets
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, abort, g, request, session

from .config import Config
from .faces import get_engine
from .models import Base, User, make_session_factory
from .providers import make_provider
from .safety import make_checker
from .storage import make_storage


def create_app(cfg: Config | None = None, *, engine_factory=None, checker=None, provider=None, storage=None) -> Flask:
    cfg = cfg or Config()
    cfg.validate()
    from .c2pa_cert import ensure_cert
    ensure_cert(cfg)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.SECRET_KEY,
        MAX_CONTENT_LENGTH=cfg.MAX_VIDEO_BYTES + 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cfg.is_production,
    )
    if cfg.DATABASE_URL.startswith("sqlite:///"):
        Path(cfg.DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    db_engine, Session = make_session_factory(cfg.DATABASE_URL)
    Base.metadata.create_all(db_engine)

    app.extensions["face_swap"] = ctx = {
        "cfg": cfg,
        "Session": Session,
        "storage": storage or make_storage(cfg),
        "engine_factory": engine_factory or (lambda: get_engine(cfg.FACE_MODELS_DIR)),
        "checker": checker or make_checker(cfg),
        "provider": provider or make_provider(cfg),
        "workdir": tempfile.mkdtemp(prefix="face_swap_jobs_"),
    }

    @app.before_request
    def _open_db():
        g.db = Session()
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = g.db.get(User, uid)
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.endpoint not in ("auth.login", "static"):
            token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not token or token != session.get("csrf"):
                abort(400, "CSRF token missing or wrong")

    @app.teardown_request
    def _close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def _csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf"], "app_env": cfg.APP_ENV,
                "dev_provider": ctx["provider"].name.startswith("dev_"),
                "dev_safety": getattr(ctx["checker"], "name", "") == "dev_allow"}

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=()")
        return resp

    from .views import bp as views_bp
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)

    if cfg.RUN_JOBS_INLINE:
        _start_inline_worker(ctx)
    return app


def _start_inline_worker(ctx):
    from .jobs import run_pending

    def loop():
        while True:
            try:
                n = run_pending(ctx["Session"], storage=ctx["storage"], engine_factory=ctx["engine_factory"],
                                checker=ctx["checker"], provider=ctx["provider"], cfg=ctx["cfg"],
                                workdir=ctx["workdir"])
            except Exception:
                logging.exception("inline worker")
                n = 0
            time.sleep(0.5 if n else 2)

    threading.Thread(target=loop, daemon=True, name="inline-worker").start()
