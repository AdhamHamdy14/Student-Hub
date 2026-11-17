import re
import secrets
from datetime import timedelta
from functools import wraps
from hmac import compare_digest

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from models import PasswordReset, Profile, db, utc_now

auth_pages = Blueprint("auth_pages", __name__)
SUPPORTED_ROLES = frozenset({"admin", "teaching_assistant", "student"})


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        profile_id = session.get("profile_id")
        auth_token = session.get("auth_token")
        if not profile_id or not isinstance(auth_token, str):
            session.clear()
            return redirect(url_for("auth_pages.login"))

        user = db.session.get(Profile, profile_id)
        if (
            user is None
            or not isinstance(user.tokens, str)
            or not compare_digest(user.tokens, auth_token)
        ):
            session.clear()
            flash("Your session is no longer active. Please log in again.", "error")
            return redirect(url_for("auth_pages.login"))

        g.current_user = user
        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.current_user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


@auth_pages.get("/")
def index():
    return redirect(url_for("auth_pages.login"))


@auth_pages.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = Profile.query.filter_by(primary_email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth_pages.login"))

        if user.role not in SUPPORTED_ROLES:
            flash("This account has an unsupported role.", "error")
            return redirect(url_for("auth_pages.login"))

        auth_token = secrets.token_urlsafe(32)
        user.tokens = auth_token
        db.session.commit()

        session.clear()
        session["profile_id"] = user.id
        session["auth_token"] = auth_token
        return redirect(url_for("home"))

    return render_template("auth/login.html")


@auth_pages.post("/logout")
def logout():
    profile_id = session.get("profile_id")
    auth_token = session.get("auth_token")

    if profile_id and isinstance(auth_token, str):
        user = db.session.get(Profile, profile_id)
        if (
            user is not None
            and isinstance(user.tokens, str)
            and compare_digest(user.tokens, auth_token)
        ):
            user.tokens = None
            db.session.commit()

    session.clear()
    return redirect(url_for("auth_pages.login"))


@auth_pages.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = Profile.query.filter_by(primary_email=email).first()

        if not user:
            flash("No account found with this email address.", "error")
            return redirect(url_for("auth_pages.forgot_password"))

        PasswordReset.query.filter_by(profile_id=user.id).delete()

        otp_code = f"{secrets.randbelow(1_000_000):06d}"
        reset_token = secrets.token_urlsafe(32)
        reset_entry = PasswordReset(
            profile_id=user.id,
            code=otp_code,
            reset_session_token=reset_token,
            expires_at=utc_now() + timedelta(minutes=10),
        )
        db.session.add(reset_entry)
        db.session.commit()

        if current_app.debug:
            current_app.logger.debug("Password reset code for %s: %s", email, otp_code)

        session["reset_profile_id"] = user.id
        return redirect(url_for("auth_pages.verify_otp"))

    return render_template("auth/forgot_password.html")


@auth_pages.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    profile_id = session.get("reset_profile_id")
    if not profile_id:
        return redirect(url_for("auth_pages.forgot_password"))

    if request.method == "POST":
        entered_code = "".join(request.form.getlist("digits")).strip()
        reset_entry = (
            PasswordReset.query.filter_by(profile_id=profile_id)
            .order_by(PasswordReset.id.desc())
            .first()
        )

        if not reset_entry or utc_now() >= reset_entry.expires_at:
            flash("Verification code expired. Please request a new one.", "error")
            return redirect(url_for("auth_pages.forgot_password"))

        if reset_entry.attempts >= 5:
            flash("Too many failed attempts. Please request a new code.", "error")
            return redirect(url_for("auth_pages.forgot_password"))

        if (
            len(entered_code) != 6
            or not entered_code.isdecimal()
            or entered_code != reset_entry.code
        ):
            reset_entry.attempts += 1
            db.session.commit()
            flash("Invalid verification code. Try again.", "error")
            return redirect(url_for("auth_pages.verify_otp"))

        session["reset_session_token"] = reset_entry.reset_session_token
        return redirect(url_for("auth_pages.reset_password"))

    return render_template("auth/verify_otp.html")


@auth_pages.post("/resend-otp")
def resend_otp():
    profile_id = session.get("reset_profile_id")
    if not profile_id:
        return redirect(url_for("auth_pages.forgot_password"))

    user = db.session.get(Profile, profile_id)
    if not user:
        session.pop("reset_profile_id", None)
        session.pop("reset_session_token", None)
        flash("Account not found. Please start over.", "error")
        return redirect(url_for("auth_pages.forgot_password"))

    PasswordReset.query.filter_by(profile_id=profile_id).delete()
    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    reset_entry = PasswordReset(
        profile_id=profile_id,
        code=otp_code,
        reset_session_token=secrets.token_urlsafe(32),
        expires_at=utc_now() + timedelta(minutes=10),
    )
    db.session.add(reset_entry)
    db.session.commit()
    session.pop("reset_session_token", None)

    if current_app.debug:
        current_app.logger.debug("Password reset code for %s: %s", user.primary_email, otp_code)

    flash("A new verification code has been generated.", "success")
    return redirect(url_for("auth_pages.verify_otp"))


@auth_pages.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    profile_id = session.get("reset_profile_id")
    token = session.get("reset_session_token")

    if not profile_id or not token:
        return redirect(url_for("auth_pages.forgot_password"))

    reset_entry = PasswordReset.query.filter_by(
        profile_id=profile_id, reset_session_token=token
    ).first()

    if not reset_entry or utc_now() >= reset_entry.expires_at:
        flash("Session expired. Please start over.", "error")
        return redirect(url_for("auth_pages.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if len(password) < 8 or not re.search(r"[0-9\W_]", password):
            flash("Password must be at least 8 characters with 1 number or symbol.", "error")
            return redirect(url_for("auth_pages.reset_password"))

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("auth_pages.reset_password"))

        user = db.session.get(Profile, profile_id)
        if not user:
            flash("Account not found. Please start over.", "error")
            return redirect(url_for("auth_pages.forgot_password"))

        user.password_hash = generate_password_hash(password)
        user.tokens = None
        db.session.delete(reset_entry)
        db.session.commit()
        session.pop("reset_profile_id", None)
        session.pop("reset_session_token", None)

        flash("Password updated successfully. You can now log in.", "success")
        return redirect(url_for("auth_pages.login"))

    return render_template("auth/reset_password.html")
