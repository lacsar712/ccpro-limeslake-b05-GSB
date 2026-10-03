from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond
from app.services.legend import STATUS_KEYS, get_visibility
from app.services.rules import RuleError, assert_can_set_pond_status, latest_batch_for_pond

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


@bp.route("/")
@login_required
def floor_plan():
    plants = Plant.query.order_by(Plant.name).all()
    plant_id_raw = request.args.get("plant_id", "").strip()
    active_plant = None
    if plant_id_raw.isdigit():
        active_plant = db.session.get(Plant, int(plant_id_raw))
    if active_plant is None and plants:
        active_plant = plants[0]

    ponds = []
    if active_plant:
        ponds = (
            Pond.query.filter_by(plant_id=active_plant.id)
            .order_by(Pond.code)
            .all()
        )

    visibility = get_visibility()

    all_cards = []
    pond_cards = []
    for pond in ponds:
        batch = latest_batch_for_pond(pond)
        card = {"pond": pond, "batch": batch}
        all_cards.append(card)
        # 只在网格中隐藏瓦片；偏好不改动池本身的任何状态
        if visibility.get(pond.status, True):
            pond_cards.append(card)

    hidden_statuses = [
        STATUS_LABELS[key] for key in STATUS_KEYS if not visibility.get(key, True)
    ]

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    if selected_id:
        selected = next((c["pond"] for c in all_cards if c["pond"].id == selected_id), None)
        if selected:
            selected_batch = latest_batch_for_pond(selected)

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        hidden_total=len(all_cards) - len(pond_cards),
        hidden_statuses=hidden_statuses,
        visibility=visibility,
        selected=selected,
        selected_batch=selected_batch,
        status_labels=STATUS_LABELS,
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    pond = Pond.query.get_or_404(pond_id)
    status = request.form.get("status") or pond.status
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()

    batch = latest_batch_for_pond(pond)
    if batch is None:
        flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    if peak_raw:
        try:
            batch.peak_temp_c = float(peak_raw)
        except ValueError:
            flash("峰值温度格式无效", "error")
            return redirect(
                url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
            )

    batch.notes = notes

    try:
        assert_can_set_pond_status(pond, status)
        pond.status = status
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id))
