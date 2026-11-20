import os
import re
import uuid
from decimal import Decimal, InvalidOperation
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

from models import SavedItem, UsedItem, db
from services.csrf import csrf_token
from services.roles import ADMIN_ROLE

used_items_pages = Blueprint("used_items_pages", __name__)

CATEGORIES = [
    {"slug": "Electronics & Kits", "label": "Electronics & Kits", "icon": "🔌"},
    {"slug": "Books & Notes", "label": "Books & Notes", "icon": "📘"},
    {"slug": "Drafting Tools", "label": "Drafting Tools", "icon": "📐"},
    {"slug": "Lab Gear & Coats", "label": "Lab Gear & Coats", "icon": "🦺"},
    {"slug": "Other", "label": "Other Items", "icon": "📦"},
]

CONDITIONS = ["Like New", "Very Good", "Good", "Fair"]
CATEGORY_ICONS = {c["slug"]: c["icon"] for c in CATEGORIES}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def _is_admin(user) -> bool:
    if not user:
        return False
    return getattr(user, "role", None) == ADMIN_ROLE or bool(getattr(user, "is_admin", False))


def _get_account_whatsapp(user) -> str:
    if not user:
        return ""
    val = getattr(user, "phone_number", None)
    return val.strip() if isinstance(val, str) and val.strip() else ""


def _normalize_whatsapp(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("01") and len(digits) == 11:
        digits = "20" + digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    return digits


def _whatsapp_link(number: str, item_name: str, listing_type: str) -> str:
    digits = _normalize_whatsapp(number)
    if not digits:
        return "#"
    intent = "free donation" if listing_type == "free" else "listing"
    msg = f"Hi! I'm interested in your {intent} on Student Hub: {item_name}."
    return f"https://wa.me/{digits}?text={quote(msg)}"


def _format_price(price_val) -> str:
    if price_val is None:
        return "0 EGP"
    dec = Decimal(str(price_val))
    if dec == dec.to_integral_value():
        return f"{int(dec)} EGP"
    return f"{dec:.2f} EGP"


def _seller_info(item: UsedItem, current_user) -> dict:
    is_owner = bool(current_user and item.profile_id == current_user.id)
    if getattr(item, "is_anonymous", False):
        return {
            "name": "Anonymous member (You)" if is_owner else "Anonymous member",
            "initials": "AM",
            "department": "Identity hidden by seller",
        }
    full_name = (item.seller.name if item.seller and item.seller.name else "Student").strip()
    parts = [p[0].upper() for p in full_name.split()[:2] if p]
    initials = "".join(parts) or "ST"
    dept = getattr(item.seller, "department", None) or "FOE-AU Student"
    return {
        "name": f"{full_name} (You)" if is_owner else full_name,
        "initials": initials,
        "department": dept,
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
    upload_dir = os.path.join(current_app.static_folder, "uploads", "used_items")
    os.makedirs(upload_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(upload_dir, unique_name))
    return f"uploads/used_items/{unique_name}"


def _delete_local_photo(image_url: str | None):
    if not image_url or not image_url.startswith("uploads/used_items/"):
        return
    full_path = os.path.join(current_app.static_folder, image_url.replace("/", os.sep))
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
        except OSError:
            pass


def _parse_price(raw_price: str) -> Decimal | None:
    cleaned = (raw_price or "").strip()
    if not cleaned:
        return None
    try:
        val = Decimal(cleaned)
    except InvalidOperation:
        return None
    if val <= 0 or val > Decimal("999999.99"):
        return None
    return val.quantize(Decimal("0.01"))


@used_items_pages.before_request
def require_login():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))


