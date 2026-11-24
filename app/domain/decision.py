from app.domain.helpers import D


def decide_rows(items):
    for item in items:
        if item.get("problem"):
            item["verdict"] = "REJECT"
            item["reason"] = item["problem"]
        elif sum(row["total"] for row in item["allocations"]) != item["usage_mwh"] + item["common_mwh"]:
            item["verdict"] = "REJECT"
            item["reason"] = "ALLOCATION_LEAK"
        else:
            item["verdict"] = "PASS"
            item["reason"] = "METER_BALANCED"
        item.setdefault("verdict", "PASS")
        item.setdefault("reason", "OK")
    return items
