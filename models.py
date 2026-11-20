from datetime import UTC, datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, UniqueConstraint, text

db = SQLAlchemy()
BIGINT_ID = db.BigInteger().with_variant(db.Integer, "sqlite")


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class Profile(db.Model):
    __tablename__ = "profile"

    id = db.Column(BIGINT_ID, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    primary_email = db.Column(db.String(255), unique=True, nullable=False)
    secondary_email = db.Column(db.String(255), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(255),
        nullable=False,
        default="student",
        server_default=text("'student'"),
    )
    tokens = db.Column(db.String(255), nullable=True)
    failed_login_attempts = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    login_locked_until = db.Column(db.DateTime, nullable=True)
    last_active = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )
    phone_number = db.Column(db.String(255), unique=True, nullable=True)
    department = db.Column(db.String(255), nullable=False)
    student_id = db.Column(db.String(255), unique=True, nullable=True)
    profile_image_url = db.Column(db.String(255), nullable=True)

    # Relationships
    lab_reservations = db.relationship("LabReservation", back_populates="profile", lazy=True)
    event_reservations = db.relationship("EventReservation", back_populates="profile", lazy=True)
    used_items = db.relationship("UsedItem", back_populates="seller", lazy=True)
    lost_and_found_reports = db.relationship("LostAndFound", back_populates="reporter", lazy=True)
    notifications = db.relationship("Notification", back_populates="profile", lazy=True)
    password_resets = db.relationship("PasswordReset", back_populates="profile", lazy=True)
    saved_items = db.relationship("SavedItem", back_populates="profile", lazy=True)
    starred_events = db.relationship("StarredEvent", back_populates="profile", lazy=True)

    def __repr__(self):
        return f"<Profile {self.id}: {self.name} ({self.role})>"


class Lab(db.Model):
    __tablename__ = "lab"

    id = db.Column(BIGINT_ID, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(20), nullable=True)
    capacity = db.Column(db.BigInteger, nullable=False)
    status = db.Column(
        db.String(255),
        nullable=False,
        default="available",
        server_default=text("'available'"),
    )
    room = db.Column(db.String(255), nullable=False)

    # Relationships
    slots = db.relationship("LabSlot", back_populates="lab", lazy=True)

    def __repr__(self):
        return f"<Lab {self.id}: {self.name} - {self.room}>"