@used_items_pages.route("/used-items")
def used_items():
    view_filter = request.args.get("view", "all").strip().lower()
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()
    user_id = g.current_user.id

    base_query = UsedItem.query.filter_by(status="available")
    saved_ids = {
        row.used_item_id
        for row in SavedItem.query.filter_by(profile_id=user_id).all()
    }

    counts = {
        "all": base_query.count(),
        "free": base_query.filter_by(listing_type="free").count(),
        "sale": base_query.filter_by(listing_type="sale").count(),
        "mine": base_query.filter_by(profile_id=user_id).count(),
        "saved": base_query.filter(UsedItem.id.in_(saved_ids)).count() if saved_ids else 0,
    }

    query = base_query
    if view_filter == "free":
        query = query.filter_by(listing_type="free")
    elif view_filter == "sale":
        query = query.filter_by(listing_type="sale")
    elif view_filter == "mine":
        query = query.filter_by(profile_id=user_id)
    elif view_filter == "saved":
        query = query.filter(UsedItem.id.in_(saved_ids)) if saved_ids else query.filter(False)
    else:
        view_filter = "all"

    if category_filter:
        query = query.filter_by(category=category_filter)

    if search_query:
        like_term = f"%{search_query}%"
        query = query.filter(
            or_(
                UsedItem.item_name.ilike(like_term),
                UsedItem.description.ilike(like_term),
                UsedItem.category.ilike(like_term),
                UsedItem.meeting_point.ilike(like_term),
            )
        )

    items = query.order_by(UsedItem.created_at.desc()).all()
    is_admin = _is_admin(g.current_user)

    cards = []
    for item in items:
        seller = _seller_info(item, g.current_user)
        is_owner = item.profile_id == user_id
        cards.append(
            {
                "id": item.id,
                "listing_type": item.listing_type,
                "badge_text": "Free Donation" if item.listing_type == "free" else _format_price(item.price),
                "title": item.item_name,
                "category": item.category,
                "category_icon": CATEGORY_ICONS.get(item.category, "📦"),
                "condition": item.condition,
                "department": seller["department"],
                "seller_name": seller["name"],
                "image_url": item.image_url,
                "whatsapp_url": _whatsapp_link(item.phone_number, item.item_name, item.listing_type),
                "is_owner": is_owner,
                "is_saved": item.id in saved_ids,
                "can_edit": is_owner,
                "can_delete": is_owner or is_admin,
            }
        )

    return render_template(
        "used_items/used_items.html",
        cards=cards,
        counts=counts,
        categories=CATEGORIES,
        active_view=view_filter,
        active_category=category_filter,
        search_query=search_query,
    )


@used_items_pages.route("/used-items/<int:item_id>")
def item_details(item_id: int):
    item = db.session.get(UsedItem, item_id)
    if not item or item.status != "available":
        abort(404)

    user_id = g.current_user.id
    is_owner = item.profile_id == user_id
    is_admin = _is_admin(g.current_user)
    seller = _seller_info(item, g.current_user)
    is_saved = (
        SavedItem.query.filter_by(profile_id=user_id, used_item_id=item.id).first() is not None
    )

    return render_template(
        "used_items/item_details.html",
        item=item,
        category_icon=CATEGORY_ICONS.get(item.category, "📦"),
        badge_text="Free Donation" if item.listing_type == "free" else _format_price(item.price),
        seller=seller,
        whatsapp_url=_whatsapp_link(item.phone_number, item.item_name, item.listing_type),
        is_owner=is_owner,
        is_saved=is_saved,
        can_edit=is_owner,
        can_delete=is_owner or is_admin,
    )


@used_items_pages.route("/used-items/<int:item_id>/save", methods=["POST"])
def toggle_save(item_id: int):
    _check_csrf()
    item = db.session.get(UsedItem, item_id)
    if not item or item.status != "available":
        abort(404)

    if item.profile_id == g.current_user.id:
        return redirect(request.referrer or url_for("used_items_pages.used_items"))

    existing = SavedItem.query.filter_by(
        profile_id=g.current_user.id,
        used_item_id=item.id,
    ).first()

    if existing:
        db.session.delete(existing)
        flash("Removed from saved items.", "success")
    else:
        db.session.add(SavedItem(profile_id=g.current_user.id, used_item_id=item.id))
        flash("Item saved to your list.", "success")

    db.session.commit()
    return redirect(request.referrer or url_for("used_items_pages.item_details", item_id=item.id))


