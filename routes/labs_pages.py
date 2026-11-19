from datetime import date, time

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from models import Lab, LabReservation, LabSlot, db
from services.csrf import csrf_protect
from services.roles import (
    ADMIN_ROLE,
    TA_DEPARTMENTS,
    can_manage_lab,
    ta_department_for_role,
)

labs_pages = Blueprint("labs_pages", __name__)
LAB_STATUSES = frozenset({"available", "maintenance", "closed"})


@labs_pages.before_request
def require_login():
    if not getattr(g, "current_user", None):
        return redirect(url_for("auth_pages.login"))


def _require_lab_manager(lab=None):
    role = g.current_user.role
    if role != ADMIN_ROLE and ta_department_for_role(role) is None:
        abort(403)
    if lab is not None and not can_manage_lab(role, lab.department):
        abort(403)


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_slot_form(lab):
    try:
        slot_date = date.fromisoformat(request.form.get("date", ""))
        start_time = time.fromisoformat(request.form.get("start_time", ""))
        end_time = time.fromisoformat(request.form.get("end_time", ""))
    except ValueError:
        flash("Enter a valid date and time for the lab slot.", "error")
        return None

    capacity = _positive_int(request.form.get("capacity"))
    if capacity is None or capacity > lab.capacity:
        flash("Slot capacity must be positive and no greater than the lab capacity.", "error")
        return None
    if end_time <= start_time:
        flash("The slot end time must be after its start time.", "error")
        return None

    availability = request.form.get("availability", "available")
    if availability not in {"available", "unavailable"}:
        flash("Choose a valid slot availability.", "error")
        return None

    return {
        "date": slot_date,
        "start_time": start_time,
        "end_time": end_time,
        "capacity": capacity,
        "is_active": availability == "available",
    }


def _active_reservation_count(slot):
    if slot is None:
        return 0
    return LabReservation.query.filter(
        LabReservation.slot_id == slot.id,
        LabReservation.status != "cancelled",
    ).count()


@labs_pages.get("/labs")
def labs():
    role = g.current_user.role
    labs_list = Lab.query.order_by(Lab.department.asc(), Lab.name.asc()).all()
    manager_department = ta_department_for_role(role)
    if role == ADMIN_ROLE or manager_department is not None:
        return render_template(
            "labs/manage.html",
            labs=labs_list,
            manager_department=manager_department,
        )

    return render_template(
        "labs.html",
        labs=labs_list,
        departments=TA_DEPARTMENTS,
        manager_department=manager_department,
        can_create_lab=False,
    )


def _render_lab_editor(lab=None, status_code=200):
    slots = []
    selected_slot = None
    selected_slot_reservations = 0
    if lab is not None:
        slots = (
            LabSlot.query.filter_by(lab_id=lab.id)
            .order_by(LabSlot.date.asc(), LabSlot.start_time.asc())
            .all()
        )
        raw_slot_id = request.args.get("slot_id")
        if raw_slot_id is not None:
            slot_id = _positive_int(raw_slot_id)
            if slot_id is None:
                abort(404)
            selected_slot = LabSlot.query.filter_by(
                id=slot_id,
                lab_id=lab.id,
            ).first_or_404()
            selected_slot_reservations = _active_reservation_count(selected_slot)

    response = render_template(
        "labs/edit.html",
        lab=lab,
        slots=slots,
        selected_slot=selected_slot,
        selected_slot_reservations=selected_slot_reservations,
        departments=TA_DEPARTMENTS,
        manager_department=ta_department_for_role(g.current_user.role),
    )
    return response if status_code == 200 else (response, status_code)


@labs_pages.get("/labs/new")
def new_lab():
    _require_lab_manager()
    return _render_lab_editor()


@labs_pages.get("/labs/<int:lab_id>/edit")
def edit_lab(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)
    return _render_lab_editor(lab)


@labs_pages.get("/labs/<int:lab_id>/saved")
def lab_saved(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)
    slot = None
    slot_id = request.args.get("slot_id", type=int)
    if slot_id is not None:
        slot = LabSlot.query.filter_by(id=slot_id, lab_id=lab.id).first_or_404()

    return render_template(
        "labs/saved.html",
        lab=lab,
        slot=slot,
        slot_reservations=_active_reservation_count(slot),
    )


