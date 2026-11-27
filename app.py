import os
import time
from datetime import timedelta
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from sqlalchemy import text
from sqlalchemy.engine import make_url

from models import Profile, db
from routes.admin_roles_pages import admin_roles_pages
from routes.auth_pages import auth_pages
from routes.event_management_pages import event_management_pages
from routes.events_pages import events_pages
from routes.home_pages import home_pages
from routes.labs_pages import labs_pages
from routes.lost_found_pages import lost_found_pages
from routes.profile_pages import profile_pages
from routes.used_items_pages import used_items_pages
from services.csrf import csrf_token
from services.roles import ADMIN_ROLE, EVENT_MANAGER_ROLE, role_label

load_dotenv()

app = Flask(__name__, static_folder="public/static", static_url_path="/static")
STATIC_ASSET_CACHE_AGE = 356 * 24 * 60 * 60
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY must be configured with a strong random value.")
app.config["SECRET_KEY"] = secret_key
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)
app.config["SESSION_REFRESH_EACH_REQUEST"] = True
app.config["MAIL_EMAIL"] = os.getenv("MAIL_EMAIL")
app.config["MAIL_APP_PASSWORD"] = os.getenv("MAIL_APP_PASSWORD")
database_url = os.getenv("DATABASE_URL")
if database_url and database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
database_config = make_url(database_url) if database_url else None
if (
    database_config
    and database_config.get_backend_name() == "postgresql"
    and database_config.port == 6543
):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {"prepare_threshold": None},
    }

db.init_app(app)
migrate = Migrate(app, db)

app.register_blueprint(auth_pages)
app.register_blueprint(events_pages)
app.register_blueprint(labs_pages)
app.register_blueprint(profile_pages)
app.register_blueprint(admin_roles_pages)
app.register_blueprint(event_management_pages)
app.register_blueprint(home_pages)
app.register_blueprint(lost_found_pages)
app.register_blueprint(used_items_pages)


@app.url_defaults
def version_static_assets(endpoint, values):
    if endpoint != "static":
        return

    filename = values.get("filename")
    if not isinstance(filename, str):
        return

    relative_path = Path(filename)
    if (
        relative_path.suffix.lower() not in {".css", ".js"}
        or relative_path.parts[:2] not in {("app", "css"), ("app", "js")}
    ):
        return

    static_root = Path(app.static_folder).resolve()
    asset_path = (static_root / relative_path).resolve()
    if not asset_path.is_relative_to(static_root) or not asset_path.is_file():
        return

    values.setdefault("v", sha256(asset_path.read_bytes()).hexdigest()[:16])


app.add_url_rule("/used-items", endpoint="used_items", view_func=app.view_functions["used_items_pages.used_items"])

app.add_url_rule("/lost-found", endpoint="lost_found", view_func=app.view_functions["lost_found_pages.lost_found"])

@app.context_processor
def inject_template_helpers():
    return {
        "csrf_token": csrf_token,
        "role_label": role_label,
        "admin_role": ADMIN_ROLE,
        "event_manager_role": EVENT_MANAGER_ROLE,
    }


@app.before_request
def load_current_user():
    g.current_user = None
    if request.endpoint == "static":
        return

    profile_id = session.get("profile_id")
    auth_token = session.get("auth_token")

    if profile_id is None and auth_token is None:
        session.pop("user_id", None)
        return

    user = db.session.get(Profile, profile_id) if isinstance(profile_id, int) else None
    if (
        user is None
        or not isinstance(auth_token, str)
        or not isinstance(user.tokens, str)
        or not compare_digest(user.tokens, auth_token)
    ):
        session.pop("profile_id", None)
        session.pop("auth_token", None)
        session.pop("auth_last_activity", None)
        flash("Your session is no longer active. Please log in again.", "error")
        return

    now = time.time()
    last_activity = session.get("auth_last_activity")
    if (
        not isinstance(last_activity, (int, float))
        or isinstance(last_activity, bool)
        or now - last_activity >= app.permanent_session_lifetime.total_seconds()
    ):
        user.tokens = None
        db.session.commit()
        session.pop("profile_id", None)
        session.pop("auth_token", None)
        session.pop("auth_last_activity", None)
        flash("You were logged out after one hour of inactivity.", "error")
        return

    session.permanent = True
    session["auth_last_activity"] = now
    g.current_user = user


@app.after_request
def prevent_authenticated_page_caching(response):
    static_filename = (
        request.view_args.get("filename", "")
        if request.view_args
        else ""
    )
    if (
        request.endpoint == "static"
        and response.status_code == 200
        and isinstance(static_filename, str)
        and static_filename.lower().endswith((".css", ".js"))
    ):
        response.headers["Cache-Control"] = (
            f"public, max-age={STATIC_ASSET_CACHE_AGE}, immutable"
        )
    elif getattr(g, "current_user", None) is not None:
        response.headers["Cache-Control"] = (
            "private, no-store, no-cache, must-revalidate"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    if getattr(g, "current_user", None):
        return redirect(url_for("home"))
    return redirect(url_for("auth_pages.login"))


app.add_url_rule("/home", endpoint="home", view_func=app.view_functions["home_pages.home"])


@app.route("/health")
def health_check():
    db.session.execute(text("SELECT 1"))
    return {"status": "connected"}


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("legal.html", page="privacy")


@app.route("/user-guide")
def user_guide():
    return render_template("legal.html", page="guide")


@app.route("/terms-of-service")
def terms_of_service():
    return render_template("legal.html", page="terms")


if __name__ == "__main__":
    app.run(debug=True)