import os
import re
import uuid
from datetime import datetime, timezone
from hmac import compare_digest
from urllib.parse import quote

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from models import LostAndFound, Notification, db
from services.csrf import csrf_token
from services.roles import ADMIN_ROLE

lost_found_pages = Blueprint("lost_found_pages", __name__)

CATEGORIES = [
    {"slug": "IDs & Cards", "label": "IDs & Cards", "icon": "🪪"},
    {"slug": "Electronics & Keys", "label": "Electronics & Keys", "icon": "🔑"},
    {"slug": "Books & Notebooks", "label": "Books & Notebooks", "icon": "📓"},
    {"slug": "Bags & Bottles", "label": "Bags & Bottles", "icon": "🎒"},
    {"slug": "Other", "label": "Other Items", "icon": "📦"},
]

CATEGORY_ICONS = {c["slug"]: c["icon"] for c in CATEGORIES}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
STOPWORDS = {
    "the", "and", "for", "with", "from", "near", "inside", "hall", "building",
    "lost", "found", "item", "campus", "foe", "alexandria", "university",
}


def _is_admin(user) -> bool:
    if not user:
        return False
    return getattr(user, "role", None) == ADMIN_ROLE or bool(getattr(user, "is_admin", False))


def _get_account_whatsapp(user) -> str:
    if not user:
        return ""
    for attr in ("phone_number", "phone", "whatsapp_number", "whatsapp"):
        val = getattr(user, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _normalize_whatsapp(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("01") and len(digits) == 11:
        digits = "20" + digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    return digits


def _whatsapp_link(number: str, item_name: str, report_type: str) -> str:
    digits = _normalize_whatsapp(number)
    if not digits:
        return "#"
    action = "found" if report_type == "found" else "lost"
    msg = f"Hi! I saw your Lost & Found post on Student Hub regarding the {action} item: {item_name}."
    return f"https://wa.me/{digits}?text={quote(msg)}"


def _relative_time(dt) -> str:
    if not dt:
        return ""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    seconds = max(int((now - dt).total_seconds()), 0)
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days == 1:
        return "Yesterday"
    return f"{days}d ago"


def _publisher_info(item: LostAndFound, current_user) -> dict:
    is_owner = bool(current_user and item.profile_id == current_user.id)
    if getattr(item, "is_anonymous", False):
        return {
            "name": "Anonymous member (You)" if is_owner else "Anonymous member",
            "initials": "AM",
            "subtitle": "Identity hidden by publisher",
        }
    full_name = (item.reporter.name if item.reporter and item.reporter.name else "Student").strip()
    parts = [p[0].upper() for p in full_name.split()[:2] if p]
    initials = "".join(parts) or "ST"
    dept = getattr(item.reporter, "department", None) or "FOE-AU Student"
    return {
        "name": f"{full_name} (You)" if is_owner else full_name,
        "initials": initials,
        "subtitle": dept,
    }


def _check_csrf():
    submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    expected = csrf_token()
    if not submitted or not expected or not compare_digest(str(submitted), str(expected)):
        abort(400, description="Invalid or missing CSRF token.")


def _save_uploaded_photo(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return None
    upload_dir = os.path.join(current_app.static_folder, "uploads", "lost_found")
    os.makedirs(upload_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(upload_dir, unique_name))
    return f"uploads/lost_found/{unique_name}"


def _delete_local_photo(image_url: str | None):
    if not image_url or not image_url.startswith("uploads/lost_found/"):
        return
    full_path = os.path.join(current_app.static_folder, image_url.replace("/", os.sep))
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
        except OSError:
            pass


def _tokenize(text_val: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", (text_val or "").lower())
    return {w for w in words if w not in STOPWORDS}


def _find_similar_items(item: LostAndFound, limit: int = 4) -> list[LostAndFound]:
    opposite_type = "found" if item.type == "lost" else "lost"
    candidates = (
        LostAndFound.query.filter(
            LostAndFound.status == "open",
            LostAndFound.type == opposite_type,
            LostAndFound.profile_id != item.profile_id,
        )
        .order_by(LostAndFound.created_at.desc())
        .all()
    )

    title_tokens = _tokenize(item.item_name)
    extra_tokens = _tokenize(f"{item.description or ''} {item.location or ''}")

    scored = []
    for cand in candidates:
        cand_title_tokens = _tokenize(cand.item_name)
        cand_all_tokens = cand_title_tokens | _tokenize(f"{cand.description or ''} {cand.location or ''}")

        title_overlap = len(title_tokens & cand_title_tokens)
        general_overlap = len((title_tokens | extra_tokens) & cand_all_tokens)
        same_category = 1 if cand.category == item.category else 0

        score = (title_overlap * 3) + general_overlap + (same_category * 2)
        if title_overlap >= 1 or (same_category and general_overlap >= 1):
            scored.append((score, cand))

    scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
    return [cand for _, cand in scored[:limit]]


def _notify_matching_users(new_item: LostAndFound):
    matches = _find_similar_items(new_item, limit=5)
    for match in matches:
        if new_item.type == "lost":
            db.session.add(
                Notification(
                    profile_id=new_item.profile_id,
                    title="Possible Found Match",
                    description=f"A Found item '{match.item_name}' ({match.location or 'Campus'}) matches your lost '{new_item.item_name}'.",
                )
            )
            db.session.add(
                Notification(
                    profile_id=match.profile_id,
                    title="Someone Lost a Similar Item",
                    description=f"A student reported losing '{new_item.item_name}', similar to the '{match.item_name}' you found.",
                )
            )
        else:
            db.session.add(
                Notification(
                    profile_id=new_item.profile_id,
                    title="Matching Lost Report",
                    description=f"A student reported losing '{match.item_name}' ({match.location or 'Campus'}), matching your found '{new_item.item_name}'.",
                )
            )
            db.session.add(
                Notification(
                    profile_id=match.profile_id,
                    title="Similar Item Just Found!",
                    description=f"Someone found '{new_item.item_name}' near {new_item.location or 'Campus'}, matching your lost '{match.item_name}'.",
                )
            )
    if matches:
        db.session.commit()


@lost_found_pages.before_request
def require_login():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))


@lost_found_pages.route("/lost-found")
def lost_found():
    view_filter = request.args.get("view", "all").strip().lower()
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()
    user_id = g.current_user.id

    base_query = LostAndFound.query.filter_by(status="open")

    counts = {
        "all": base_query.count(),
        "found": base_query.filter_by(type="found").count(),
        "lost": base_query.filter_by(type="lost").count(),
        "mine": base_query.filter_by(profile_id=user_id).count(),
    }

    query = base_query
    if view_filter == "found":
        query = query.filter_by(type="found")
    elif view_filter == "lost":
        query = query.filter_by(type="lost")
    elif view_filter == "mine":
        query = query.filter_by(profile_id=user_id)
    else:
        view_filter = "all"

    if category_filter:
        query = query.filter_by(category=category_filter)

    if search_query:
        like_term = f"%{search_query}%"
        query = query.filter(
            or_(
                LostAndFound.item_name.ilike(like_term),
                LostAndFound.location.ilike(like_term),
                LostAndFound.description.ilike(like_term),
                LostAndFound.category.ilike(like_term),
            )
        )

    items = query.order_by(LostAndFound.created_at.desc()).all()
    is_admin = _is_admin(g.current_user)

    cards = []
    for item in items:
        pub = _publisher_info(item, g.current_user)
        is_owner = item.profile_id == user_id
        cards.append(
            {
                "id": item.id,
                "report_type": item.type,
                "title": item.item_name,
                "category": item.category,
                "category_icon": CATEGORY_ICONS.get(item.category, "📦"),
                "location": item.location or "FOE-AU Campus",
                "image_url": item.image_url,
                "time_ago": _relative_time(item.date or item.created_at),
                "publisher_name": pub["name"],
                "whatsapp_url": _whatsapp_link(item.phone_number, item.item_name, item.type),
                "is_owner": is_owner,
                "can_edit": is_owner,
                "can_delete": is_owner or is_admin,
            }
        )

    return render_template(
        "lost_found/lost_found.html",
        cards=cards,
        counts=counts,
        categories=CATEGORIES,
        active_view=view_filter,
        active_category=category_filter,
        search_query=search_query,
    )


@lost_found_pages.route("/lost-found/<int:item_id>")
def item_details(item_id: int):
    item = db.session.get(LostAndFound, item_id)
    if not item or item.status != "open":
        abort(404)

    user_id = g.current_user.id
    is_owner = item.profile_id == user_id
    is_admin = _is_admin(g.current_user)
    pub = _publisher_info(item, g.current_user)

    raw_suggestions = _find_similar_items(item, limit=3)
    suggestions = []
    for s in raw_suggestions:
        s_pub = _publisher_info(s, g.current_user)
        suggestions.append(
            {
                "id": s.id,
                "title": s.item_name,
                "report_type": s.type,
                "category": s.category,
                "category_icon": CATEGORY_ICONS.get(s.category, "📦"),
                "location": s.location or "FOE-AU Campus",
                "time_ago": _relative_time(s.date or s.created_at),
                "publisher_name": s_pub["name"],
                "whatsapp_url": _whatsapp_link(s.phone_number, s.item_name, s.type),
            }
        )

    return render_template(
        "lost_found/item_details.html",
        item=item,
        category_icon=CATEGORY_ICONS.get(item.category, "📦"),
        publisher=pub,
        time_ago=_relative_time(item.date or item.created_at),
        whatsapp_url=_whatsapp_link(item.phone_number, item.item_name, item.type),
        is_owner=is_owner,
        can_edit=is_owner,
        can_delete=is_owner or is_admin,
        suggestions=suggestions,
    )


@lost_found_pages.route("/lost-found/new", methods=["GET", "POST"])
def create_item():
    account_whatsapp = _get_account_whatsapp(g.current_user)

    if request.method == "POST":
        _check_csrf()

        report_type = request.form.get("report_type", "found").strip().lower()
        if report_type not in ("found", "lost"):
            report_type = "found"

        item_name = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        is_anonymous = request.form.get("is_anonymous") == "on"
        whatsapp_mode = request.form.get("whatsapp_mode", "account")
        temp_whatsapp = request.form.get("temp_whatsapp", "").strip()

        chosen_whatsapp = account_whatsapp if whatsapp_mode == "account" else temp_whatsapp

        if not item_name or not category or not location:
            flash("Please fill in item name, category, and campus location.", "error")
            return render_template(
                "lost_found/report_form.html",
                mode="create",
                item=None,
                categories=CATEGORIES,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        if len(_normalize_whatsapp(chosen_whatsapp)) < 10:
            flash("Please provide a valid WhatsApp number (from your account or a temporary one).", "error")
            return render_template(
                "lost_found/report_form.html",
                mode="create",
                item=None,
                categories=CATEGORIES,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        photo_file = request.files.get("photo")
        image_url = _save_uploaded_photo(photo_file)
        if photo_file and photo_file.filename and not image_url:
            flash("Photo must be a PNG, JPG, or WEBP image.", "error")
            return render_template(
                "lost_found/report_form.html",
                mode="create",
                item=None,
                categories=CATEGORIES,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        new_item = LostAndFound(
            profile_id=g.current_user.id,
            item_name=item_name,
            type=report_type,
            category=category,
            location=location,
            description=description or "No additional notes provided.",
            phone_number=chosen_whatsapp,
            date=datetime.now(timezone.utc).replace(tzinfo=None),
            is_anonymous=is_anonymous,
            image_url=image_url,
            status="open",
        )
        db.session.add(new_item)
        db.session.commit()

        _notify_matching_users(new_item)
        flash("Your Lost & Found report has been published!", "success")
        return redirect(url_for("lost_found_pages.item_details", item_id=new_item.id))

    return render_template(
        "lost_found/report_form.html",
        mode="create",
        item=None,
        categories=CATEGORIES,
        account_whatsapp=account_whatsapp,
        form_data={},
    )


@lost_found_pages.route("/lost-found/<int:item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id: int):
    item = db.session.get(LostAndFound, item_id)
    if not item or item.status != "open":
        abort(404)

    # Strictly publisher only (admins cannot edit another user's post)
    if item.profile_id != g.current_user.id:
        abort(403)

    account_whatsapp = _get_account_whatsapp(g.current_user)

    if request.method == "POST":
        _check_csrf()

        report_type = request.form.get("report_type", item.type).strip().lower()
        if report_type in ("found", "lost"):
            item.type = report_type

        item_name = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        is_anonymous = request.form.get("is_anonymous") == "on"
        whatsapp_mode = request.form.get("whatsapp_mode", "account")
        temp_whatsapp = request.form.get("temp_whatsapp", "").strip()

        chosen_whatsapp = account_whatsapp if whatsapp_mode == "account" else temp_whatsapp

        if not item_name or not category or not location:
            flash("Item name, category, and campus location are required.", "error")
            return render_template(
                "lost_found/report_form.html",
                mode="edit",
                item=item,
                categories=CATEGORIES,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        if len(_normalize_whatsapp(chosen_whatsapp)) < 10:
            flash("Please provide a valid WhatsApp number.", "error")
            return render_template(
                "lost_found/report_form.html",
                mode="edit",
                item=item,
                categories=CATEGORIES,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        photo_file = request.files.get("photo")
        if photo_file and photo_file.filename:
            new_image_url = _save_uploaded_photo(photo_file)
            if not new_image_url:
                flash("Photo must be a PNG, JPG, or WEBP image.", "error")
                return render_template(
                    "lost_found/report_form.html",
                    mode="edit",
                    item=item,
                    categories=CATEGORIES,
                    account_whatsapp=account_whatsapp,
                    form_data=request.form,
                )
            _delete_local_photo(item.image_url)
            item.image_url = new_image_url

        item.item_name = item_name
        item.category = category
        item.location = location
        item.description = description or "No additional notes provided."
        item.phone_number = chosen_whatsapp
        item.is_anonymous = is_anonymous

        db.session.commit()
        flash("Report updated successfully.", "success")
        return redirect(url_for("lost_found_pages.item_details", item_id=item.id))

    return render_template(
        "lost_found/report_form.html",
        mode="edit",
        item=item,
        categories=CATEGORIES,
        account_whatsapp=account_whatsapp,
        form_data={},
    )


@lost_found_pages.route("/lost-found/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id: int):
    _check_csrf()
    item = db.session.get(LostAndFound, item_id)
    if not item:
        abort(404)

    # Publisher OR Admin can delete
    if item.profile_id != g.current_user.id and not _is_admin(g.current_user):
        abort(403)

    _delete_local_photo(item.image_url)
    db.session.delete(item)
    db.session.commit()

    flash("Post deleted permanently.", "success")
    return redirect(url_for("lost_found_pages.lost_found"))


@lost_found_pages.route("/lost-found/<int:item_id>/returned", methods=["POST"])
def mark_returned(item_id: int):
    _check_csrf()
    item = db.session.get(LostAndFound, item_id)
    if not item:
        abort(404)

    # Publisher marks the item as returned -> automatically deleted from database
    if item.profile_id != g.current_user.id:
        abort(403)

    _delete_local_photo(item.image_url)
    db.session.delete(item)
    db.session.commit()

    flash("Item marked as returned to its original owner and removed from the database.", "success")
    return redirect(url_for("lost_found_pages.lost_found"))