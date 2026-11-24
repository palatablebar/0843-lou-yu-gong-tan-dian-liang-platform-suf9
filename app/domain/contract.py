"""命名兼容：合同上限（contract）入口。"""
from app.domain.contracts import normalize_contract_limits  # noqa: F401
from app.domain.allocation import (  # noqa: F401
    allocate_with_caps,
    cap_from_room,
    capped_largest_remainder,
    to_wh,
)


def apply_contract_limits(items, contract_limits=None, **kwargs):
    """整理后的房间记录 -> 带上限分摊的楼栋结果（含判定）。"""
    from app.domain.calculate import calculate_rows
    from app.domain.decision import decide_rows
    mapping = None
    if contract_limits is not None:
        mapping = normalize_contract_limits(contract_limits, kwargs.get("unit"))["mapping"]
    return decide_rows(calculate_rows(items, limits=mapping))
