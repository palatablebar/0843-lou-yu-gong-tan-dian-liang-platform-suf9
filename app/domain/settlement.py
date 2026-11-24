"""命名兼容：结算/出账领域入口。"""
from app.domain.allocation import (  # noqa: F401
    allocate_with_caps,
    capped_largest_remainder,
    split_common,
    split_shared,
)
from app.domain.calculate import calculate_rows  # noqa: F401
from app.domain.decision import decide_rows  # noqa: F401


def settle(rows, limits=None):
    return decide_rows(calculate_rows(rows, limits=limits))


settle_rows = settle
