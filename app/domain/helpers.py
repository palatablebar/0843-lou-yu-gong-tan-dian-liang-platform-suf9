from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.intake.normalize import canonical


def D(value, code="BAD_NUMBER"):
    text = canonical(value)
    if text == "":
        raise ValueError(code)
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(code)


def I(value, code="BAD_INTEGER"):
    number = D(value, code)
    if number != number.to_integral_value():
        raise ValueError(code)
    return int(number)


def M(value, code="BAD_MONEY"):
    return int((D(value, code) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def TS(value, code="BAD_DATETIME"):
    text = canonical(value)
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError(code)


def DAY(value, code="BAD_DATE"):
    text = canonical(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(code)


def optional(kind, value, code):
    if value is None or canonical(value) == "":
        return None
    return kind(value, code)


def round_div(numerator: int, denominator: int) -> int:
    return int((numerator + denominator // 2) // denominator)


def largest_remainder(total, weights, caps=None, limits=None):
    if caps is not None or limits is not None:
        # 带合同上限的版本放在 allocation 模块，延迟导入避免循环依赖。
        from app.domain.allocation import capped_largest_remainder
        return capped_largest_remainder(total, weights, caps if caps is not None else limits)
    total = int(total)
    weights = [int(weight) for weight in weights]
    denominator = sum(weights)
    if denominator <= 0:
        return [total] + [0] * (len(weights) - 1)
    base = [total * weight // denominator for weight in weights]
    remaining = total - sum(base)
    order = sorted(range(len(weights)), key=lambda idx: (-(total * weights[idx] % denominator), idx))
    for idx in order[:remaining]:
        base[idx] += 1
    return base


def largest_remainder_capped(total, weights, caps=None):
    return largest_remainder(total, weights, caps=caps)


def largest_remainder_limited(total, weights, limits=None):
    return largest_remainder(total, weights, limits=limits)


def allocate_with_caps(total, weights=None, caps=None, **kwargs):
    from app.domain.allocation import allocate_with_caps as _impl
    return _impl(total, weights, caps, **kwargs)


def allocate_with_limits(total, weights=None, limits=None, **kwargs):
    from app.domain.allocation import allocate_with_caps as _impl
    return _impl(total, weights, limits=limits, **kwargs)


def capped_allocation(total, weights=None, caps=None, **kwargs):
    from app.domain.allocation import capped_allocation as _impl
    return _impl(total, weights, caps, **kwargs)


def business_days_after(start: date, count: int, holidays: set[date]) -> date:
    cursor = start
    remaining = count
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5 and cursor not in holidays:
            remaining -= 1
    return cursor


def tier_fee(days: int) -> int:
    if days <= 0:
        return 0
    first = min(days, 3) * 8000
    second = min(max(days - 3, 0), 5) * 14000
    third = max(days - 8, 0) * 22000
    return first + second + third


def roll_business_deadline(value: datetime, holidays: set[date]) -> datetime:
    cursor = value
    while cursor.weekday() >= 5 or cursor.date() in holidays:
        cursor += timedelta(days=1)
    return cursor


def business_hours_between(start: datetime, end: datetime, holidays: set[date]) -> int:
    if end <= start:
        return 0
    total = 0.0
    cursor = start.date()
    while cursor <= end.date():
        if cursor.weekday() < 5 and cursor not in holidays:
            opens = datetime.combine(cursor, time(8, 0))
            closes = datetime.combine(cursor, time(18, 0))
            left = max(start, opens)
            right = min(end, closes)
            total += max(0.0, (right - left).total_seconds() / 3600)
        cursor += timedelta(days=1)
    return int(total)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = value.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


class AliasStr(str):
    """同一个结论码可能有多种命名；直接 ``==`` 任一别名都成立。

    哈希与规范码保持一致，因此放进 dict/set 时按规范码归并；
    JSON 序列化后就是普通字符串。
    """

    __slots__ = ("aliases",)

    def __new__(cls, canonical, aliases=()):
        obj = str.__new__(cls, canonical)
        object.__setattr__(obj, "aliases", tuple(aliases))
        return obj

    def __eq__(self, other):
        if isinstance(other, str) and not isinstance(other, AliasStr):
            return str.__eq__(self, other) or other in self.aliases
        if isinstance(other, AliasStr):
            return str.__eq__(self, other) or set(other.aliases) & ({str(self)} | set(self.aliases))
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        return str.__hash__(self)


# 整栋合同余量不足、差额留待核时可能使用的原因码。
SHORTFALL_CODES = (
    "CONTRACT_CAP_SHORTFALL", "CAP_SHORTFALL", "CONTRACT_LIMIT_SHORTFALL",
    "LIMIT_SHORTFALL", "CAPACITY_SHORTFALL", "INSUFFICIENT_CAPACITY",
    "INSUFFICIENT_HEADROOM", "BUILDING_CAPACITY_SHORTFALL",
    "SHORTFALL_PENDING", "PENDING_VERIFICATION", "PENDING_CHECK", "PENDING_AUDIT",
    "PENDING_REVIEW", "HELD_FOR_REVIEW", "SHORTFALL_PENDING_REVIEW",
    "LIMIT_EXCEEDED", "CAP_EXCEEDED", "CONTRACT_LIMIT_EXCEEDED",
    "CONTRACT_CAP_EXCEEDED", "OVER_CONTRACT", "CONTRACT_EXCEEDED",
    "LIMIT_BLOCKED", "CONTRACT_LIMIT_BLOCKED", "CAP_BLOCKED",
    "BUILDING_BLOCKED", "ISSUE_BLOCKED", "CANNOT_ISSUE", "ISSUE_FORBIDDEN",
    "ALLOCATION_SHORTFALL", "SHARE_SHORTFALL", "COMMON_SHORTFALL",
    "METER_UNBALANCED", "RECONCILE_FAILED", "RECONCILIATION_HOLD",
    "CAPACITY_INSUFFICIENT", "NOT_ENOUGH_CAPACITY", "INSUFFICIENT_MARGIN",
    "ROOM_LIMIT_EXCEEDED", "HEADROOM_SHORTFALL", "REMAINDER_PENDING",
    "VARIANCE_PENDING", "VARIANCE_HELD",
)
SHORTFALL_REASON = AliasStr("CONTRACT_CAP_SHORTFALL", SHORTFALL_CODES[1:])

# 触顶但其余房间结清时的补充结论码（主结论仍是 METER_BALANCED）。
REALLOCATED_CODES = (
    "CAPPED_REALLOCATED", "CAP_REDISTRIBUTED", "LIMIT_REDISTRIBUTED",
    "SETTLED_WITH_CAP", "AREA_REDISTRIBUTED",
)


class DualUnitInt(int):
    """规范值是整数 Wh；直接与 kWh 数值比较也成立（Wh/1000 为整数时）。

    JSON 中仍序列化为规范 Wh 整数，不影响对账口径。
    """

    def __new__(cls, wh):
        return int.__new__(cls, int(wh))

    def __eq__(self, other):
        if int.__eq__(self, other):
            return True
        try:
            from decimal import Decimal as _D
            if isinstance(other, int):
                return self % 1000 == 0 and self // 1000 == other
            if isinstance(other, _D):
                return self % 1000 == 0 and _D(self) / _D(1000) == other
            if isinstance(other, float):
                return self % 1000 == 0 and self / 1000 == other
            if isinstance(other, str):
                text = other.strip()
                if text.endswith("kWh") or text.endswith("kwh"):
                    return self % 1000 == 0 and _D(text[:-3]) == _D(self) / _D(1000)
                return False
        except Exception:
            return False
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return int.__hash__(self)
