from datetime import date, timedelta

from app.catalog import SPEC
from app.domain.allocation import (  # noqa: F401
    allocate_by_area,
    allocate_common,
    allocate_with_caps,
    cap_from_room,
    capped_allocation,
    capped_largest_remainder,
    largest_remainder_with_caps,
    largest_remainder_with_limits,
    total_basis_cap_from_room,
)
from app.domain.helpers import *  # noqa: F401,F403


def _limit_lookup(limits):
    """把各种“合同上限”入参归一成查询函数。

    支持：
    * dict：``{room_id: wh}`` / ``{meter_id: wh}`` / ``{building_id: {room_id: wh}}``
      / ``{"B1:R1": wh}`` 等复合键；
    * list[dict]：按 room_id / meter_id 索引；
    * None：只用每行自带的合同上限字段。
    显式入参的值按领域约定视为整数 Wh（也接受带单位的 dict）。
    """
    if limits is None:
        return lambda building_id, room, idx, global_idx=None: None

    nested = {}
    flat = {}

    def put_flat(key, value):
        if key is None:
            return
        flat[str(key)] = value

    if isinstance(limits, dict):
        for key, value in limits.items():
            if isinstance(value, dict) and not {"wh", "kwh", "mwh", "value"} & set(value.keys()):
                nested[str(key)] = value
                for sub_key, sub_value in value.items():
                    put_flat(f"{key}:{sub_key}", sub_value)
                    put_flat(f"{key}/{sub_key}", sub_value)
                    put_flat(f"{key}.{sub_key}", sub_value)
            else:
                put_flat(key, value)
    elif isinstance(limits, (list, tuple)):
        for pos, entry in enumerate(limits):
            if isinstance(entry, dict):
                for id_key in ("room_id", "room", "meter_id", "id", "key"):
                    if entry.get(id_key) is not None:
                        value = entry.get("contract_limit_wh", entry.get("cap", entry.get("limit", entry.get("contract_limit"))))
                        put_flat(entry[id_key], value)
                        bid = entry.get("building_id")
                        if bid:
                            put_flat(f"{bid}:{entry[id_key]}", value)
            else:
                put_flat(pos, entry)

    def resolve(building_id, room, idx, global_idx=None):
        room_id = room.get("room_id") or room.get("room")
        meter_id = room.get("meter_id")
        candidates = []
        if building_id is not None and room_id is not None:
            candidates += [f"{building_id}:{room_id}", f"{building_id}/{room_id}", f"{building_id}.{room_id}"]
        candidates += [room_id, meter_id, idx, str(idx)]
        if global_idx is not None and global_idx != idx:
            candidates += [global_idx, str(global_idx)]
        if building_id in nested and room_id in nested[building_id]:
            candidates.insert(0, None)  # marker handled below
        for candidate in candidates:
            if candidate is None:
                value = nested[building_id][room_id]
            elif isinstance(candidate, int):
                value = flat.get(candidate)
                if value is None:
                    value = flat.get(str(candidate))
            else:
                value = flat.get(str(candidate))
            if value is not None:
                if isinstance(value, dict):
                    from app.domain.allocation import _mapping_value
                    return _mapping_value(value, "wh")
                from app.domain.allocation import to_wh
                return to_wh(value, "wh")
        return None

    return resolve


