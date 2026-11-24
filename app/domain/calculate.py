from datetime import date, timedelta
from app.catalog import SPEC
from app.domain.helpers import *  # noqa: F401,F403


def calculate_rows(items):
    out = []
    rows = items
    buildings = {}
    for item in items:
        buildings.setdefault(item["building_id"], []).append(item)
    for building_id, rooms in buildings.items():
        usage = sum(room["usage_mwh"] for room in rooms)
        common = rooms[0]["main_mwh"] - usage
        areas = [int(room["area_m2"] * 100) for room in rooms]
        shares = largest_remainder(max(0, common), areas)
        problem = None if common >= 0 else "MAIN_UNDER_ROOMS"
        allocations = []
        for room, share in zip(rooms, shares):
            allocations.append({"room": room["room_id"], "usage": room["usage_mwh"], "shared": share, "total": room["usage_mwh"] + share})
        out.append({"label": building_id, "main_kwh": D(str(rooms[0]["main_mwh"] / 1000), "CALC"),
                    "usage_mwh": usage, "common_mwh": max(0, common), "allocations": allocations,
                    "breakdown": [f'{row["room"]} · 分表 {row["usage"]} Wh · 公摊 {row["shared"]} Wh'
                                  for row in allocations],
                    "problem": problem, "metric": D(str(rooms[0]["main_mwh"] / 1000), "CALC"),
                    "limit": D(str((usage + max(0, common)) / 1000), "LIMIT")})
    for item in out:
        item.setdefault("label", str(item.get(SPEC["key"], "")))
    return out
