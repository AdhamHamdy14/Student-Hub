from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func

from models import (
    Event,
    EventReservation,
    Lab,
    LabReservation,
    LabSlot,
    LostAndFound,
    Notification,
    Profile,
    UsedItem,
    db,
)
from services.roles import (
    ADMIN_ROLE,
    EVENT_MANAGER_ROLE,
    STUDENT_ROLE,
    ta_department_for_role,
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
    user = g.current_user
    user_id = user.id
    today = datetime.now().date()

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

    dashboard = {
        "dashboard_role": "student",
        "role_tag": "Student Portal",
        "subtitle": "Book engineering labs, register for workshops, find campus essentials, and keep up with your FOE-AU life.",
        "primary_action": {
            "label": "Book a Lab",
            "url": url_for("labs_pages.labs"),
        },
        "secondary_action": {
            "label": "Browse Events",
            "url": url_for("events_pages.events"),
        },
        "workspace_title": "Your Upcoming Schedule",
        "workspace_subtitle": "Confirmed lab reservations and registered campus events",
        "workspace_action": {
            "label": "Browse events",
            "url": url_for("events_pages.events"),
        },
        "system_activity": [],
    }

    department = ta_department_for_role(user.role)
    if department:
        dashboard.update(
            dashboard_role="ta",
            role_tag=f"{department} Lab Supervisor",
            subtitle="Oversee your department's lab sessions, monitor student bookings, and keep campus reports up to date.",
            primary_action={
                "label": "Manage labs",
                "url": url_for("labs_pages.labs"),
            },
            secondary_action={
                "label": "Report an item",
                "url": url_for("lost_found_pages.create_item"),
            },
            workspace_title="Upcoming Department Lab Sessions",
            workspace_subtitle=f"Active sessions for {department} and their current reservations",
            workspace_action={
                "label": "Manage labs",
                "url": url_for("labs_pages.labs"),
            },
        )
        active_slots_count = (
            db.session.query(func.count(LabSlot.id))
            .join(Lab, LabSlot.lab_id == Lab.id)
            .filter(
                Lab.department == department,
                Lab.status == "available",
                LabSlot.is_active.is_(True),
                LabSlot.date >= today,
            )
            .scalar()
        )
        slots = (
            db.session.query(LabSlot, Lab)
            .join(Lab, LabSlot.lab_id == Lab.id)
            .filter(
                Lab.department == department,
                Lab.status == "available",
                LabSlot.is_active.is_(True),
                LabSlot.date >= today,
            )
            .order_by(LabSlot.date.asc(), LabSlot.start_time.asc())
            .limit(5)
            .all()
        )
        slot_ids = [slot.id for slot, _ in slots]
        reservations_by_slot = {}
        if slot_ids:
            reservation_counts = (
                db.session.query(
                    LabReservation.slot_id,
                    func.count(LabReservation.id),
                )
                .filter(
                    LabReservation.slot_id.in_(slot_ids),
                    LabReservation.status != "cancelled",
                )
                .group_by(LabReservation.slot_id)
                .all()
            )
            reservations_by_slot = dict(reservation_counts)

        today_bookings = (
            db.session.query(func.count(LabReservation.id))
            .join(LabSlot, LabReservation.slot_id == LabSlot.id)
            .join(Lab, LabSlot.lab_id == Lab.id)
            .filter(
                Lab.department == department,
                LabSlot.date == today,
                LabReservation.status != "cancelled",
            )
            .scalar()
        )
        open_reports = LostAndFound.query.filter_by(
            profile_id=user_id, status="open"
        ).count()
        dashboard["kpis"] = [
            {
                "value": active_slots_count or 0,
                "label": "Active Upcoming Lab Slots",
                "detail": f"Scheduled in {department}",
                "icon": "flask",
                "tone": "blue",
            },
            {
                "value": today_bookings or 0,
                "label": "Today's Lab Bookings",
                "detail": "Confirmed reservations in your department",
                "icon": "cal",
                "tone": "green",
            },
            {
                "value": open_reports,
                "label": "My Open Lost & Found Reports",
                "detail": "Reports you have posted",
                "icon": "doc",
                "tone": "purple",
            },
        ]
        dashboard["lab_items"] = [
            {
                "title": lab.name,
                "meta": f"{lab.department} · {lab.room}",
                "date": slot.date.strftime("%a, %d %b"),
                "time": f"{slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                "reserved": reservations_by_slot.get(slot.id, 0),
                "capacity": slot.capacity,
                "url": url_for("labs_pages.edit_lab", lab_id=lab.id),
            }
            for slot, lab in slots
        ]
    elif user.role == EVENT_MANAGER_ROLE:
        dashboard.update(
            dashboard_role="event_manager",
            role_tag="Event Organizer",
            subtitle="Create campus events, track registrations, and keep an eye on event capacity from one place.",
            primary_action={
                "label": "Create an event",
                "url": url_for("event_management_pages.new_event"),
            },
            secondary_action={
                "label": "Manage events",
                "url": url_for("event_management_pages.index"),
            },
            workspace_title="Upcoming Managed Events",
            workspace_subtitle="Registration progress for upcoming events",
            workspace_action={
                "label": "Manage events",
                "url": url_for("event_management_pages.index"),
            },
        )
        upcoming_events = (
            Event.query.filter(Event.date >= today)
            .order_by(Event.date.asc(), Event.start_time.asc())
            .all()
        )
        event_ids = [event.id for event in upcoming_events]
        registrations_by_event = {}
        if event_ids:
            registration_counts = (
                db.session.query(
                    EventReservation.event_id,
                    func.count(EventReservation.id),
                )
                .filter(
                    EventReservation.event_id.in_(event_ids),
                    EventReservation.status != "cancelled",
                )
                .group_by(EventReservation.event_id)
                .all()
            )
            registrations_by_event = dict(registration_counts)

        total_registrations = sum(registrations_by_event.values())
        total_seats_left = sum(
            max(0, event.capacity - registrations_by_event.get(event.id, 0))
            for event in upcoming_events
            if event.capacity is not None
        )
        capped_events = sum(1 for event in upcoming_events if event.capacity is not None)
        dashboard["kpis"] = [
            {
                "value": sum(1 for event in upcoming_events if event.registration_status == "open"),
                "label": "Open Upcoming Events",
                "detail": f"{len(upcoming_events)} upcoming event{'s' if len(upcoming_events) != 1 else ''} in total",
                "icon": "cal",
                "tone": "blue",
            },
            {
                "value": total_registrations,
                "label": "Student Registrations",
                "detail": "Across all upcoming events",
                "icon": "doc",
                "tone": "green",
            },
            {
                "value": total_seats_left if capped_events else "—",
                "label": "Seats Remaining",
                "detail": "Across events with a capacity limit" if capped_events else "No event capacity limits are set",
                "icon": "flask",
                "tone": "purple",
            },
        ]
        dashboard["event_items"] = [
            {
                "title": event.event_name,
                "meta": f"{event.location} · {event.date.strftime('%a, %d %b')} · {event.start_time.strftime('%H:%M')}",
                "registered": registrations_by_event.get(event.id, 0),
                "capacity": event.capacity,
                "url": url_for("event_management_pages.edit_event", event_id=event.id),
            }
            for event in upcoming_events[:5]
        ]
    elif user.role == ADMIN_ROLE:
        dashboard.update(
            dashboard_role="admin",
            role_tag="System Administration",
            subtitle="Review platform activity, keep track of campus usage, and manage accounts and roles.",
            primary_action={
                "label": "Manage users & roles",
                "url": url_for("admin_roles_pages.index"),
            },
            secondary_action={
                "label": "Manage events",
                "url": url_for("event_management_pages.index"),
            },
            workspace_title="Recent Campus Activity",
            workspace_subtitle="Latest active listings and open lost & found reports",
            workspace_action={
                "label": "Review listings",
                "url": url_for("used_items"),
            },
        )
        total_users = Profile.query.count()
        ta_users = Profile.query.filter(Profile.role.like("ta:%")).count()
        event_managers = Profile.query.filter_by(role=EVENT_MANAGER_ROLE).count()
        students = Profile.query.filter_by(role=STUDENT_ROLE).count()
        today_lab_bookings = (
            db.session.query(func.count(LabReservation.id))
            .join(LabSlot, LabReservation.slot_id == LabSlot.id)
            .filter(
                LabSlot.date == today,
                LabReservation.status != "cancelled",
            )
            .scalar()
        )
        today_event_registrations = (
            db.session.query(func.count(EventReservation.id))
            .join(Event, EventReservation.event_id == Event.id)
            .filter(
                Event.date == today,
                EventReservation.status != "cancelled",
            )
            .scalar()
        )
        available_items = UsedItem.query.filter_by(status="available").count()
        open_lost_found = LostAndFound.query.filter_by(status="open").count()
        dashboard["kpis"] = [
            {
                "value": total_users,
                "label": "Registered Users",
                "detail": (
                    f"{students} student{'s' if students != 1 else ''} · "
                    f"{ta_users} TAs · "
                    f"{event_managers} event manager{'s' if event_managers != 1 else ''}"
                ),
                "icon": "doc",
                "tone": "blue",
            },
            {
                "value": (today_lab_bookings or 0) + (today_event_registrations or 0),
                "label": "Today's Reservations",
                "detail": (
                    f"{today_lab_bookings or 0} lab booking{'s' if today_lab_bookings != 1 else ''} · "
                    f"{today_event_registrations or 0} event registration{'s' if today_event_registrations != 1 else ''}"
                ),
                "icon": "cal",
                "tone": "green",
            },
            {
                "value": available_items + open_lost_found,
                "label": "Active Listings & Reports",
                "detail": f"{available_items} used items · {open_lost_found} lost & found",
                "icon": "flask",
                "tone": "purple",
            },
        ]

        activity = []
        for item in UsedItem.query.filter_by(status="available").order_by(
            UsedItem.created_at.desc()
        ).limit(5):
            activity.append(
                {
                    "category": "Used item",
                    "title": item.item_name,
                    "meta": f"Posted by {item.seller.name} · {item.created_at.strftime('%d %b')}",
                    "timestamp": item.created_at,
                    "url": url_for("used_items"),
                }
            )
        for report in LostAndFound.query.filter_by(status="open").order_by(
            LostAndFound.created_at.desc()
        ).limit(5):
            activity.append(
                {
                    "category": "Lost & found",
                    "title": report.item_name,
                    "meta": f"Reported by {report.reporter.name} · {report.created_at.strftime('%d %b')}",
                    "timestamp": report.created_at,
                    "url": url_for("lost_found"),
                }
            )
        dashboard["system_activity"] = sorted(
            activity,
            key=lambda item: item["timestamp"],
            reverse=True,
        )[:5]
    else:
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
        used_items_count = UsedItem.query.filter_by(
            profile_id=user_id, status="available"
        ).count()
        lost_found_count = LostAndFound.query.filter_by(
            profile_id=user_id, status="open"
        ).count()

        schedule_items = []
        for reservation, slot, lab in lab_rows:
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
                    "status": reservation.status.capitalize(),
                    "status_class": "st-green",
                    "url": url_for("labs_pages.labs"),
                }
            )
        for reservation, event in event_rows:
            schedule_items.append(
                {
                    "kind": "event",
                    "sort_key": datetime.combine(event.date, event.start_time),
                    "month": event.date.strftime("%b").upper(),
                    "day": event.date.strftime("%d"),
                    "weekday": event.date.strftime("%a").upper(),
                    "title": event.event_name,
                    "time_str": f"{event.start_time.strftime('%H:%M')}–{event.end_time.strftime('%H:%M')}",
                    "location": event.location,
                    "status": "Registered",
                    "status_class": "st-blue",
                    "url": url_for("events_pages.event_details", event_id=event.id),
                }
            )
        schedule_items.sort(key=lambda item: item["sort_key"])
        next_lab = lab_rows[0] if lab_rows else None
        next_event = event_rows[0] if event_rows else None
        dashboard["kpis"] = [
            {
                "value": len(lab_rows),
                "label": "Active Lab Reservations",
                "detail": (
                    f"Next: {next_lab[2].name} · {next_lab[1].date.strftime('%a, %d %b')}"
                    if next_lab
                    else "No upcoming lab slots booked"
                ),
                "icon": "flask",
                "tone": "blue",
            },
            {
                "value": len(event_rows),
                "label": "Upcoming Events",
                "detail": f"Next: {next_event[1].event_name}" if next_event else "No upcoming registered events",
                "icon": "cal",
                "tone": "green",
            },
            {
                "value": used_items_count + lost_found_count,
                "label": "Active Listings & Reports",
                "detail": f"{used_items_count} used items · {lost_found_count} lost & found",
                "icon": "doc",
                "tone": "purple",
            },
        ]
        dashboard["schedule_items"] = schedule_items[:5]

    return render_template(
        "home/home.html",
        **dashboard,
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