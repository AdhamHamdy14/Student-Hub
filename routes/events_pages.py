from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from models import Event, EventReservation, StarredEvent, db
from services.csrf import csrf_protect
from services.roles import ADMIN_ROLE, EVENT_MANAGER_ROLE

events_pages = Blueprint("events_pages", __name__)


@events_pages.before_request
def require_login():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))
    if g.current_user.role in {ADMIN_ROLE, EVENT_MANAGER_ROLE}:
        return redirect(url_for("event_management_pages.index"))


def _is_event_ended(event: Event, now: datetime) -> bool:
    if not event.date or not event.end_time:
        return False
    return datetime.combine(event.date, event.end_time) < now


def _reserved_counts_map() -> dict[int, int]:
    rows = (
        db.session.query(EventReservation.event_id, func.count(EventReservation.id))
        .filter(EventReservation.status != "cancelled")
        .group_by(EventReservation.event_id)
        .all()
    )
    return {event_id: count for event_id, count in rows}


@events_pages.route("/events")
def events():
    view_filter = request.args.get("view", "all").strip().lower()
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()
    now = datetime.now()
    all_events = Event.query.order_by(Event.date.asc(), Event.start_time.asc()).all()

    user_reservations = EventReservation.query.filter(
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).all()
    registered_event_ids = {r.event_id for r in user_reservations}

    starred_rows = StarredEvent.query.filter_by(profile_id=g.current_user.id).all()
    starred_event_ids = {s.event_id for s in starred_rows}

    reserved_map = _reserved_counts_map()

    upcoming_unregistered = []
    upcoming_registered = []
    ended_events = []

    for ev in all_events:
        is_ended = _is_event_ended(ev, now)
        is_registered = ev.id in registered_event_ids
        is_starred = ev.id in starred_event_ids
        reserved_count = reserved_map.get(ev.id, 0)
        seats_left = max(0, ev.capacity - reserved_count) if ev.capacity is not None else None

        is_full = seats_left is not None and seats_left <= 0
        is_open = (not is_ended) and ev.registration_status == "open" and (not is_full)
        is_low_seats = (
            (not is_ended)
            and ev.registration_status == "open"
            and (seats_left is not None and 0 < seats_left <= 20)
        )

        card = {
            "event": ev,
            "is_ended": is_ended,
            "is_registered": is_registered,
            "is_starred": is_starred,
            "reserved_count": reserved_count,
            "seats_left": seats_left,
            "is_full": is_full,
            "is_open": is_open,
            "is_low_seats": is_low_seats,
        }

        if is_ended:
            ended_events.append(card)
        elif is_registered:
            upcoming_registered.append(card)
        else:
            upcoming_unregistered.append(card)

    ended_events.reverse()

    # Order: 1) Upcoming not registered -> 2) Upcoming registered -> 3) Ended events
    ordered_cards = upcoming_unregistered + upcoming_registered + ended_events
    categories = sorted({ev.category for ev in all_events if ev.category})

    counts = {
        "all": len(ordered_cards),
        "registered": len(upcoming_registered) + sum(1 for c in ended_events if c["is_registered"]),
        "starred": sum(1 for c in ordered_cards if c["is_starred"]),
        "open": sum(1 for c in ordered_cards if c["is_open"]),
        "ended": len(ended_events),
    }

    filtered_cards = ordered_cards

    if view_filter == "registered":
        filtered_cards = [card for card in filtered_cards if card["is_registered"]]
    elif view_filter == "starred":
        filtered_cards = [card for card in filtered_cards if card["is_starred"]]
    elif view_filter == "open":
        filtered_cards = [card for card in filtered_cards if card["is_open"]]
    elif view_filter == "ended":
        filtered_cards = [card for card in filtered_cards if card["is_ended"]]
    else:
        view_filter = "all"

    if category_filter:
        filtered_cards = [
            card
            for card in filtered_cards
            if (card["event"].category or "").lower() == category_filter.lower()
        ]

    if search_query:
        needle = search_query.lower()
        filtered_cards = [
            card
            for card in filtered_cards
            if needle
            in (
                f"{card['event'].event_name} "
                f"{card['event'].organizer or ''} "
                f"{card['event'].location or ''} "
                f"{card['event'].category or ''}"
            ).lower()
        ]

    return render_template(
        "events/events.html",
        cards=filtered_cards,
        categories=categories,
        counts=counts,
        active_view=view_filter,
        active_category=category_filter,
        search_query=search_query,
    )