def _parse_lab_form():
    role = g.current_user.role
    name = request.form.get("name", "").strip()
    room = request.form.get("room", "").strip()
    capacity = _positive_int(request.form.get("capacity"))
    department = (
        request.form.get("department", "").strip().upper()
        if role == ADMIN_ROLE
        else ta_department_for_role(role)
    )
    status = request.form.get("status", "available")

    if not name or not room or capacity is None:
        flash("Enter a lab name, room, and positive capacity.", "error")
        return None
    if department not in TA_DEPARTMENTS:
        flash("Choose a valid department for this lab.", "error")
        return None
    if status not in LAB_STATUSES:
        flash("Choose a valid lab status.", "error")
        return None

    return {
        "name": name,
        "room": room,
        "capacity": capacity,
        "department": department,
        "status": status,
    }


@labs_pages.post("/labs")
@csrf_protect
def create_lab():
    _require_lab_manager()
    lab_data = _parse_lab_form()
    if lab_data is None:
        return _render_lab_editor(status_code=400)

    lab = Lab(**lab_data)
    db.session.add(lab)
    db.session.commit()
    flash("Lab created.", "success")
    return redirect(url_for("labs_pages.lab_saved", lab_id=lab.id))


@labs_pages.post("/labs/<int:lab_id>/update")
@csrf_protect
def update_lab(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)
    lab_data = _parse_lab_form()
    if lab_data is None:
        return _render_lab_editor(lab, status_code=400)

    for field, value in lab_data.items():
        setattr(lab, field, value)
    db.session.commit()
    flash("Lab updated.", "success")
    return redirect(url_for("labs_pages.lab_saved", lab_id=lab.id))


@labs_pages.post("/labs/<int:lab_id>/delete")
@csrf_protect
def delete_lab(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)

    has_reservations = (
        LabReservation.query.join(LabSlot)
        .filter(LabSlot.lab_id == lab.id)
        .first()
        is not None
    )
    if has_reservations:
        flash("A lab with reservations cannot be deleted. Close it instead.", "error")
        return redirect(url_for("labs_pages.labs"))

    LabSlot.query.filter_by(lab_id=lab.id).delete(synchronize_session=False)
    db.session.delete(lab)
    db.session.commit()
    flash("Lab deleted.", "success")
    return redirect(url_for("labs_pages.labs"))


@labs_pages.post("/labs/<int:lab_id>/slots")
@csrf_protect
def create_slot(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)
    slot_data = _parse_slot_form(lab)
    if slot_data is None:
        return redirect(url_for("labs_pages.edit_lab", lab_id=lab.id))

    slot = LabSlot(lab_id=lab.id, **slot_data)
    db.session.add(slot)
    db.session.commit()
    flash("Lab slot created.", "success")
    return redirect(
        url_for("labs_pages.lab_saved", lab_id=lab.id, slot_id=slot.id)
    )


@labs_pages.post("/labs/<int:lab_id>/slots/<int:slot_id>/update")
@csrf_protect
def update_slot(lab_id, slot_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)
    slot = LabSlot.query.filter_by(id=slot_id, lab_id=lab.id).first_or_404()

    if _active_reservation_count(slot):
        flash("A slot with active reservations cannot be edited.", "error")
        return redirect(
            url_for("labs_pages.edit_lab", lab_id=lab.id, slot_id=slot.id)
        )

    slot_data = _parse_slot_form(lab)
    if slot_data is None:
        return redirect(
            url_for("labs_pages.edit_lab", lab_id=lab.id, slot_id=slot.id)
        )

    for field, value in slot_data.items():
        setattr(slot, field, value)
    db.session.commit()
    flash("Lab slot updated.", "success")
    return redirect(
        url_for("labs_pages.lab_saved", lab_id=lab.id, slot_id=slot.id)
    )


@labs_pages.post("/labs/<int:lab_id>/slots/<int:slot_id>/toggle")
@csrf_protect
def toggle_slot(lab_id, slot_id):
    lab = db.get_or_404(Lab, lab_id)
    _require_lab_manager(lab)
    slot = LabSlot.query.filter_by(id=slot_id, lab_id=lab.id).first_or_404()
    slot.is_active = not slot.is_active
    db.session.commit()
    flash("Lab slot updated.", "success")
    return redirect(
        url_for("labs_pages.lab_saved", lab_id=lab.id, slot_id=slot.id)
    )