@used_items_pages.route("/used-items/new", methods=["GET", "POST"])
def create_item():
    account_whatsapp = _get_account_whatsapp(g.current_user)

    if request.method == "POST":
        _check_csrf()

        listing_type = request.form.get("listing_type", "free").strip().lower()
        if listing_type not in ("free", "sale"):
            listing_type = "free"

        item_name = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        condition = request.form.get("condition", "").strip()
        meeting_point = request.form.get("meeting_point", "").strip()
        description = request.form.get("description", "").strip()
        is_anonymous = request.form.get("is_anonymous") == "on"
        whatsapp_mode = request.form.get("whatsapp_mode", "account")
        temp_whatsapp = request.form.get("temp_whatsapp", "").strip()

        chosen_whatsapp = account_whatsapp if whatsapp_mode == "account" else temp_whatsapp

        price = Decimal("0.00")
        if listing_type == "sale":
            parsed = _parse_price(request.form.get("price", ""))
            if parsed is None:
                flash("Please enter a valid price in EGP for a 'For Sale' listing.", "error")
                return render_template(
                    "used_items/item_form.html",
                    mode="create",
                    item=None,
                    categories=CATEGORIES,
                    conditions=CONDITIONS,
                    account_whatsapp=account_whatsapp,
                    form_data=request.form,
                )
            price = parsed

        if not item_name or not category or not condition:
            flash("Please fill in item title, category, and condition.", "error")
            return render_template(
                "used_items/item_form.html",
                mode="create",
                item=None,
                categories=CATEGORIES,
                conditions=CONDITIONS,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        if len(_normalize_whatsapp(chosen_whatsapp)) < 10:
            flash("Please provide a valid WhatsApp number (from your account or a temporary one).", "error")
            return render_template(
                "used_items/item_form.html",
                mode="create",
                item=None,
                categories=CATEGORIES,
                conditions=CONDITIONS,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        photo_file = request.files.get("photo")
        image_url = _save_uploaded_photo(photo_file)
        if photo_file and photo_file.filename and not image_url:
            flash("Photo must be a PNG, JPG, or WEBP image.", "error")
            return render_template(
                "used_items/item_form.html",
                mode="create",
                item=None,
                categories=CATEGORIES,
                conditions=CONDITIONS,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        new_item = UsedItem(
            profile_id=g.current_user.id,
            item_name=item_name,
            condition=condition,
            category=category,
            meeting_point=meeting_point or None,
            status="available",
            phone_number=chosen_whatsapp,
            description=description or None,
            image_url=image_url,
            price=price,
            listing_type=listing_type,
            is_anonymous=is_anonymous,
        )
        db.session.add(new_item)
        db.session.commit()

        flash("Your listing has been published!", "success")
        return redirect(url_for("used_items_pages.item_details", item_id=new_item.id))

    return render_template(
        "used_items/item_form.html",
        mode="create",
        item=None,
        categories=CATEGORIES,
        conditions=CONDITIONS,
        account_whatsapp=account_whatsapp,
        form_data={},
    )


@used_items_pages.route("/used-items/<int:item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id: int):
    item = db.session.get(UsedItem, item_id)
    if not item or item.status != "available":
        abort(404)

    # Strictly publisher only (admins cannot edit another user's post)
    if item.profile_id != g.current_user.id:
        abort(403)

    account_whatsapp = _get_account_whatsapp(g.current_user)

    if request.method == "POST":
        _check_csrf()

        listing_type = request.form.get("listing_type", item.listing_type).strip().lower()
        if listing_type not in ("free", "sale"):
            listing_type = item.listing_type

        item_name = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        condition = request.form.get("condition", "").strip()
        meeting_point = request.form.get("meeting_point", "").strip()
        description = request.form.get("description", "").strip()
        is_anonymous = request.form.get("is_anonymous") == "on"
        whatsapp_mode = request.form.get("whatsapp_mode", "account")
        temp_whatsapp = request.form.get("temp_whatsapp", "").strip()

        chosen_whatsapp = account_whatsapp if whatsapp_mode == "account" else temp_whatsapp

        price = Decimal("0.00")
        if listing_type == "sale":
            parsed = _parse_price(request.form.get("price", ""))
            if parsed is None:
                flash("Please enter a valid price in EGP for a 'For Sale' listing.", "error")
                return render_template(
                    "used_items/item_form.html",
                    mode="edit",
                    item=item,
                    categories=CATEGORIES,
                    conditions=CONDITIONS,
                    account_whatsapp=account_whatsapp,
                    form_data=request.form,
                )
            price = parsed

        if not item_name or not category or not condition:
            flash("Item title, category, and condition are required.", "error")
            return render_template(
                "used_items/item_form.html",
                mode="edit",
                item=item,
                categories=CATEGORIES,
                conditions=CONDITIONS,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        if len(_normalize_whatsapp(chosen_whatsapp)) < 10:
            flash("Please provide a valid WhatsApp number.", "error")
            return render_template(
                "used_items/item_form.html",
                mode="edit",
                item=item,
                categories=CATEGORIES,
                conditions=CONDITIONS,
                account_whatsapp=account_whatsapp,
                form_data=request.form,
            )

        photo_file = request.files.get("photo")
        if photo_file and photo_file.filename:
            new_image_url = _save_uploaded_photo(photo_file)
            if not new_image_url:
                flash("Photo must be a PNG, JPG, or WEBP image.", "error")
                return render_template(
                    "used_items/item_form.html",
                    mode="edit",
                    item=item,
                    categories=CATEGORIES,
                    conditions=CONDITIONS,
                    account_whatsapp=account_whatsapp,
                    form_data=request.form,
                )
            _delete_local_photo(item.image_url)
            item.image_url = new_image_url

        item.listing_type = listing_type
        item.price = price
        item.item_name = item_name
        item.category = category
        item.condition = condition
        item.meeting_point = meeting_point or None
        item.description = description or None
        item.phone_number = chosen_whatsapp
        item.is_anonymous = is_anonymous

        db.session.commit()
        flash("Listing updated successfully.", "success")
        return redirect(url_for("used_items_pages.item_details", item_id=item.id))

    return render_template(
        "used_items/item_form.html",
        mode="edit",
        item=item,
        categories=CATEGORIES,
        conditions=CONDITIONS,
        account_whatsapp=account_whatsapp,
        form_data={},
    )


@used_items_pages.route("/used-items/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id: int):
    _check_csrf()
    item = db.session.get(UsedItem, item_id)
    if not item:
        abort(404)

    # Publisher OR Admin can delete
    if item.profile_id != g.current_user.id and not _is_admin(g.current_user):
        abort(403)

    SavedItem.query.filter_by(used_item_id=item.id).delete()
    _delete_local_photo(item.image_url)
    db.session.delete(item)
    db.session.commit()

    flash("Listing deleted permanently.", "success")
    return redirect(url_for("used_items_pages.used_items"))


@used_items_pages.route("/used-items/<int:item_id>/sold", methods=["POST"])
def mark_sold(item_id: int):
    _check_csrf()
    item = db.session.get(UsedItem, item_id)
    if not item:
        abort(404)

    # Publisher marks the item as sold/claimed -> automatically deleted from database
    if item.profile_id != g.current_user.id:
        abort(403)

    SavedItem.query.filter_by(used_item_id=item.id).delete()
    _delete_local_photo(item.image_url)
    db.session.delete(item)
    db.session.commit()

    flash("Listing marked as completed and removed from the marketplace.", "success")
    return redirect(url_for("used_items_pages.used_items"))