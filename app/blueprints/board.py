from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import update

from app.extensions import db
from app.models import LegendPreference, Plant, Pond, utcnow
from app.services.rules import RuleError, assert_can_set_pond_status, latest_batch_for_pond

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def get_legend_preference() -> LegendPreference:
    """取全局唯一的图例偏好；缺失时以“三类全显”补建（不依赖 seed 也成立）。"""
    pref = db.session.get(LegendPreference, LegendPreference.SINGLETON_ID)
    if pref is None:
        pref = LegendPreference(
            id=LegendPreference.SINGLETON_ID,
            show_filling=True,
            show_slaking=True,
            show_drawn=True,
        )
        db.session.add(pref)
        db.session.commit()
    return pref


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

    preference = get_legend_preference()

    # 未被偏好勾选的状态瓦片不进网格；偏好只影响显隐，绝不改动池状态。
    pond_cards = []
    for pond in ponds:
        if not preference.is_visible(pond.status):
            continue
        batch = latest_batch_for_pond(pond)
        pond_cards.append({"pond": pond, "batch": batch})

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    if selected_id:
        selected = next((c["pond"] for c in pond_cards if c["pond"].id == selected_id), None)
        if selected:
            selected_batch = latest_batch_for_pond(selected)

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        ponds=ponds,
        pond_cards=pond_cards,
        selected=selected,
        selected_batch=selected_batch,
        status_labels=STATUS_LABELS,
        preference=preference,
    )


@bp.route("/legend", methods=["GET", "POST"])
@login_required
def legend_preference():
    """图例偏好专页：管理员可勾选保存，操作工只能查看。"""
    preference = get_legend_preference()

    if request.method == "POST":
        if current_user.role != "admin":
            # 操作工只读：即使绕过页面直接 POST 也拒绝，绝不落库。
            abort(403)

        # 以“提交的整版勾选”为准：未勾选的复选框不会出现在表单里。
        show = {
            status: status in request.form
            for status in LegendPreference.STATUS_FIELDS
        }

        # 关键：用一条全列 UPDATE 写入三个显隐位，而不是 ORM 的“只更新脏列”。
        # 否则两位主管几乎同时提交不同勾选时，两笔事务各写各的变更列，
        # 会拼出一列来自 A、一列来自 B 的混合损坏态。全列写入保证后提交者
        # 整版覆盖，库里永远只留一套完整勾选，网格跟这一版走。
        db.session.execute(
            update(LegendPreference)
            .where(LegendPreference.id == LegendPreference.SINGLETON_ID)
            .values(
                show_filling=show[Pond.STATUS_FILLING],
                show_slaking=show[Pond.STATUS_SLAKING],
                show_drawn=show[Pond.STATUS_DRAWN],
                updated_by=current_user.id,
                updated_at=utcnow(),
            )
        )
        db.session.commit()
        flash("图例偏好已保存，平面图瓦片显隐已更新", "ok")
        return redirect(url_for("board.legend_preference"))

    return render_template(
        "board/legend.html",
        preference=preference,
        status_labels=STATUS_LABELS,
        is_admin=current_user.role == "admin",
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
