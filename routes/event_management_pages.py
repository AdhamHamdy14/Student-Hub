from datetime import date, time

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from models import Event, db
from services.csrf import csrf_protect
from services.roles import ADMIN_ROLE, EVENT_MANAGER_ROLE

event_management_pages = Blueprint(
    "event_management_pages",
    __name__,
    url_prefix="/events/manage",
)


@event_management_pages.before_request
def require_event_manager():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))
    if g.current_user.role not in {ADMIN_ROLE, EVENT_MANAGER_ROLE}:
        abort(403)


def _event_form_data():
    event_name = request.form.get("event_name", "").strip()
    organizer = request.form.get("organizer", "").strip()
    location = request.form.get("location", "").strip()
    category = request.form.get("category", "").strip()
    agenda = request.form.get("agenda", "").strip() or None
    status = request.form.get("registration_status", "open")

    try:
        event_date = date.fromisoformat(request.form.get("date", ""))
        start_time = time.fromisoformat(request.form.get("start_time", ""))
        end_time = time.fromisoformat(request.form.get("end_time", ""))
    except ValueError:
        flash("Enter a valid event date and time.", "error")
        return None

    capacity_text = request.form.get("capacity", "").strip()
    if capacity_text:
        try:
            capacity = int(capacity_text)
        except ValueError:
            capacity = 0
        if capacity <= 0:
            flash("Capacity must be a positive number or left blank.", "error")
            return None
    else:
        capacity = None

    if not event_name or not organizer or not location or not category:
        flash("Event name, organizer, location, and category are required.", "error")
        return None
    if end_time <= start_time:
        flash("Event end time must be after its start time.", "error")
        return None
    if status not in {"open", "closed"}:
        flash("Choose a valid registration status.", "error")
        return None

    return {
        "event_name": event_name,
        "organizer": organizer,
        "location": location,
        "category": category,
        "agenda": agenda,
        "date": event_date,
        "start_time": start_time,
        "end_time": end_time,
        "capacity": capacity,
        "registration_status": status,
    }


@event_management_pages.get("/")
def index():
    events = Event.query.order_by(Event.date.asc(), Event.start_time.asc()).all()
    categories = sorted({event.category for event in events})
    return render_template(
        "events/manage.html",
        events=events,
        categories=categories,
    )


@event_management_pages.get("/new")
def new_event():
    return render_template("events/edit.html", event=None)


@event_management_pages.get("/<int:event_id>/edit")
def edit_event(event_id):
    event = db.get_or_404(Event, event_id)
    return render_template("events/edit.html", event=event)


@event_management_pages.get("/<int:event_id>/saved")
def event_saved(event_id):
    event = db.get_or_404(Event, event_id)
    return render_template("events/saved.html", event=event)


@event_management_pages.post("/")
@csrf_protect
def create_event():
    event_data = _event_form_data()
    if event_data is None:
        return render_template("events/edit.html", event=None), 400

    event = Event(**event_data)
    db.session.add(event)
    db.session.commit()
    flash("Event created.", "success")
    return redirect(url_for("event_management_pages.event_saved", event_id=event.id))


@event_management_pages.post("/<int:event_id>")
@csrf_protect
def update_event(event_id):
    event = db.get_or_404(Event, event_id)
    event_data = _event_form_data()
    if event_data is None:
        return render_template("events/edit.html", event=event), 400

    for field, value in event_data.items():
        setattr(event, field, value)
    db.session.commit()
    flash("Event updated.", "success")
    return redirect(url_for("event_management_pages.event_saved", event_id=event.id))
