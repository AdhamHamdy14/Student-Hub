import re
import secrets
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from models import Profile, db
from services.csrf import csrf_protect
from services.passwords import password_meets_policy

profile_pages = Blueprint("profile_pages", __name__, url_prefix="/profile")
MAX_PROFILE_PHOTO_SIZE = 2 * 1024 * 1024
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PROFILE_PHOTO_PATTERN = re.compile(r"profile_\d+_[0-9a-f]{32}\.(?:png|jpg)")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


@profile_pages.before_request
def require_login():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))


def _upload_folder():
    configured_folder = current_app.config.get("PROFILE_UPLOAD_FOLDER")
    if configured_folder:
        return Path(configured_folder)
    return Path(current_app.instance_path) / "profile_uploads"


def _stored_photo_path(filename):
    if (
        not isinstance(filename, str)
        or PROFILE_PHOTO_PATTERN.fullmatch(filename) is None
    ):
        return None
    return _upload_folder() / filename


def _remove_stored_photo(filename):
    path = _stored_photo_path(filename)
    if path is None:
        return True
    try:
        path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.exception("Unable to remove a profile photo.")
        return False
    return True


@profile_pages.get("/")
def index():
    return render_template("profile/profile.html", profile=g.current_user)


@profile_pages.post("/update")
@csrf_protect
def update():
    profile = g.current_user
    name = request.form.get("name", "").strip()
    phone_number = request.form.get("phone_number", "").strip() or None
    secondary_email = request.form.get("secondary_email", "").strip().lower() or None

    if not name or len(name) > 255:
        flash("Enter a name up to 255 characters.", "error")
        return redirect(url_for("profile_pages.index"))
    if phone_number is not None and len(phone_number) > 255:
        flash("Enter a phone number up to 255 characters.", "error")
        return redirect(url_for("profile_pages.index"))
    if secondary_email is not None:
        if (
            len(secondary_email) > 255
            or EMAIL_PATTERN.fullmatch(secondary_email) is None
        ):
            flash("Enter a valid secondary email address.", "error")
            return redirect(url_for("profile_pages.index"))
        if secondary_email == profile.primary_email.lower():
            flash("The secondary email must differ from the primary email.", "error")
            return redirect(url_for("profile_pages.index"))

        email_owner = Profile.query.filter(
            Profile.id != profile.id,
            or_(
                func.lower(Profile.primary_email) == secondary_email,
                func.lower(Profile.secondary_email) == secondary_email,
            ),
        ).first()
        if email_owner:
            flash("That email address is already associated with another account.", "error")
            return redirect(url_for("profile_pages.index"))

    if phone_number and Profile.query.filter(
        Profile.id != profile.id,
        Profile.phone_number == phone_number,
    ).first():
        flash("That phone number is already associated with another account.", "error")
        return redirect(url_for("profile_pages.index"))

    profile.name = name
    profile.phone_number = phone_number
    profile.secondary_email = secondary_email
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        email_owner = (
            Profile.query.filter(
                Profile.id != profile.id,
                or_(
                    func.lower(Profile.primary_email) == secondary_email,
                    func.lower(Profile.secondary_email) == secondary_email,
                ),
            ).first()
            if secondary_email
            else None
        )
        phone_owner = (
            Profile.query.filter(
                Profile.id != profile.id,
                Profile.phone_number == phone_number,
            ).first()
            if phone_number
            else None
        )
        if email_owner:
            flash("That email address is already associated with another account.", "error")
            return redirect(url_for("profile_pages.index"))
        if phone_owner:
            flash("That phone number is already associated with another account.", "error")
            return redirect(url_for("profile_pages.index"))
        raise

    flash("Profile details updated.", "success")
    return redirect(url_for("profile_pages.index"))


@profile_pages.post("/password")
@csrf_protect
def update_password():
    profile = g.current_user
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(profile.password_hash, current_password):
        flash("The current password is incorrect.", "error")
        return redirect(url_for("profile_pages.index"))
    if not password_meets_policy(new_password):
        flash(
            "Password must be at least 8 characters with 1 number or symbol.",
            "error",
        )
        return redirect(url_for("profile_pages.index"))
    if new_password != confirm_password:
        flash("The new passwords do not match.", "error")
        return redirect(url_for("profile_pages.index"))

    profile.password_hash = generate_password_hash(new_password)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to update a profile password.")
        flash("Unable to update the password. Please try again.", "error")
        return redirect(url_for("profile_pages.index"))

    flash("Password updated successfully.", "success")
    return redirect(url_for("profile_pages.index"))


@profile_pages.post("/photo")
@csrf_protect
def update_photo():
    profile = g.current_user
    old_filename = profile.profile_image_url

    if request.form.get("action") == "remove":
        if not old_filename:
            flash("There is no profile photo to remove.", "error")
            return redirect(url_for("profile_pages.index"))
        profile.profile_image_url = None
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Unable to remove a profile photo.")
            flash("Unable to remove the profile photo. Please try again.", "error")
            return redirect(url_for("profile_pages.index"))
        if _remove_stored_photo(old_filename):
            flash("Profile photo removed.", "success")
        else:
            flash("Profile photo was removed, but its stored file could not be deleted.", "error")
        return redirect(url_for("profile_pages.index"))

    photo = request.files.get("profile_photo")
    if photo is None or not photo.filename:
        flash("Choose a JPG or PNG photo to upload.", "error")
        return redirect(url_for("profile_pages.index"))

    photo_data = photo.stream.read(MAX_PROFILE_PHOTO_SIZE + 1)
    if len(photo_data) > MAX_PROFILE_PHOTO_SIZE:
        flash("Profile photos must be 2MB or smaller.", "error")
        return redirect(url_for("profile_pages.index"))
    if photo_data.startswith(PNG_SIGNATURE):
        extension = "png"
    elif photo_data.startswith(JPEG_SIGNATURE):
        extension = "jpg"
    else:
        flash("Choose a valid JPG or PNG photo.", "error")
        return redirect(url_for("profile_pages.index"))

    filename = f"profile_{profile.id}_{secrets.token_hex(16)}.{extension}"
    upload_folder = _upload_folder()
    destination = upload_folder / filename
    try:
        upload_folder.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(photo_data)
    except OSError:
        current_app.logger.exception("Unable to store a profile photo.")
        flash("Unable to save the profile photo. Please try again.", "error")
        return redirect(url_for("profile_pages.index"))

    profile.profile_image_url = filename
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception("Unable to clean up an unsaved profile photo.")
        current_app.logger.exception("Unable to update a profile photo.")
        flash("Unable to save the profile photo. Please try again.", "error")
        return redirect(url_for("profile_pages.index"))

    if not _remove_stored_photo(old_filename):
        flash("Photo uploaded, but the previous photo could not be deleted.", "error")
    else:
        flash("Profile photo updated.", "success")
    return redirect(url_for("profile_pages.index"))


@profile_pages.get("/photo/<path:filename>")
def photo(filename):
    if g.current_user.profile_image_url != filename:
        abort(404)
    path = _stored_photo_path(filename)
    if path is None or not path.is_file():
        abort(404)
    return send_from_directory(_upload_folder(), filename, conditional=True)
