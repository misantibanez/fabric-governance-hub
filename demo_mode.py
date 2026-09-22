import os
import secrets
from functools import wraps

from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from demo_data import render_demo_endpoint


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
DEMO_SESSION_KEY = "demo_authenticated"
DEMO_CSRF_KEY = "demo_login_csrf"


def is_demo_mode():
    return os.environ.get("DEMO_MODE", "").strip().lower() == "true"


def _safe_return_path(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return url_for("menu")
    return value


def _requires_json_response():
    return request.path.startswith("/gateway-governance/") or request.is_json


def _demo_login():
    if request.method == "GET":
        csrf_token = session.get(DEMO_CSRF_KEY)
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session[DEMO_CSRF_KEY] = csrf_token
        return render_template(
            "demo_login.html",
            csrf_token=csrf_token,
            return_to=_safe_return_path(request.args.get("return_to")),
            error=None,
        )

    expected_csrf = session.pop(DEMO_CSRF_KEY, "")
    submitted_csrf = request.form.get("csrf_token", "")
    configured_username = os.environ.get("DEMO_USERNAME", "demo")
    configured_password_hash = os.environ.get("DEMO_PASSWORD_HASH", "")
    valid_csrf = bool(
        expected_csrf
        and submitted_csrf
        and secrets.compare_digest(expected_csrf, submitted_csrf)
    )
    valid_username = secrets.compare_digest(
        request.form.get("username", ""), configured_username
    )
    valid_password = bool(
        configured_password_hash
        and check_password_hash(
            configured_password_hash, request.form.get("password", "")
        )
    )
    if valid_csrf and valid_username and valid_password:
        session.clear()
        session[DEMO_SESSION_KEY] = True
        session.permanent = True
        return redirect(_safe_return_path(request.form.get("return_to")))

    csrf_token = secrets.token_urlsafe(32)
    session[DEMO_CSRF_KEY] = csrf_token
    return render_template(
        "demo_login.html",
        csrf_token=csrf_token,
        return_to=_safe_return_path(request.form.get("return_to")),
        error="Invalid demo credentials.",
    ), 401


def _demo_logout():
    session.clear()
    return redirect(url_for("demo_login"))


def configure_demo_mode(app):
    if not is_demo_mode():
        return
    if not os.environ.get("FLASK_SECRET_KEY"):
        raise RuntimeError("FLASK_SECRET_KEY is required when DEMO_MODE is enabled.")
    if not os.environ.get("DEMO_PASSWORD_HASH"):
        raise RuntimeError("DEMO_PASSWORD_HASH is required when DEMO_MODE is enabled.")

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(
            os.environ.get("DEMO_COOKIE_SECURE", "true").strip().lower() != "false"
        ),
        PERMANENT_SESSION_LIFETIME=1800,
    )
    app.add_url_rule(
        "/demo/login", "demo_login", _demo_login, methods=["GET", "POST"]
    )
    app.add_url_rule("/demo/logout", "demo_logout", _demo_logout, methods=["POST"])

    @app.before_request
    def enforce_demo_boundary():
        if request.endpoint in {"demo_login", "demo_logout", "static"}:
            return None
        if not session.get(DEMO_SESSION_KEY):
            return redirect(
                url_for("demo_login", return_to=_safe_return_path(request.full_path))
            )
        if request.method not in SAFE_METHODS or request.endpoint == "dev_ws_stream":
            if _requires_json_response():
                return jsonify({
                    "ok": False,
                    "error": "Write operations are disabled in the demo environment.",
                }), 403
            return render_template("demo_forbidden.html"), 403
        return render_demo_endpoint(request.endpoint)

    @app.after_request
    def add_demo_banner(response):
        if (
            response.status_code < 300
            and response.mimetype == "text/html"
            and request.endpoint != "demo_login"
        ):
            banner = render_template(
                "demo_banner.html",
                demo_username=os.environ.get("DEMO_USERNAME", "demo"),
            ).encode("utf-8")
            response.set_data(response.get_data().replace(b"<body>", b"<body>" + banner, 1))
            response.headers.pop("Content-Length", None)
        return response