@events_pages.route("/events/<int:event_id>", methods=["GET", "POST"])
def event_details(event_id):
    event = Event.query.get_or_404(event_id)
    now = datetime.now()
    is_ended = _is_event_ended(event, now)

    active_reservation = EventReservation.query.filter(
        EventReservation.event_id == event.id,
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).first()

    reserved_count = EventReservation.query.filter(
        EventReservation.event_id == event.id,
        EventReservation.status != "cancelled",
    ).count()

    seats_left = max(0, event.capacity - reserved_count) if event.capacity is not None else None
    is_low_seats = (
        (not is_ended)
        and event.registration_status == "open"
        and (seats_left is not None and 0 < seats_left <= 20)
    )

    if request.method == "POST":
        return _handle_register_post(event, active_reservation, is_ended, seats_left)

    is_starred = (
        StarredEvent.query.filter_by(
            profile_id=g.current_user.id,
            event_id=event.id,
        ).first()
        is not None
    )

    return render_template(
        "events/event_details.html",
        event=event,
        reservation=active_reservation,
        is_registered=bool(active_reservation),
        is_starred=is_starred,
        is_ended=is_ended,
        is_low_seats=is_low_seats,
        reserved_count=reserved_count,
        seats_left=seats_left,
    )


@csrf_protect
def _handle_register_post(event, active_reservation, is_ended, seats_left):
    if active_reservation:
        return redirect(url_for("events_pages.event_registered", event_id=event.id))

    if is_ended:
        flash("This event has already ended.", "error")
        return redirect(url_for("events_pages.event_details", event_id=event.id))

    if event.registration_status != "open":
        flash("Registration for this event is closed.", "error")
        return redirect(url_for("events_pages.event_details", event_id=event.id))

    if seats_left is not None and seats_left <= 0:
        flash("This event has reached full capacity.", "error")
        return redirect(url_for("events_pages.event_details", event_id=event.id))

    reminder_enabled = bool(request.form.get("reminder"))

    try:
        reservation = EventReservation(
            profile_id=g.current_user.id,
            event_id=event.id,
            status="registered",
            reminder=reminder_enabled,
        )
        db.session.add(reservation)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

    return redirect(url_for("events_pages.event_registered", event_id=event.id))


@events_pages.route("/events/<int:event_id>/registered")
def event_registered(event_id):
    event = Event.query.get_or_404(event_id)

    reservation = EventReservation.query.filter(
        EventReservation.event_id == event.id,
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).first()

    if not reservation:
        return redirect(url_for("events_pages.event_details", event_id=event.id))

    return render_template(
        "events/event_registered.html",
        event=event,
        reservation=reservation,
    )


@events_pages.route("/events/<int:event_id>/cancel", methods=["POST"])
@csrf_protect
def cancel_registration(event_id):
    reservation = EventReservation.query.filter(
        EventReservation.event_id == event_id,
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).first_or_404()

    reservation.status = "cancelled"
    db.session.commit()
    flash("Your event registration has been cancelled.", "info")
    return redirect(request.referrer or url_for("events_pages.event_details", event_id=event_id))


@events_pages.route("/events/<int:event_id>/star", methods=["POST"])
@csrf_protect
def toggle_star_event(event_id):
    Event.query.get_or_404(event_id)
    existing = StarredEvent.query.filter_by(
        profile_id=g.current_user.id,
        event_id=event_id,
    ).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(StarredEvent(profile_id=g.current_user.id, event_id=event_id))

    db.session.commit()
    return redirect(request.referrer or url_for("events_pages.events"))