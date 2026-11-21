import secrets
import time
from datetime import timedelta
from functools import wraps
from hmac import compare_digest

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
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
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from models import PasswordReset, Profile, db, utc_now
from services.password_reset_email import (
    PasswordResetEmailError,
    send_password_reset_email,
)
from services.passwords import password_meets_policy
from services.roles import FOE_DEPARTMENTS, ROLE_VALUES, STUDENT_ROLE

auth_pages = Blueprint("auth_pages", __name__)
microsoft_oauth = OAuth()
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_DURATION = timedelta(minutes=15)
PASSWORD_RESET_LIFETIME = timedelta(minutes=15)
PASSWORD_RESET_MAX_ATTEMPTS = 5


def configure_microsoft_oauth(app):
    microsoft_oauth.init_app(app)
    client_id = app.config.get("MICROSOFT_CLIENT_ID")
    client_secret = app.config.get("MICROSOFT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return

    tenant_id = app.config.get("MICROSOFT_TENANT_ID", "organizations")
    microsoft_oauth.register(
        name="microsoft",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{tenant_id}/v2.0/"
            ".well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid profile email"},
    )


def _email_uses_allowed_domain(email):
    if not isinstance(email, str) or email.count("@") != 1:
        return False
    address, domain = email.strip().lower().rsplit("@", 1)
    allowed_domain = current_app.config.get("MICROSOFT_EMAIL_DOMAIN", "")
    return bool(address) and bool(allowed_domain) and domain == allowed_domain


def _establish_session(user):
    auth_token = secrets.token_urlsafe(32)
    user.tokens = auth_token
    user.failed_login_attempts = 0
    user.login_locked_until = None
    db.session.commit()

    session.clear()
    session.permanent = True
    session["profile_id"] = user.id
    session["auth_token"] = auth_token
    session["auth_last_activity"] = time.time()


def _microsoft_client():
    if not current_app.config.get("MICROSOFT_CLIENT_ID") or not current_app.config.get(
        "MICROSOFT_CLIENT_SECRET"
    ):
        return None
    return microsoft_oauth.create_client("microsoft")


