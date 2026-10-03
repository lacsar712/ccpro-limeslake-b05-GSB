"""图例（瓦片分类）显隐偏好。

全系统单行：两名主管几乎同时提交时，靠固定主键 + 事务内行锁保证
库里只留一版，后提交者整体覆盖，不会拼出两套勾选的混合体。
偏好只控制平面图瓦片显隐，不触碰任何 Pond 状态。
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import LegendPreference, Pond

# 种子默认：三类全显。仅在库里尚无偏好行时使用，保存后以库中版本为准。
DEFAULT_VISIBILITY = {
    Pond.STATUS_FILLING: True,
    Pond.STATUS_SLAKING: True,
    Pond.STATUS_DRAWN: True,
}

STATUS_KEYS = (Pond.STATUS_FILLING, Pond.STATUS_SLAKING, Pond.STATUS_DRAWN)


def get_visibility() -> dict:
    """返回当前各状态是否显示；无偏好行时返回种子默认（不落库）。"""
    pref = db.session.get(LegendPreference, LegendPreference.SINGLETON_ID)
    if pref is None:
        return dict(DEFAULT_VISIBILITY)
    return pref.as_visibility()


def _lock_preference() -> LegendPreference | None:
    """事务内锁住单行偏好，串行化并发提交。"""
    return db.session.get(
        LegendPreference,
        LegendPreference.SINGLETON_ID,
        with_for_update=True,
    )


def save_visibility(visibility: dict) -> LegendPreference:
    """整体写入一版勾选。

    visibility 必须含三种状态的布尔值，整版覆盖。
    通过固定主键的行锁 + 唯一行约束，并发提交只会留下一版。
    """
    values = {key: bool(visibility.get(key, True)) for key in STATUS_KEYS}

    # 外层仅处理两个新事务同时 INSERT 单行的极小窗口；
    # 其中一个 commit 撞唯一/CHECK 约束失败后，整版重试为 UPDATE。
    for attempt in range(2):
        pref = _lock_preference()
        if pref is None:
            pref = LegendPreference(
                id=LegendPreference.SINGLETON_ID,
                show_filling=values[Pond.STATUS_FILLING],
                show_slaking=values[Pond.STATUS_SLAKING],
                show_drawn=values[Pond.STATUS_DRAWN],
            )
            db.session.add(pref)
        else:
            pref.show_filling = values[Pond.STATUS_FILLING]
            pref.show_slaking = values[Pond.STATUS_SLAKING]
            pref.show_drawn = values[Pond.STATUS_DRAWN]
        try:
            db.session.commit()
            return pref
        except IntegrityError:
            db.session.rollback()
            if attempt == 0:
                continue
            raise
    return pref  # pragma: no cover
