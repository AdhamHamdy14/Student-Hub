import re
import secrets
import time
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
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from models import PendingSignup, PasswordReset, Profile, db, utc_now
from services.csrf import csrf_protect
from services.password_reset_email import (
    PasswordResetEmailError,
    send_password_reset_email,
    send_signup_verification_email,
)
from services.passwords import password_meets_policy
from services.roles import FOE_DEPARTMENTS, ROLE_VALUES, STUDENT_ROLE

auth_pages = Blueprint("auth_pages", __name__)
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_DURATION = timedelta(minutes=15)
PASSWORD_RESET_LIFETIME = timedelta(minutes=15)
PASSWORD_RESET_MAX_ATTEMPTS = 5
SIGNUP_EMAIL_DOMAIN = "alexu.edu.eg"
SIGNUP_OTP_LIFETIME = timedelta(minutes=15)
SIGNUP_OTP_MAX_ATTEMPTS = 5
SIGNUP_OTP_RESEND_COOLDOWN = timedelta(seconds=60)


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


@auth_pages.route("/signup", methods=["GET", "POST"])
@csrf_protect
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department = request.form.get("department", "").strip()
        student_id = request.form.get("student_id", "").strip()
        valid_departments = {code for code, _ in FOE_DEPARTMENTS}

        if not name or len(name) > 255:
            flash("Enter your name (255 characters or fewer).", "error")
            return redirect(url_for("auth_pages.signup"))
        if (
            len(email) > 255
            or re.fullmatch(
                rf"[^@\s]+@{re.escape(SIGNUP_EMAIL_DOMAIN)}", email
            )
            is None
        ):
            flash(
                f"Use a valid email ending in @{SIGNUP_EMAIL_DOMAIN}.",
                "error",
            )
            return redirect(url_for("auth_pages.signup"))
        if not password_meets_policy(password):
            flash("Password must be at least 8 characters with 1 number or symbol.", "error")
            return redirect(url_for("auth_pages.signup"))
        if department not in valid_departments:
            flash("Choose a valid department.", "error")
            return redirect(url_for("auth_pages.signup"))
        if not student_id or len(student_id) > 255:
            flash(
                "University ID is required and must be 255 characters or fewer.",
                "error",
            )
            return redirect(url_for("auth_pages.signup"))
        now = utc_now()
        expired_signups = PendingSignup.query.filter(
            PendingSignup.expires_at <= now
        ).delete(synchronize_session=False)
        if expired_signups:
            db.session.commit()
        if Profile.query.filter(
            func.lower(Profile.primary_email) == email
        ).first():
            flash("An account with this email already exists. Please log in.", "error")
            return redirect(url_for("auth_pages.login"))
        if Profile.query.filter_by(student_id=student_id).first():
            flash("An account with that University ID already exists.", "error")
            return redirect(url_for("auth_pages.signup"))
        pending_id = PendingSignup.query.filter_by(student_id=student_id).first()
        if pending_id and pending_id.email != email:
            flash("A signup with that University ID is already pending.", "error")
            return redirect(url_for("auth_pages.signup"))

        pending = PendingSignup.query.filter_by(email=email).first()
        if pending and now - pending.requested_at < SIGNUP_OTP_RESEND_COOLDOWN:
            session["signup_email"] = email
            flash("A verification code was just sent. Check your email.", "success")
            return redirect(url_for("auth_pages.verify_signup_otp"))

        if pending is None:
            pending = PendingSignup(email=email)
            db.session.add(pending)
        pending.name = name
        pending.password_hash = generate_password_hash(password)
        pending.department = department
        pending.student_id = student_id
        verification_code = _prepare_signup_verification(pending)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            if Profile.query.filter(
                func.lower(Profile.primary_email) == email
            ).first():
                flash("An account with this email already exists. Please log in.", "error")
                return redirect(url_for("auth_pages.login"))
            if Profile.query.filter_by(student_id=student_id).first():
                flash("An account with that University ID already exists.", "error")
                return redirect(url_for("auth_pages.signup"))
            raise

        session["signup_email"] = email
        try:
            _send_signup_verification(pending, verification_code)
        except PasswordResetEmailError:
            current_app.logger.exception("Failed to send a signup verification email.")
            session.pop("signup_email", None)
            flash("Unable to send the verification email. Please try again later.", "error")
            return redirect(url_for("auth_pages.signup"))

        flash("A verification code has been sent to your university email.", "success")
        return redirect(url_for("auth_pages.verify_signup_otp"))

    return render_template("auth/signup.html", departments=FOE_DEPARTMENTS)


