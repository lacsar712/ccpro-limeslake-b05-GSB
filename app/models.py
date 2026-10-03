from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="worker")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Plant(db.Model):
    __tablename__ = "plants"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(200), nullable=False, default="")
    notes = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    ponds = db.relationship("Pond", back_populates="plant", cascade="all, delete-orphan")


class Pond(db.Model):
    __tablename__ = "ponds"
    __table_args__ = (
        db.UniqueConstraint("plant_id", "code", name="uq_pond_code_per_plant"),
    )

    STATUS_FILLING = "filling"
    STATUS_SLAKING = "slaking"
    STATUS_DRAWN = "drawn"
    STATUS_CHOICES = (STATUS_FILLING, STATUS_SLAKING, STATUS_DRAWN)

    id = db.Column(db.Integer, primary_key=True)
    plant_id = db.Column(db.Integer, db.ForeignKey("plants.id"), nullable=False)
    code = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_FILLING)
    capacity_m3 = db.Column(db.Float, nullable=False, default=0.0)
    notes = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    plant = db.relationship("Plant", back_populates="ponds")
    batches = db.relationship(
        "SlakeBatch",
        back_populates="pond",
        cascade="all, delete-orphan",
    )


class SlakeBatch(db.Model):
    __tablename__ = "slake_batches"

    id = db.Column(db.Integer, primary_key=True)
    pond_id = db.Column(db.Integer, db.ForeignKey("ponds.id"), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    target_temp_c = db.Column(db.Float, nullable=False, default=80.0)
    peak_temp_c = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=False, default="")

    pond = db.relationship("Pond", back_populates="batches")


class LegendPreference(db.Model):
    """图例偏好（全局单例，id 恒为 1）：控制三类状态瓦片在平面图上的显隐。"""

    __tablename__ = "legend_preferences"

    SINGLETON_ID = 1

    id = db.Column(db.Integer, primary_key=True)
    show_filling = db.Column(db.Boolean, nullable=False, default=True)
    show_slaking = db.Column(db.Boolean, nullable=False, default=True)
    show_drawn = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    STATUS_FIELDS = {
        Pond.STATUS_FILLING: "show_filling",
        Pond.STATUS_SLAKING: "show_slaking",
        Pond.STATUS_DRAWN: "show_drawn",
    }

    def is_visible(self, status: str) -> bool:
        return bool(getattr(self, self.STATUS_FIELDS[status]))

    def as_dict(self) -> dict[str, bool]:
        return {status: self.is_visible(status) for status in self.STATUS_FIELDS}
