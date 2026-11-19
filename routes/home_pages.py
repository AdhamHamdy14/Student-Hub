from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from models import (
    Event,
    EventReservation,
    Lab,
    LabReservation,
    LabSlot,
    LostAndFound,
    Notification,
    UsedItem,
    db,
)

home_pages = Blueprint("home_pages", __name__)


def _relative_time(dt):
    if not dt:
        return ""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    diff = now - dt
    seconds = max(int(diff.total_seconds()), 0)
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


@home_pages.before_request
def require_login():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))


@home_pages.route("/home")
def home():
    user_id = g.current_user.id
    today = datetime.now().date()

    # 1. Active Upcoming Lab Reservations
    lab_rows = (
        db.session.query(LabReservation, LabSlot, Lab)
        .join(LabSlot, LabReservation.slot_id == LabSlot.id)
        .join(Lab, LabSlot.lab_id == Lab.id)
        .filter(
            LabReservation.profile_id == user_id,
            LabReservation.status != "cancelled",
            LabSlot.date >= today,
        )
        .order_by(LabSlot.date.asc(), LabSlot.start_time.asc())
        .all()
    )

    # 2. Active Upcoming Registered Events
    event_rows = (
        db.session.query(EventReservation, Event)
        .join(Event, EventReservation.event_id == Event.id)
        .filter(
            EventReservation.profile_id == user_id,
            EventReservation.status != "cancelled",
            Event.date >= today,
        )
        .order_by(Event.date.asc(), Event.start_time.asc())
        .all()
    )

    # 3. Active Listings & Lost/Found Reports
    used_items_count = UsedItem.query.filter_by(
        profile_id=user_id, status="available"
    ).count()
    lost_found_count = LostAndFound.query.filter_by(
        profile_id=user_id, status="open"
    ).count()

    # 4. Merge Labs + Events into unified chronological schedule
    schedule_items = []
    for res, slot, lab in lab_rows:
        schedule_items.append(
            {
                "kind": "lab",
                "sort_key": datetime.combine(slot.date, slot.start_time),
                "month": slot.date.strftime("%b").upper(),
                "day": slot.date.strftime("%d"),
                "weekday": slot.date.strftime("%a").upper(),
                "title": f"{lab.name} Reservation",
                "time_str": f"{slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                "location": f"{lab.name} ({lab.room})" if lab.room else lab.name,
                "status": res.status.capitalize(),
                "status_class": "st-green",
                "url": url_for("labs_pages.labs"),
            }
        )

    for res, ev in event_rows:
        schedule_items.append(
            {
                "kind": "event",
                "sort_key": datetime.combine(ev.date, ev.start_time),
                "month": ev.date.strftime("%b").upper(),
                "day": ev.date.strftime("%d"),
                "weekday": ev.date.strftime("%a").upper(),
                "title": ev.event_name,
                "time_str": f"{ev.start_time.strftime('%H:%M')}–{ev.end_time.strftime('%H:%M')}",
                "location": ev.location,
                "status": "Registered",
                "status_class": "st-blue",
                "url": url_for("events_pages.event_details", event_id=ev.id),
            }
        )

    schedule_items.sort(key=lambda item: item["sort_key"])

    # 5. Notifications
    notifications = (
        Notification.query.filter_by(profile_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(10)
        .all()
    )
    unread_count = sum(1 for n in notifications if not n.is_read)

    accent_classes = ["notif-blue", "notif-green", "notif-amber", "notif-purple"]
    notif_items = []
    for idx, n in enumerate(notifications):
        notif_items.append(
            {
                "id": n.id,
                "title": n.title,
                "description": n.description,
                "is_read": n.is_read,
                "time_ago": _relative_time(n.created_at),
                "accent_class": "is-read" if n.is_read else accent_classes[idx % len(accent_classes)],
            }
        )

    next_lab = lab_rows[0] if lab_rows else None
    next_event = event_rows[0] if event_rows else None

    return render_template(
        "home/home.html",
        active_labs_count=len(lab_rows),
        next_lab=next_lab,
        upcoming_events_count=len(event_rows),
        next_event=next_event,
        used_items_count=used_items_count,
        lost_found_count=lost_found_count,
        total_listings_count=used_items_count + lost_found_count,
        schedule_items=schedule_items[:5],
        notifications=notif_items,
        unread_count=unread_count,
    )


@home_pages.route("/home/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    Notification.query.filter_by(
        profile_id=g.current_user.id, is_read=False
    ).update({"is_read": True})
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": "ok"})
    return redirect(url_for("home"))