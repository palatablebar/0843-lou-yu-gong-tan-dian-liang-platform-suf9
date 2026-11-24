"""合同上限能力的命名兼容入口。"""
from app.domain.allocation import (  # noqa: F401
    AllocationResult,
    ShareList,
    allocate_by_area,
    allocate_common,
    allocate_with_caps,
    apportion,
    cap_from_room,
    capped_allocation,
    capped_largest_remainder,
    largest_remainder_with_caps,
    largest_remainder_with_limits,
    normalize_caps,
    to_wh,
)
