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


@events_pages.route("/events")
def events():
    all_events = Event.query.order_by(Event.date.asc(), Event.start_time.asc()).all()
    reserved_counts = dict(
        db.session.query(
            EventReservation.event_id,
            func.count(EventReservation.id),
        )
        .filter(EventReservation.status != "cancelled")
        .group_by(EventReservation.event_id)
        .all()
    )
    seats_left_by_event_id = {
        event.id: max(event.capacity - reserved_counts.get(event.id, 0), 0)
        for event in all_events
        if event.capacity is not None
    }

    user_reservations = EventReservation.query.filter(
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).all()
    registered_event_ids = {r.event_id for r in user_reservations}

    starred_rows = StarredEvent.query.filter_by(profile_id=g.current_user.id).all()
    starred_event_ids = {s.event_id for s in starred_rows}

    return render_template(
        "events/events.html",
        events=all_events,
        registered_event_ids=registered_event_ids,
        starred_event_ids=starred_event_ids,
        seats_left_by_event_id=seats_left_by_event_id,
    )


@events_pages.route("/events/<int:event_id>", methods=["GET", "POST"])
def event_details(event_id):
    event = Event.query.get_or_404(event_id)

    active_reservation = EventReservation.query.filter(
        EventReservation.event_id == event.id,
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).first()

    reserved_count = EventReservation.query.filter(
        EventReservation.event_id == event.id,
        EventReservation.status != "cancelled",
    ).count()

    seats_left = (event.capacity - reserved_count) if event.capacity is not None else None

    if request.method == "POST":
        if active_reservation:
            return redirect(url_for("events_pages.event_registered", event_id=event.id))

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
        reserved_count=reserved_count,
        seats_left=seats_left,
    )


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
def cancel_registration(event_id):
    reservation = EventReservation.query.filter(
        EventReservation.event_id == event_id,
        EventReservation.profile_id == g.current_user.id,
        EventReservation.status != "cancelled",
    ).first_or_404()

    reservation.status = "cancelled"
    db.session.commit()
    flash("Your event registration has been cancelled.", "info")
    return redirect(url_for("events_pages.event_details", event_id=event_id))


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