def _prepare_signup_verification(pending):
    code = f"{secrets.randbelow(1_000_000):06d}"
    pending.code_hash = generate_password_hash(code)
    pending.expires_at = utc_now() + SIGNUP_OTP_LIFETIME
    pending.attempts = 0
    pending.requested_at = utc_now()
    return code


def _send_signup_verification(pending, code):
    db.session.commit()
    try:
        send_signup_verification_email(pending.email, code)
    except PasswordResetEmailError:
        db.session.delete(pending)
        db.session.commit()
        raise


@auth_pages.route("/signup/verify", methods=["GET", "POST"])
@csrf_protect
def verify_signup_otp():
    email = session.get("signup_email")
    if not isinstance(email, str):
        return redirect(url_for("auth_pages.signup"))

    pending = PendingSignup.query.filter_by(email=email).first()
    if not pending or utc_now() >= pending.expires_at:
        if pending:
            db.session.delete(pending)
            db.session.commit()
        session.pop("signup_email", None)
        flash("Verification code expired. Please sign up again.", "error")
        return redirect(url_for("auth_pages.signup"))

    if request.method == "POST":
        if pending.attempts >= SIGNUP_OTP_MAX_ATTEMPTS:
            flash("Too many incorrect codes. Request a new code to continue.", "error")
            return redirect(url_for("auth_pages.signup"))

        entered_code = "".join(request.form.getlist("digits")).strip()
        code_is_valid = (
            len(entered_code) == 6
            and entered_code.isdecimal()
            and check_password_hash(pending.code_hash, entered_code)
        )
        if not code_is_valid:
            pending.attempts += 1
            db.session.commit()
            flash("Invalid verification code. Try again.", "error")
            return redirect(url_for("auth_pages.verify_signup_otp"))

        if Profile.query.filter(
            func.lower(Profile.primary_email) == email
        ).first():
            db.session.delete(pending)
            db.session.commit()
            session.pop("signup_email", None)
            flash("An account with this email already exists. Please log in.", "error")
            return redirect(url_for("auth_pages.login"))
        if Profile.query.filter_by(student_id=pending.student_id).first():
            db.session.delete(pending)
            db.session.commit()
            session.pop("signup_email", None)
            flash("An account with that University ID already exists.", "error")
            return redirect(url_for("auth_pages.signup"))

        user = Profile(
            name=pending.name,
            primary_email=pending.email,
            password_hash=pending.password_hash,
            role=STUDENT_ROLE,
            student_id=pending.student_id,
            department=pending.department,
        )
        db.session.add(user)
        db.session.delete(pending)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if Profile.query.filter(
                func.lower(Profile.primary_email) == email
            ).first():
                flash("An account with this email already exists. Please log in.", "error")
                session.pop("signup_email", None)
                return redirect(url_for("auth_pages.login"))
            if Profile.query.filter_by(student_id=pending.student_id).first():
                flash("An account with that University ID already exists.", "error")
                session.pop("signup_email", None)
                return redirect(url_for("auth_pages.signup"))
            raise

        session.pop("signup_email", None)
        _establish_session(user)
        return redirect(url_for("home"))

    return render_template("auth/verify_signup_otp.html")


@auth_pages.post("/signup/resend-otp")
@csrf_protect
def resend_signup_otp():
    email = session.get("signup_email")
    if not isinstance(email, str):
        return redirect(url_for("auth_pages.signup"))

    pending = PendingSignup.query.filter_by(email=email).first()
    if not pending or utc_now() >= pending.expires_at:
        if pending:
            db.session.delete(pending)
            db.session.commit()
        session.pop("signup_email", None)
        flash("Signup expired. Please submit the form again.", "error")
        return redirect(url_for("auth_pages.signup"))

    if utc_now() - pending.requested_at < SIGNUP_OTP_RESEND_COOLDOWN:
        flash("Please wait a minute before requesting another code.", "error")
        return redirect(url_for("auth_pages.verify_signup_otp"))

    verification_code = _prepare_signup_verification(pending)
    try:
        _send_signup_verification(pending, verification_code)
    except PasswordResetEmailError:
        current_app.logger.exception("Failed to resend a signup verification email.")
        session.pop("signup_email", None)
        flash("Unable to send the verification email. Please try again later.", "error")
        return redirect(url_for("auth_pages.signup"))

    flash("A new verification code has been sent.", "success")
    return redirect(url_for("auth_pages.verify_signup_otp"))


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