class LabSlot(db.Model):
    __tablename__ = "lab_slots"

    id = db.Column(BIGINT_ID, primary_key=True)
    lab_id = db.Column(db.BigInteger, db.ForeignKey("lab.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.BigInteger, nullable=False)
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    # Relationships
    lab = db.relationship("Lab", back_populates="slots")
    reservations = db.relationship("LabReservation", back_populates="slot", lazy=True)

    def __repr__(self):
        return f"<LabSlot {self.id}: Lab {self.lab_id} on {self.date}>"


class LabReservation(db.Model):
    __tablename__ = "lab_reservation"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    slot_id = db.Column(db.BigInteger, db.ForeignKey("lab_slots.id"), nullable=False)
    status = db.Column(
        db.String(255),
        nullable=False,
        default="confirmed",
        server_default=text("'confirmed'"),
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    __table_args__ = (
        Index(
            "lab_reservation_active_unique",
            "profile_id",
            "slot_id",
            unique=True,
            postgresql_where=text("status != 'cancelled'"),
        ),
    )

    # Relationships
    profile = db.relationship("Profile", back_populates="lab_reservations")
    slot = db.relationship("LabSlot", back_populates="reservations")

    def __repr__(self):
        return f"<LabReservation {self.id}: Profile {self.profile_id} -> Slot {self.slot_id}>"


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(BIGINT_ID, primary_key=True)
    event_name = db.Column(db.String(255), nullable=False)
    organizer = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.BigInteger, nullable=True)
    registration_status = db.Column(
        db.String(255),
        nullable=False,
        default="open",
        server_default=text("'open'"),
    )
    category = db.Column(db.String(255), nullable=False)
    agenda = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    # Relationships
    reservations = db.relationship("EventReservation", back_populates="event", lazy=True)
    starred_by = db.relationship("StarredEvent", back_populates="event", lazy=True)

    def __repr__(self):
        return f"<Event {self.id}: {self.event_name}>"


class EventReservation(db.Model):
    __tablename__ = "event_reservation"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id"), nullable=False)
    status = db.Column(
        db.String(255),
        nullable=False,
        default="registered",
        server_default=text("'registered'"),
    )
    reminder = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    __table_args__ = (
        Index(
            "event_reservation_active_unique",
            "profile_id",
            "event_id",
            unique=True,
            postgresql_where=text("status != 'cancelled'"),
        ),
    )

    # Relationships
    profile = db.relationship("Profile", back_populates="event_reservations")
    event = db.relationship("Event", back_populates="reservations")

    def __repr__(self):
        return f"<EventReservation {self.id}: Profile {self.profile_id} -> Event {self.event_id}>"


class UsedItem(db.Model):
    __tablename__ = "used_items"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    item_name = db.Column(db.String(255), nullable=False)
    condition = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(255), nullable=False)
    meeting_point = db.Column(db.String(255), nullable=True)
    status = db.Column(
        db.String(255),
        nullable=False,
        default="available",
        server_default=text("'available'"),
    )
    phone_number = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )
    image_url = db.Column(db.String(255), nullable=True)
    is_anonymous = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    price = db.Column(
        db.Numeric(8, 2),
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    listing_type = db.Column(db.String(255), nullable=False)

    # Relationships
    seller = db.relationship("Profile", back_populates="used_items")
    saved_by = db.relationship("SavedItem", back_populates="used_item", lazy=True)

    def __repr__(self):
        return f"<UsedItem {self.id}: {self.item_name} ({self.listing_type})>"


class LostAndFound(db.Model):
    __tablename__ = "lost_and_found"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    item_name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(255), nullable=False)  # 'lost' or 'found'
    category = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=True)
    status = db.Column(
        db.String(255),
        nullable=False,
        default="open",
        server_default=text("'open'"),
    )
    phone_number = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    image_url = db.Column(db.String(255), nullable=True)
    is_anonymous = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    # Relationships
    reporter = db.relationship("Profile", back_populates="lost_and_found_reports")

    def __repr__(self):
        return f"<LostAndFound {self.id}: {self.item_name} ({self.type})>"


class Notification(db.Model):
    __tablename__ = "notification"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )
    is_read = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # Relationships
    profile = db.relationship("Profile", back_populates="notifications")

    def __repr__(self):
        return f"<Notification {self.id}: {self.title}>"


class PasswordReset(db.Model):
    __tablename__ = "password_reset"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    code = db.Column(db.String(255), nullable=False)
    reset_session_token = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(
        db.BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    requested_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    # Relationships
    profile = db.relationship("Profile", back_populates="password_resets")

    def __repr__(self):
        return f"<PasswordReset {self.id}: Profile {self.profile_id}>"


class SavedItem(db.Model):
    __tablename__ = "saved_items"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    used_item_id = db.Column(db.BigInteger, db.ForeignKey("used_items.id"), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("profile_id", "used_item_id", name="saved_items_profile_item_unique"),
    )

    # Relationships
    profile = db.relationship("Profile", back_populates="saved_items")
    used_item = db.relationship("UsedItem", back_populates="saved_by")

    def __repr__(self):
        return f"<SavedItem {self.id}: Profile {self.profile_id} -> Item {self.used_item_id}>"


class StarredEvent(db.Model):
    __tablename__ = "starred_events"

    id = db.Column(BIGINT_ID, primary_key=True)
    profile_id = db.Column(db.BigInteger, db.ForeignKey("profile.id"), nullable=False)
    event_id = db.Column(db.BigInteger, db.ForeignKey("events.id"), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        server_default=db.func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("profile_id", "event_id", name="starred_events_profile_event_unique"),
    )

    # Relationships
    profile = db.relationship("Profile", back_populates="starred_events")
    event = db.relationship("Event", back_populates="starred_by")

    def __repr__(self):
        return f"<StarredEvent {self.id}: Profile {self.profile_id} -> Event {self.event_id}>"