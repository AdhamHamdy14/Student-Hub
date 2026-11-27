import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from models import (
    EventReservation,
    LabReservation,
    LostAndFound,
    Notification,
    PasswordReset,
    Profile,
    SavedItem,
    StarredEvent,
    UsedItem,
    db,
)
from services.csrf import csrf_protect
from services.passwords import password_meets_policy
from services.roles import (
    ADMIN_ROLE,
    FOE_DEPARTMENTS,
    ROLE_CHOICES,
    ROLE_VALUES,
    ta_department_for_role,
)

admin_roles_pages = Blueprint("admin_roles_pages", __name__, url_prefix="/admin/roles")


@admin_roles_pages.before_request
def require_admin():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))
    if g.current_user.role != ADMIN_ROLE:
        abort(403)


@admin_roles_pages.get("/")
def index():
    profiles = Profile.query.order_by(
        func.lower(Profile.name).asc(),
        func.lower(Profile.primary_email).asc(),
    ).all()
    return render_template(
        "admin/roles.html",
        profiles=profiles,
        role_choices=ROLE_CHOICES,
        departments=FOE_DEPARTMENTS,
        department_codes={code for code, _ in FOE_DEPARTMENTS},
    )


@admin_roles_pages.post("/<int:profile_id>/delete")
@csrf_protect
def delete_account(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        abort(404)
    if profile.id == g.current_user.id:
        flash("You cannot delete your own administrator account.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if (
        profile.role == ADMIN_ROLE
        and Profile.query.filter_by(role=ADMIN_ROLE).count() <= 1
    ):
        flash("The last administrator cannot be deleted.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    owned_item_ids = db.session.query(UsedItem.id).filter_by(profile_id=profile.id)
    SavedItem.query.filter(
        (SavedItem.profile_id == profile.id)
        | SavedItem.used_item_id.in_(owned_item_ids)
    ).delete(synchronize_session=False)
    for model in (
        LabReservation,
        EventReservation,
        LostAndFound,
        Notification,
        PasswordReset,
        StarredEvent,
        UsedItem,
    ):
        model.query.filter_by(profile_id=profile.id).delete(synchronize_session=False)

    email = profile.primary_email
    db.session.delete(profile)
    db.session.commit()
    flash(f"Account deleted for {email}.", "success")
    return redirect(url_for("admin_roles_pages.index"))


@admin_roles_pages.post("/create")
@csrf_protect
def create_account():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "")
    student_id = request.form.get("student_id", "").strip() or None
    requested_department = request.form.get("department", "").strip()

    if not name or len(name) > 255:
        flash("Enter a name up to 255 characters.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if (
        len(email) > 255
        or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None
    ):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if not password_meets_policy(password):
        flash("Password must be at least 8 characters with 1 number or symbol.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if role not in ROLE_VALUES:
        flash("Choose a valid role.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if student_id is not None and len(student_id) > 255:
        flash("University ID must be 255 characters or fewer.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if requested_department and len(requested_department) > 255:
        flash("Department must be 255 characters or fewer.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if ta_department_for_role(role) is None and requested_department not in {
        department for department, _ in FOE_DEPARTMENTS
    }:
        flash("Choose a valid department.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if Profile.query.filter(func.lower(Profile.primary_email) == email).first():
        flash("An account with that email already exists.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if student_id and Profile.query.filter_by(student_id=student_id).first():
        flash("An account with that University ID already exists.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    profile = Profile(
        name=name,
        primary_email=email,
        password_hash=generate_password_hash(password),
        role=role,
        student_id=student_id,
        department=ta_department_for_role(role) or requested_department or "Unassigned",
    )
    db.session.add(profile)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if Profile.query.filter(func.lower(Profile.primary_email) == email).first():
            flash("An account with that email already exists.", "error")
            return redirect(url_for("admin_roles_pages.index"))
        if student_id and Profile.query.filter_by(student_id=student_id).first():
            flash("An account with that University ID already exists.", "error")
            return redirect(url_for("admin_roles_pages.index"))
        raise

    flash(f"Account created for {email}.", "success")
    return redirect(url_for("admin_roles_pages.index"))


@admin_roles_pages.post("/<int:profile_id>")
@csrf_protect
def update_role(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        abort(404)

    new_role = request.form.get("role", "")
    if new_role not in ROLE_VALUES:
        flash("Choose a valid role.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    if profile.id == g.current_user.id and new_role != ADMIN_ROLE:
        flash("You cannot change your own administrator role.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    if (
        profile.role == ADMIN_ROLE
        and new_role != ADMIN_ROLE
        and Profile.query.filter_by(role=ADMIN_ROLE).count() <= 1
    ):
        flash("The last administrator cannot be demoted.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    profile.role = new_role
    db.session.commit()
    flash(f"Role updated for {profile.primary_email}.", "success")
    return redirect(url_for("admin_roles_pages.index"))


@admin_roles_pages.post("/<int:profile_id>/edit")
@csrf_protect
def edit_account(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        abort(404)

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone_number = request.form.get("phone_number", "").strip() or None
    secondary_email = request.form.get("secondary_email", "").strip().lower() or None
    student_id = request.form.get("student_id", "").strip() or None
    department = request.form.get("department", "").strip()
    role = request.form.get("role", "")
    password = request.form.get("password", "")

    if not name or len(name) > 255:
        flash("Enter a name up to 255 characters.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if (
        len(email) > 255
        or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None
    ):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if role not in ROLE_VALUES:
        flash("Choose a valid role.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if phone_number is not None and len(phone_number) > 255:
        flash("Phone number must be 255 characters or fewer.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if secondary_email is not None and (
        len(secondary_email) > 255
        or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", secondary_email) is None
    ):
        flash("Enter a valid secondary email address.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if secondary_email == email:
        flash("The secondary email must differ from the primary email.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if student_id is not None and len(student_id) > 255:
        flash("University ID must be 255 characters or fewer.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if (
        department not in {code for code, _ in FOE_DEPARTMENTS}
        and department != profile.department
    ):
        flash("Choose a valid department.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if password and not password_meets_policy(password):
        flash("Password must be at least 8 characters with 1 number or symbol.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    email_owner = Profile.query.filter(
        Profile.id != profile.id,
        or_(
            func.lower(Profile.primary_email) == email,
            func.lower(Profile.secondary_email) == email,
        ),
    ).first()
    if email_owner:
        flash("That email address is already associated with another account.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    if secondary_email and Profile.query.filter(
        Profile.id != profile.id,
        or_(
            func.lower(Profile.primary_email) == secondary_email,
            func.lower(Profile.secondary_email) == secondary_email,
        ),
    ).first():
        flash("That email address is already associated with another account.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    if student_id and Profile.query.filter(
        Profile.id != profile.id,
        Profile.student_id == student_id,
    ).first():
        flash("An account with that University ID already exists.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    if phone_number and Profile.query.filter(
        Profile.id != profile.id,
        Profile.phone_number == phone_number,
    ).first():
        flash("That phone number is already associated with another account.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    if profile.id == g.current_user.id and role != ADMIN_ROLE:
        flash("You cannot change your own administrator role.", "error")
        return redirect(url_for("admin_roles_pages.index"))
    if (
        profile.role == ADMIN_ROLE
        and role != ADMIN_ROLE
        and Profile.query.filter_by(role=ADMIN_ROLE).count() <= 1
    ):
        flash("The last administrator cannot be demoted.", "error")
        return redirect(url_for("admin_roles_pages.index"))

    profile.name = name
    profile.primary_email = email
    profile.secondary_email = secondary_email
    profile.phone_number = phone_number
    profile.student_id = student_id
    profile.department = ta_department_for_role(role) or department
    profile.role = role
    if password:
        profile.password_hash = generate_password_hash(password)
        profile.tokens = None

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if Profile.query.filter(
            Profile.id != profile.id,
            or_(
                func.lower(Profile.primary_email) == email,
                func.lower(Profile.secondary_email) == email,
                func.lower(Profile.primary_email) == secondary_email,
                func.lower(Profile.secondary_email) == secondary_email,
            ),
        ).first():
            flash("That email address is already associated with another account.", "error")
            return redirect(url_for("admin_roles_pages.index"))
        if student_id and Profile.query.filter(
            Profile.id != profile.id,
            Profile.student_id == student_id,
        ).first():
            flash("An account with that University ID already exists.", "error")
            return redirect(url_for("admin_roles_pages.index"))
        if phone_number and Profile.query.filter(
            Profile.id != profile.id,
            Profile.phone_number == phone_number,
        ).first():
            flash("That phone number is already associated with another account.", "error")
            return redirect(url_for("admin_roles_pages.index"))
        raise

    flash(f"Account updated for {email}.", "success")
    return redirect(url_for("admin_roles_pages.index"))
