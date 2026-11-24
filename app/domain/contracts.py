"""月底录入的房间合同上限：HTTP/表单入参归一化。

对外单位默认按业务录入习惯自动识别（小数/kWh 量级按 kWh，
大整数按 Wh）；也可以显式传 ``unit='kwh'|'wh'``。
归一化后全部是整数 Wh，键同时保留 room_id / meter_id 与
``building_id:room_id`` 复合形式。
"""
from __future__ import annotations

from app.domain.allocation import to_wh


def normalize_contract_limits(payload, unit: str | None = None):
    """把请求里的 contract_limits/limits/caps 归一成 calculate_rows 可用的 dict。

    返回 ``{"flat": {...}, "nested": {bid: {room: wh}}, "items": [...]}`。
    """
    if payload is None:
        return {"flat": {}, "nested": {}, "items": []}

    forced_unit = None if unit in (None, "auto") else (unit or "").lower()

    def convert(value):
        if isinstance(value, dict):
            if value.get("wh") is not None:
                return to_wh(value["wh"], "wh")
            if value.get("mwh") is not None:
                return to_wh(value["mwh"], "wh")
            if value.get("kwh") is not None:
                return to_wh(value["kwh"], "kwh")
            for field in ("contract_limit_wh", "cap_wh", "limit_wh"):
                if value.get(field) is not None:
                    return to_wh(value[field], "wh")
            for field in ("contract_limit_kwh", "limit_kwh", "cap_kwh"):
                if value.get(field) is not None:
                    return to_wh(value[field], "kwh")
            return to_wh(value.get("value") or value.get("amount"),
                         value.get("unit") or forced_unit)
        return to_wh(value, forced_unit)

    flat: dict = {}
    nested: dict = {}
    items = []

    def record(building_id, room_id, meter_id, cap_wh, raw=None):
        if cap_wh is None:
            return
        cap_wh = max(0, int(cap_wh))
        if room_id is not None:
            flat[str(room_id)] = cap_wh
        if meter_id is not None:
            flat[str(meter_id)] = cap_wh
        if building_id is not None:
            bucket = nested.setdefault(str(building_id), {})
            if room_id is not None:
                bucket[str(room_id)] = cap_wh
                flat[f"{building_id}:{room_id}"] = cap_wh
            if meter_id is not None:
                bucket[str(meter_id)] = cap_wh
        items.append({"building_id": building_id, "room_id": room_id,
                     "meter_id": meter_id, "contract_limit_wh": cap_wh})

    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict) and not {"wh", "kwh", "mwh", "value"} & set(value.keys()):
                # {building_id: {room_id: cap}}
                for room_id, cap_value in value.items():
                    record(key, room_id, None, convert(cap_value))
            else:
                # 扁平键可能是 room/meter，也可能是 "B1:R1" 复合键。
                building_id = room_id = meter_id = None
                if ":" in str(key):
                    building_id, room_id = str(key).split(":", 1)
                elif "/" in str(key):
                    building_id, room_id = str(key).split("/", 1)
                else:
                    room_id = str(key)
                record(building_id, room_id, meter_id, convert(value))
    elif isinstance(payload, (list, tuple)):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            building_id = entry.get("building_id")
            room_id = entry.get("room_id") or entry.get("room")
            meter_id = entry.get("meter_id")
            raw_value = None
            for field in ("contract_limit", "contract_limit_kwh", "limit", "cap",
                          "contract_cap", "value", "contract_limit_wh"):
                if entry.get(field) is not None:
                    raw_value = entry[field]
                    if field.endswith("_wh"):
                        raw_value = {"wh": raw_value}
                    elif field.endswith("_kwh"):
                        raw_value = {"kwh": raw_value}
                    break
            record(building_id, room_id, meter_id, convert(raw_value))

    # calculate_rows 同时认识 nested 与 flat；用 nested 形式传入。
    merged = dict(flat)
    for building_id, rooms in nested.items():
        merged[building_id] = dict(rooms)
    return {"flat": flat, "nested": nested, "items": items, "mapping": merged}