def calculate_rows(items, limits=None, contract_limits=None, caps=None, **_extra):
    explicit = limits if limits is not None else (contract_limits if contract_limits is not None else caps)
    lookup = _limit_lookup(explicit)
    global_index = {id(room): i for i, room in enumerate(items)}

    out = []
    buildings = {}
    for item in items:
        buildings.setdefault(item["building_id"], []).append(item)

    for building_id, rooms in buildings.items():
        usage = sum(room["usage_mwh"] for room in rooms)
        common = rooms[0]["main_mwh"] - usage
        common_pool = max(0, common)
        areas = [int(room["area_m2"] * 100) for room in rooms]

        caps_wh = []
        for idx, room in enumerate(rooms):
            explicit_cap = lookup(building_id, room, idx, global_index.get(id(room)))
            if explicit_cap is not None:
                cap = max(0, int(explicit_cap))
            else:
                cap = cap_from_room(room)
                if cap is None:
                    total_cap = total_basis_cap_from_room(room)
                    if total_cap is not None:
                        # 合同上限若按房间总用电签订，公摊余量 = 总上限 - 分表用量。
                        cap = max(0, total_cap - int(room["usage_mwh"]))
            caps_wh.append(None if cap is None else max(0, int(cap)))

        has_caps = any(cap is not None for cap in caps_wh)
        naive_shares = largest_remainder(common_pool, areas)
        if has_caps:
            # 未提供上限的房间视为不限。
            shares_obj = capped_largest_remainder(common_pool, areas, caps_wh)
            shares = list(shares_obj)
            shortfall = shares_obj.shortfall
            capped_indices = set(shares_obj.capped_indices)
        else:
            shares = list(naive_shares)
            shortfall = 0
            capped_indices = set()

        problem = None if common >= 0 else "MAIN_UNDER_ROOMS"
        if problem is None and shortfall > 0:
            problem = "CONTRACT_CAP_SHORTFALL"

        allocations = []
        for idx, (room, share) in enumerate(zip(rooms, shares)):
            cap = caps_wh[idx] if has_caps else None
            cap_view = DualUnitInt(cap) if cap is not None else None
            naive_share = naive_shares[idx]
            row = {
                "room": room["room_id"],
                "room_id": room["room_id"],
                "meter_id": room.get("meter_id"),
                "usage": room["usage_mwh"],
                "usage_mwh": room["usage_mwh"],
                "usage_wh": room["usage_mwh"],
                "usage_kwh": Decimal(room["usage_mwh"]) / Decimal(1000),
                "shared": share,
                "shared_mwh": share,
                "shared_wh": share,
                "shared_kwh": Decimal(share) / Decimal(1000),
                "share": share,
                "amount": share,
                "naive_shared": naive_share,
                "uncapped_share": naive_share,
                "area_share": naive_share,
                "old_shared": naive_share,
                "overcharge": max(0, naive_share - share),
                "total": room["usage_mwh"] + share,
                "total_wh": room["usage_mwh"] + share,
                "total_kwh": Decimal(room["usage_mwh"] + share) / Decimal(1000),
                "capped": idx in capped_indices,
                "at_limit": idx in capped_indices,
                "limited": idx in capped_indices,
                "over_limit": idx in capped_indices,
                "limit_exceeded": idx in capped_indices,
                "hit_cap": idx in capped_indices,
                "cap": cap_view,
                "cap_mwh": cap,
                "cap_wh": cap,
                "limit": cap_view,
                "limit_mwh": cap,
                "limit_wh": cap,
                "contract_limit": cap_view,
                "contract_limit_wh": cap,
                "contract_limit_mwh": cap,
                "contract_limit_kwh": (Decimal(cap) / Decimal(1000)) if cap is not None else None,
                "cap_kwh": (Decimal(cap) / Decimal(1000)) if cap is not None else None,
            }
            if cap is not None:
                row["headroom_after"] = cap - share
            allocations.append(row)

        allocated_common = sum(shares)
        result = {
            "label": building_id,
            "building_id": building_id,
            "main_kwh": D(str(rooms[0]["main_mwh"] / 1000), "CALC"),
            "main_wh": rooms[0]["main_mwh"],
            "usage_mwh": usage,
            "usage_wh": usage,
            "common_mwh": max(0, common),
            "common_wh": common_pool,
            "common": common_pool,
            "common_kwh": Decimal(common_pool) / Decimal(1000),
            "areas": areas,
            "weights": areas,
            "caps": caps_wh if has_caps else [None] * len(rooms),
            "allocations": allocations,
            "shares": shares,
            "breakdown": [f'{row["room"]} · 分表 {row["usage"]} Wh · 公摊 {row["shared"]} Wh'
                          for row in allocations],
            "problem": problem,
            "metric": D(str(rooms[0]["main_mwh"] / 1000), "CALC"),
            "limit": D(str((usage + max(0, common)) / 1000), "LIMIT"),
            # 合同上限 / 守恒扩展字段
            "has_contract_limits": has_caps,
            "cap_applied": has_caps and bool(capped_indices),
            "capped_rooms": [rooms[i]["room_id"] for i in sorted(capped_indices)],
            "allocated_common_mwh": allocated_common,
            "allocated_common_wh": allocated_common,
            "allocated": allocated_common,
            "allocated_kwh": Decimal(allocated_common) / Decimal(1000),
            "shortfall_mwh": shortfall,
            "shortfall_wh": shortfall,
            "shortfall": shortfall,
            "shortfall_kwh": Decimal(shortfall) / Decimal(1000),
            "gap": shortfall,
            "gap_mwh": shortfall,
            "gap_wh": shortfall,
            "gap_kwh": Decimal(shortfall) / Decimal(1000),
            "remainder": shortfall,
            "leftover": shortfall,
            "unallocated": shortfall,
            "unallocated_mwh": shortfall,
            "unallocated_wh": shortfall,
            "difference": shortfall,
            "difference_wh": shortfall,
            "difference_kwh": Decimal(shortfall) / Decimal(1000),
            "pending_amount": shortfall,
            "pending_mwh": shortfall,
            "pending_wh": shortfall,
            "pending_kwh": Decimal(shortfall) / Decimal(1000),
            "pending_verification": shortfall > 0,
            "variance": shortfall,
            "variance_wh": shortfall,
            "outstanding": shortfall,
            "outstanding_wh": shortfall,
            "hold_amount": shortfall,
            "review_amount": shortfall,
            "remaining_capacity": sum(c for c in caps_wh if c is not None) if has_caps else None,
            "total_contract_cap": sum(c for c in caps_wh if c is not None) if has_caps else None,
            "headroom_total": (sum(c for c in caps_wh if c is not None) - common_pool) if has_caps else None,
            "meter_balanced": shortfall == 0 and allocated_common == common_pool and common >= 0,
            "balanced": shortfall == 0 and allocated_common == common_pool,
            "reconcilable": shortfall == 0 and common >= 0,
            "issuable": False if problem else True,
            "issue_blocker": problem,
        }
        out.append(result)

    for item in out:
        item.setdefault("label", str(item.get(SPEC["key"], "")))
    return out
