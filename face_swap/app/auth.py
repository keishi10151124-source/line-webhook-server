"""One owner account, configured with OWNER_EMAIL and OWNER_PASSWORD_HASH."""
import hmac
import time
from functools import wraps

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .models import User

bp = Blueprint("auth", __name__)
_failures: dict[str, list[float]] = {}


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            if request.path.startswith("/api/"):
                return {"error": "ログインしてください"}, 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def _rate_limited(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < 600]
    _failures[ip] = recent
    return len(recent) >= 10


@bp.route("/login", methods=["GET", "POST"])
def login():
    cfg = current_app.extensions["face_swap"]["cfg"]
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if _rate_limited(ip):
            flash("試行回数が多すぎます。10分ほど待ってください", "error")
            return render_template("login.html"), 429
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ok = (cfg.OWNER_EMAIL and cfg.OWNER_PASSWORD_HASH
              and hmac.compare_digest(email, cfg.OWNER_EMAIL.lower())
              and check_password_hash(cfg.OWNER_PASSWORD_HASH, password))
        if not ok:
            _failures.setdefault(ip, []).append(time.time())
            flash("メールアドレスかパスワードが違います", "error")
            return render_template("login.html"), 401
        user = g.db.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = User(email=email)
            g.db.add(user)
            g.db.commit()
        session.clear()
        session["uid"] = user.id
        nxt = request.args.get("next") or ""
        return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("views.home"))
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
