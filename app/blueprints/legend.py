from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import Pond
from app.services.legend import STATUS_KEYS, get_visibility, save_visibility

bp = Blueprint("legend", __name__, url_prefix="/legend")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}

# 勾选框 name -> Pond 状态
CHECKBOX_FIELDS = (
    ("show_filling", Pond.STATUS_FILLING),
    ("show_slaking", Pond.STATUS_SLAKING),
    ("show_drawn", Pond.STATUS_DRAWN),
)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            # 操作工只能看，不能改：拒绝任何提交，而不是静默忽略
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@bp.route("/")
@login_required
def preferences():
    visibility = get_visibility()
    return render_template(
        "legend/preferences.html",
        visibility=visibility,
        status_keys=STATUS_KEYS,
        status_labels=STATUS_LABELS,
        is_admin=current_user.role == "admin",
    )


@bp.route("/", methods=["POST"])
@admin_required
def save_preferences():
    visibility = {}
    for field_name, status_key in CHECKBOX_FIELDS:
        # 未勾选的 checkbox 不会出现在表单里 -> 显式视为 False
        visibility[status_key] = request.form.get(field_name) in ("on", "1", "true", "yes")

    # 偏好保存与池状态完全隔离：此处只写 legend_preferences 单行
    save_visibility(visibility)
    flash("图例偏好已保存，平面图瓦片显隐已更新", "ok")
    return redirect(url_for("legend.preferences"))
