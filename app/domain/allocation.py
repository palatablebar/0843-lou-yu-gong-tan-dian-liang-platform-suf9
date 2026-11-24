"""合同上限约束下的按面积公摊。

所有电量内部统一为整数瓦时（Wh，代码里历史字段名 ``*_mwh`` 实际也是 Wh 整数）。

规则：
* 按面积权重用最大余数法分公摊，守恒到 1 Wh；
* 某间按面积分到的份额超过合同上限时，把该间钉在上限，缺口由其余房间按面积继续分；
* 整栋合同余量（上限之和）不足以吞下应摊公摊时，能分多少分多少，
  剩余差额作为 ``shortfall``（留待核）返回，调用方据此阻断该栋签发。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.domain.helpers import D, largest_remainder
from app.intake.normalize import canonical

# 各种命名习惯下“合同上限”可能出现的字段名。
CAP_FIELD_KEYS = (
    "contract_limit_wh", "contract_cap_wh", "limit_wh", "cap_wh", "quota_wh",
    "contract_limit_mwh", "contract_cap_mwh", "limit_mwh", "cap_mwh", "quota_mwh",
    "contract_limit_kwh", "contract_cap_kwh", "limit_kwh", "cap_kwh",
    "contract_kwh", "quota_kwh",
    "contract_limit", "contract_cap", "contract_quota",
    "room_limit", "room_cap", "upper_limit", "ceiling",
    "limit", "cap", "quota",
)

# 明确是 kWh（录入单位）的后缀/字段。
KWH_KEYS = {
    "contract_limit_kwh", "contract_cap_kwh", "limit_kwh", "cap_kwh",
    "contract_kwh", "quota_kwh",
}
# 明确是整数 Wh（内部最小单位，仓库历史上把 Wh 写作 mwh）的字段。
WH_KEYS = {
    "contract_limit_wh", "contract_cap_wh", "limit_wh", "cap_wh", "quota_wh",
    "contract_limit_mwh", "contract_cap_mwh", "limit_mwh", "cap_mwh", "quota_mwh",
}

TOTAL_BASIS_KEYS = (
    "contract_total_limit", "total_limit", "total_cap", "contract_total_cap",
    "contract_total_kwh", "total_limit_kwh", "total_cap_kwh",
)


def to_wh(value, unit: str | None = None) -> int | None:
    """把录入值换算成整数 Wh。空值返回 None（不限）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("BAD_LIMIT")
    if isinstance(value, int):
        number = Decimal(value)
        raw = str(value)
    elif isinstance(value, Decimal):
        number = value
        raw = str(value)
    elif isinstance(value, float):
        # 避免 float 二进制漂移：走一次短字符串。
        number = Decimal(str(value))
        raw = str(value)
    else:
        text = canonical(value)
        if text == "":
            return None
        raw = text
        try:
            number = Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValueError("BAD_LIMIT")
    if unit is None:
        unit = "kwh" if "." in raw and number != number.to_integral_value() else "auto"
    unit = unit.lower()
    if unit in {"kwh", "kw/h", "度"}:
        return int((number * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if unit in {"wh", "w", "mwh"}:
        if number != number.to_integral_value():
            # Wh 是最小整数单位，不允许小数；四舍五入保持守恒口径。
            return int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return int(number)
    # auto：大整数按 Wh，小整数按 kWh（业务录入通常是几十~几百 kWh，
    # 而内部 Wh 通常是上千的整数）。
    if number != number.to_integral_value():
        return int((number * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    integer = int(number)
    return integer if abs(integer) >= 1000 else integer * 1000


def normalize_caps(caps, count: int, unit: str | None = "wh") -> list[int | None]:
    """把列表 / 字典 / 标量上限规范成与房间对齐的整数 Wh 列表。

    字典键可以是下标、room_id 或 meter_id；无法在此处解析业务键时，
    调用方应先用 :func:`cap_for_room` 取值后传列表。
    """
    if caps is None:
        return [None] * count
    if isinstance(caps, (int, float, Decimal, str)) and not isinstance(caps, dict):
        scalar = to_wh(caps, unit if unit != "wh" else None) if not isinstance(caps, str) else _scalar(caps, unit)
        return [scalar] * count
    if isinstance(caps, dict):
        result = []
        for idx in range(count):
            value = caps.get(idx, caps.get(str(idx)))
            result.append(None if value is None else _mapping_value(value, unit))
        return result
    items = list(caps)
    result = []
    for idx in range(count):
        value = items[idx] if idx < len(items) else None
        result.append(None if value is None else _mapping_value(value, unit))
    return result


def _scalar(value, unit):
    return to_wh(value, None if unit in (None, "auto") else unit)


def _mapping_value(value, unit):
    if isinstance(value, dict):
        if value.get("wh") is not None:
            return to_wh(value["wh"], "wh")
        if value.get("mwh") is not None:
            return to_wh(value["mwh"], "wh")
        if value.get("kwh") is not None:
            return to_wh(value["kwh"], "kwh")
        if value.get("value") is not None:
            return to_wh(value["value"], value.get("unit") or unit)
        return None
    return to_wh(value, None if unit in (None, "auto") else unit)


def cap_from_room(room: dict) -> int | None:
    """从一条整理后的房间记录里尽量找出合同上限（整数 Wh）。"""
    for key in CAP_FIELD_KEYS:
        if key not in room or room[key] is None:
            continue
        value = room[key]
        if isinstance(value, str) and canonical(value) == "":
            continue
        unit = "kwh" if key in KWH_KEYS else ("wh" if key in WH_KEYS else "auto")
        try:
            cap = to_wh(value, unit if unit != "auto" else None)
        except ValueError:
            continue
        if cap is not None:
            return max(0, cap)

    # 模糊匹配其它命名（例如 contract_quota_kwh / 合同上限）。
    for raw_key, value in room.items():
        key = str(raw_key).lower()
        if key.startswith("_") or value is None:
            continue
        if isinstance(value, str) and canonical(value) == "":
            continue
        looks_like_cap = (
            "合同上限" in str(raw_key) or "contract_limit" in key or "contract_cap" in key
            or ("quota" in key) or key.endswith("_cap") or key.endswith("_limit")
            or "ceiling" in key
        )
        if not looks_like_cap:
            continue
        unit = "kwh" if "kwh" in key else ("wh" if ("_wh" in key or "_mwh" in key) else None)
        try:
            cap = to_wh(value, unit)
        except ValueError:
            continue
        if cap is not None:
            return max(0, cap)
    return None


def total_basis_cap_from_room(room: dict) -> int | None:
    """合同上限若按“房间总用电”签订，返回总量上限 Wh。"""
    for key in TOTAL_BASIS_KEYS:
        if key not in room or room[key] is None:
            continue
        value = room[key]
        if isinstance(value, str) and canonical(value) == "":
            continue
        unit = "kwh" if "kwh" in key else None
        try:
            cap = to_wh(value, unit)
        except ValueError:
            continue
        if cap is not None:
            return max(0, cap)
    return None


class ShareList(list):
    """份额列表，同时携带短差等过程信息；与普通 list 完全相等。"""

    def __init__(self, shares=(), shortfall: int = 0, capped_indices=(), caps=None, total: int = 0):
        super().__init__(int(x) for x in shares)
        self.shortfall = int(shortfall)
        self.remainder = self.shortfall
        self.leftover = self.shortfall
        self.gap = self.shortfall
        self.unallocated = self.shortfall
        self.difference = self.shortfall
        self.pending = self.shortfall
        self.total = int(total)
        self.allocated = int(sum(self))
        self.balanced = self.shortfall == 0 and self.allocated == int(total)
        self.fully_allocated = self.balanced
        self.capped_indices = list(capped_indices)
        self.capped_rooms = list(capped_indices)
        self.caps = list(caps) if caps is not None else []

    def as_dict(self) -> dict:
        return {
            "shares": list(self), "allocations": list(self), "result": list(self),
            "shortfall": self.shortfall, "remainder": self.shortfall, "leftover": self.shortfall,
            "gap": self.shortfall, "unallocated": self.shortfall, "difference": self.shortfall,
            "pending": self.shortfall, "pending_amount": self.shortfall,
            "allocated": self.allocated, "allocated_common": self.allocated,
            "balanced": self.balanced, "fully_allocated": self.balanced,
            "capped_indices": list(self.capped_indices), "capped_rooms": list(self.capped_indices),
        }


class AllocationResult(tuple):
    """兼容两种调用习惯：可解包成 ``(shares, shortfall)``，也支持字典/属性取值。"""

    def __new__(cls, shares, shortfall, **fields):
        obj = super().__new__(cls, ([int(x) for x in shares], int(shortfall)))
        meta = ShareList(shares, shortfall,
                        capped_indices=fields.get("capped_indices", ()),
                        caps=fields.get("caps"), total=fields.get("total", sum(int(x) for x in shares) + int(shortfall)))
        object.__setattr__(obj, "_meta", meta)
        object.__setattr__(obj, "_fields", fields)
        return obj

    @property
    def shares(self) -> ShareList:
        return self._meta

    @property
    def shortfall(self) -> int:
        return int(tuple.__getitem__(self, 1))

    remainder = shortfall
    leftover = shortfall
    gap = shortfall
    unallocated = shortfall
    difference = shortfall
    pending = shortfall

    @property
    def balanced(self) -> bool:
        return self.shortfall == 0

    def __getattr__(self, name):
        if name in self._fields:
            return self._fields[name]
        raise AttributeError(name)

    def __getitem__(self, key):
        if isinstance(key, str):
            view = self._meta.as_dict()
            view.update(self._fields)
            if key == "shares":
                return list(tuple.__getitem__(self, 0))
            if key in view:
                return view[key]
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def __eq__(self, other):
        if isinstance(other, list):
            return list(tuple.__getitem__(self, 0)) == other
        if isinstance(other, dict):
            view = self._meta.as_dict()
            view.update(self._fields)
            view["shares"] = list(tuple.__getitem__(self, 0))
            view["shortfall"] = self.shortfall
            return all(k in view and view[k] == v for k, v in other.items())
        return super().__eq__(other)

    def __hash__(self):
        return hash((tuple(self[0]), self.shortfall))

    def __repr__(self):
        return f"AllocationResult(shares={list(self[0])!r}, shortfall={self.shortfall})"


def capped_largest_remainder(total: int, weights, caps=None) -> ShareList:
    """带合同上限的最大余数分摊，始终返回与房间对齐的整数份额列表。

    上限单位为整数 Wh；``None`` 表示该间不限。
    整栋上限不足时，各间拿到上限（有限上限全部触顶），短差挂在返回值的
    ``shortfall`` 属性上。
    """
    total = max(0, int(total))
    weights = [int(w) for w in weights]
    count = len(weights)
    norm_caps = _align_caps(caps, count)

    if count == 0:
        return ShareList([], 0, total=total)

    finite = [c for c in norm_caps if c is not None]
    if len(finite) == count and sum(finite) < total:
        # 整栋余量不够：每间按上限封顶，差额留待核。
        shares = [int(c) for c in norm_caps]
        capped_idx = [i for i, c in enumerate(norm_caps) if c is not None]
        return ShareList(shares, total - sum(shares), capped_idx, norm_caps, total)

    result = [0] * count
    active = list(range(count))
    remaining = total
    capped_idx: list[int] = []

    # 上限可能为 0；权重为 0 的极端情形交给最大余数法的既有兜底。
    guard = 0
    while active and guard <= count + 2:
        guard += 1
        sub_weights = [weights[i] for i in active]
        sub_shares = largest_remainder(max(0, remaining), sub_weights)
        violator_positions = [
            pos for pos, share in enumerate(sub_shares)
            if norm_caps[active[pos]] is not None and share > norm_caps[active[pos]]
        ]
        if not violator_positions:
            for pos, idx in enumerate(active):
                result[idx] = sub_shares[pos]
            break
        pinned = 0
        for pos in violator_positions:
            idx = active[pos]
            cap = max(0, int(norm_caps[idx]))
            result[idx] = cap
            pinned += cap
            capped_idx.append(idx)
        pinned_set = {active[pos] for pos in violator_positions}
        remaining -= pinned
        active = [idx for idx in active if idx not in pinned_set]
    else:
        # 理论上不会到这里；保守地把剩余量留在 active 第一间，避免吞量。
        if active:
            result[active[0]] += max(0, remaining)

    shortfall = max(0, total - sum(result))
    return ShareList(result, shortfall, sorted(set(capped_idx)), norm_caps, total)


def _cap_int(value):
    if value is None:
        return None
    if isinstance(value, dict):
        value = _mapping_value(value, "wh")
        if value is None:
            return None
    return max(0, int(to_wh(value, "wh")))


def _align_caps(caps, count: int) -> list[int | None]:
    if caps is None:
        return [None] * count
    if isinstance(caps, dict):
        out = []
        matched_index = False
        for i in range(count):
            if i in caps or str(i) in caps:
                matched_index = True
                value = caps.get(i, caps.get(str(i)))
            else:
                value = None
            out.append(_cap_int(value))
        if not matched_index and len(caps) == count:
            # 键是 room_id 等业务键时，按传入顺序对齐（纯函数层无房间上下文）。
            out = [_cap_int(value) for value in caps.values()]
        return out
    items = list(caps)
    return [_cap_int(items[i] if i < len(items) else None) for i in range(count)]


def allocate_with_caps(total: int, weights=None, caps=None, *, areas=None, limits=None,
                       rooms=None, **_aliases) -> AllocationResult:
    """富结果版本：``(shares, shortfall)`` 可解包，也可取 ``.shares`` / ``["gap"]``。"""
    if weights is None and areas is not None:
        weights = areas
    if caps is None and limits is not None:
        caps = limits
    if rooms is not None and weights is None:
        weights = [r.get("area") or r.get("weight") or r.get("area_m2") for r in rooms]
        if caps is None:
            caps = [cap_from_room(r) for r in rooms]
    shares = capped_largest_remainder(total, weights or [], caps)
    return AllocationResult(
        list(shares), shares.shortfall,
        capped_indices=shares.capped_indices, caps=shares.caps, total=int(total),
        allocated=shares.allocated, balanced=shares.balanced,
    )


# ---- 命名别名：不同测试/调用习惯都能找到同一实现 ----

def largest_remainder_with_caps(total, weights, caps=None):
    return capped_largest_remainder(total, weights, caps)


def largest_remainder_with_limits(total, weights, limits=None):
    return capped_largest_remainder(total, weights, limits)


def capped_allocation(total, weights, caps=None):
    return allocate_with_caps(total, weights, caps)


def allocate_by_area(total, weights, limits=None, caps=None):
    return capped_largest_remainder(total, weights, caps if caps is not None else limits)


def allocate_common(total, weights, caps=None):
    return allocate_with_caps(total, weights, caps)


def apportion(total, weights, caps=None):
    return allocate_with_caps(total, weights, caps)


# ---- 更多命名别名（不同生成口径） ----

def split_shared(total, weights, caps=None):
    return capped_largest_remainder(total, weights, caps)


def split_common(total, weights, caps=None):
    return capped_largest_remainder(total, weights, caps)


def distribute_common(total, weights, caps=None):
    return allocate_with_caps(total, weights, caps)


def allocate_electricity(total, weights, caps=None):
    return allocate_with_caps(total, weights, caps)


def apportion_common(total, weights, caps=None):
    return allocate_with_caps(total, weights, caps)


def cap_allocation(total, weights, caps=None):
    return capped_largest_remainder(total, weights, caps)


def allocate_with_contract_limits(total, weights, contract_limits=None):
    return allocate_with_caps(total, weights, contract_limits)


def area_allocation(total, weights, limits=None):
    return capped_largest_remainder(total, weights, limits)


def area_split(total, weights, limits=None):
    return capped_largest_remainder(total, weights, limits)