def _issue_password_reset(user):
    PasswordReset.query.filter_by(profile_id=user.id).delete()

    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    reset_entry = PasswordReset(
        profile_id=user.id,
        code=generate_password_hash(otp_code),
        reset_session_token=secrets.token_urlsafe(32),
        expires_at=utc_now() + PASSWORD_RESET_LIFETIME,
    )
    db.session.add(reset_entry)
    db.session.commit()

    try:
        send_password_reset_email(user.primary_email, otp_code)
    except PasswordResetEmailError:
        db.session.delete(reset_entry)
        db.session.commit()
        raise

    return reset_entry


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return redirect(url_for("auth_pages.login"))

        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not getattr(g, "current_user", None) or g.current_user.role not in allowed_roles:
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
        user = Profile.query.filter_by(primary_email=email).with_for_update().first()

        if not user:
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth_pages.login"))

        now = utc_now()
        if user.login_locked_until and now < user.login_locked_until:
            flash("Too many failed login attempts. Please try again in 15 minutes.", "error")
            return redirect(url_for("auth_pages.login"))

        if user.login_locked_until:
            user.login_locked_until = None
            user.failed_login_attempts = 0

        if not check_password_hash(user.password_hash, password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= LOGIN_MAX_FAILED_ATTEMPTS:
                user.login_locked_until = now + LOGIN_LOCKOUT_DURATION
                flash(
                    "Too many failed login attempts. Please try again in 15 minutes.",
                    "error",
                )
            else:
                flash("Invalid email or password.", "error")
            db.session.commit()
            return redirect(url_for("auth_pages.login"))

        user.failed_login_attempts = 0
        user.login_locked_until = None
        if user.role not in ROLE_VALUES:
            db.session.commit()
            flash("This account has an unsupported role.", "error")
            return redirect(url_for("auth_pages.login"))

        _establish_session(user)
        return redirect(url_for("home"))

    return render_template("auth/login.html")


@auth_pages.get("/login/microsoft")
def microsoft_login():
    client = _microsoft_client()
    if client is None:
        flash("Microsoft sign-in is not configured yet.", "error")
        return redirect(url_for("auth_pages.login"))

    redirect_uri = current_app.config.get("MICROSOFT_REDIRECT_URI") or url_for(
        "auth_pages.microsoft_callback", _external=True
    )
    return client.authorize_redirect(redirect_uri)


@auth_pages.get("/login/microsoft/callback")
def microsoft_callback():
    client = _microsoft_client()
    if client is None:
        flash("Microsoft sign-in is not configured yet.", "error")
        return redirect(url_for("auth_pages.login"))

    try:
        token = client.authorize_access_token()
    except OAuthError as error:
        current_app.logger.warning("Microsoft sign-in failed: %s", error.error)
        flash("Microsoft sign-in could not be completed. Please try again.", "error")
        return redirect(url_for("auth_pages.login"))

    identity = token.get("userinfo")
    email = (
        next(
            (
                candidate.strip().lower()
                for candidate in (
                    identity.get("email"),
                    identity.get("preferred_username"),
                )
                if isinstance(candidate, str)
                and _email_uses_allowed_domain(candidate)
            ),
            None,
        )
        if identity
        else None
    )
    name = identity.get("name") if identity else None
    if not _email_uses_allowed_domain(email):
        flash("Use your university Microsoft account to continue.", "error")
        return redirect(url_for("auth_pages.login"))

    email = email.strip().lower()
    user = Profile.query.filter(func.lower(Profile.primary_email) == email).first()
    if user:
        if user.role not in ROLE_VALUES:
            flash("This account has an unsupported role.", "error")
            return redirect(url_for("auth_pages.login"))
        _establish_session(user)
        return redirect(url_for("home"))

    session["microsoft_signup"] = {
        "email": email,
        "name": (
            name.strip()
            if isinstance(name, str) and name.strip()
            else email.split("@", 1)[0]
        ),
    }
    return redirect(url_for("auth_pages.microsoft_signup"))


@auth_pages.route("/signup/microsoft", methods=["GET", "POST"])
def microsoft_signup():
    identity = session.get("microsoft_signup")
    if (
        not isinstance(identity, dict)
        or not _email_uses_allowed_domain(identity.get("email"))
        or not isinstance(identity.get("name"), str)
    ):
        session.pop("microsoft_signup", None)
        flash("Continue with your university Microsoft account to sign up.", "error")
        return redirect(url_for("auth_pages.login"))

    email = identity["email"].strip().lower()
    name = identity["name"].strip()
    if request.method == "POST":
        expected_csrf_token = session.get("_csrf_token")
        submitted_csrf_token = request.form.get("_csrf_token")
        if (
            not isinstance(expected_csrf_token, str)
            or not isinstance(submitted_csrf_token, str)
            or not compare_digest(expected_csrf_token, submitted_csrf_token)
        ):
            abort(400)

        department = request.form.get("department", "")
        student_id = request.form.get("student_id", "").strip() or None
        valid_departments = {code for code, _ in FOE_DEPARTMENTS}

        if department not in valid_departments:
            flash("Choose a valid department.", "error")
            return redirect(url_for("auth_pages.microsoft_signup"))
        if student_id is not None and len(student_id) > 255:
            flash("University ID must be 255 characters or fewer.", "error")
            return redirect(url_for("auth_pages.microsoft_signup"))
        if student_id and Profile.query.filter_by(student_id=student_id).first():
            flash("An account with that University ID already exists.", "error")
            return redirect(url_for("auth_pages.microsoft_signup"))

        user = Profile.query.filter(func.lower(Profile.primary_email) == email).first()
        if user is None:
            user = Profile(
                name=name[:255],
                primary_email=email,
                password_hash=generate_password_hash(secrets.token_urlsafe(32)),
                role=STUDENT_ROLE,
                student_id=student_id,
                department=department,
            )
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                if Profile.query.filter(func.lower(Profile.primary_email) == email).first():
                    flash("An account with this email already exists. Sign in with Outlook.", "error")
                    return redirect(url_for("auth_pages.login"))
                if student_id and Profile.query.filter_by(student_id=student_id).first():
                    flash("An account with that University ID already exists.", "error")
                    return redirect(url_for("auth_pages.microsoft_signup"))
                raise
        elif user.role not in ROLE_VALUES:
            flash("This account has an unsupported role.", "error")
            return redirect(url_for("auth_pages.login"))

        _establish_session(user)
        return redirect(url_for("home"))

    return render_template(
        "auth/microsoft_signup.html",
        identity=identity,
        departments=FOE_DEPARTMENTS,
    )


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

        try:
            _issue_password_reset(user)
        except PasswordResetEmailError:
            current_app.logger.exception("Failed to send a password reset email.")
            session.pop("reset_profile_id", None)
            session.pop("reset_session_token", None)
            flash(
                "Unable to send the verification email. Please try again later.",
                "error",
            )
            return redirect(url_for("auth_pages.forgot_password"))

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

        if reset_entry.attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
            flash("Too many failed attempts. Please request a new code.", "error")
            return redirect(url_for("auth_pages.forgot_password"))

        try:
            code_is_valid = check_password_hash(reset_entry.code, entered_code)
        except ValueError:
            code_is_valid = compare_digest(reset_entry.code, entered_code)

        if len(entered_code) != 6 or not entered_code.isdecimal() or not code_is_valid:
            reset_entry.attempts += 1
            db.session.commit()
            flash("Invalid verification code. Try again.", "error")
            return redirect(url_for("auth_pages.verify_otp"))

        session["reset_session_token"] = reset_entry.reset_session_token
        reset_entry.code = generate_password_hash(secrets.token_urlsafe(32))
        db.session.commit()
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

    try:
        _issue_password_reset(user)
    except PasswordResetEmailError:
        current_app.logger.exception("Failed to resend a password reset email.")
        session.pop("reset_profile_id", None)
        session.pop("reset_session_token", None)
        flash(
            "Unable to send the verification email. Please try again later.",
            "error",
        )
        return redirect(url_for("auth_pages.forgot_password"))

    session["reset_profile_id"] = user.id
    session.pop("reset_session_token", None)
    flash("A new verification code has been sent to your email.", "success")
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

        if not password_meets_policy(password):
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
