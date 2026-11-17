import os

from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from sqlalchemy import text

from models import Profile, db
from routes.auth_pages import auth_pages

load_dotenv()

app = Flask(__name__, static_folder="public/static", static_url_path="/static")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)
app.register_blueprint(auth_pages)


@app.route("/health")
def health_check():
    db.session.execute(text("SELECT 1"))
    users_count = Profile.query.count()
    return {"status": "connected", "profiles_count": users_count}



if __name__ == "__main__":
    app.run(debug=True)
