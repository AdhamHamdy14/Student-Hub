import os

from dotenv import load_dotenv
from flask import Flask, g, redirect, render_template, session, url_for
from flask_migrate import Migrate
from sqlalchemy import text

from models import Profile, db
from routes.auth_pages import auth_pages
from routes.events_pages import events_pages

load_dotenv()

app = Flask(__name__, static_folder="public/static", static_url_path="/static")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

database_url = os.getenv("DATABASE_URL")
if database_url and database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)

app.register_blueprint(auth_pages)
app.register_blueprint(events_pages)


@app.before_request
def load_current_user():
    if getattr(g, "current_user", None) is None:
        user_id = session.get("profile_id") or session.get("user_id")
        if user_id:
            g.current_user = db.session.get(Profile, user_id)


@app.route("/")
def index():
    if getattr(g, "current_user", None):
        return redirect(url_for("home"))
    return redirect(url_for("auth_pages.login"))


@app.route("/home")
def home():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))
    return render_template("home.html")


@app.route("/labs")
def labs():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))
    return render_template("labs.html")


@app.route("/health")
def health_check():
    db.session.execute(text("SELECT 1"))
    return {"status": "connected"}


if __name__ == "__main__":
    app.run(debug=True)