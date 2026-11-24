"""合同上限（contract limits）命名兼容入口。"""
from app.domain.caps import *  # noqa: F401,F403
from app.domain.caps import allocate_with_caps  # noqa: F401
from app.domain.allocation import (  # noqa: F401
    largest_remainder_with_limits as allocate_with_limits_name,
)


def allocate_with_limits(total, weights=None, limits=None, **kwargs):
    from app.domain.allocation import allocate_with_caps
    return allocate_with_caps(total, weights, caps=limits, **kwargs)
