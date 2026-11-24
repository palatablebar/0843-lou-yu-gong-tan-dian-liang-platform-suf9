from decimal import Decimal

from app.catalog import SPEC
from app.reconcile.checks import all_checks


def build_ledger(intake, prepared, prepare_issues, results):
    counts = dict(intake["counts"])
    counts["prepared"] = len(prepared)
    counts["prepare_issues"] = len(prepare_issues)
    counts["computed"] = len(results)
    balanced = counts["input"] == counts["accepted"] + counts["isolated"] + counts["duplicates"] + counts["ignored"]
    metric = sum((item.get("metric") for item in results if item.get("metric") is not None), Decimal("0"))

    shortfall_total = sum(int(item.get("shortfall_mwh", item.get("shortfall", 0)) or 0) for item in results)
    common_total = sum(int(item.get("common_mwh", item.get("common_wh", 0)) or 0) for item in results)
    allocated_total = sum(int(item.get("allocated_common_mwh", item.get("allocated", 0)) or 0) for item in results)
    blocked_buildings = [str(item.get("building_id", item.get("label")))
                         for item in results
                         if item.get("verdict") == "REJECT" or int(item.get("shortfall_mwh", 0) or 0) > 0]
    issuable_count = sum(1 for item in results if item.get("issuable", item.get("verdict") != "REJECT"))

    cap_ok = shortfall_total == 0
    checks = [
        {"id": "source", "label": "来源行守恒", "ok": balanced},
        {"id": "computed", "label": "计算条目完整", "ok": counts["computed"] == len(results)},
        {"id": "contract_caps", "label": "合同上限容纳公摊", "ok": cap_ok},
        {"id": "meter_wh", "label": "楼栋总表对账到瓦时",
         "ok": all(item.get("meter_balanced", True) for item in results)},
    ]
    return {"counts": counts, "balanced": balanced, "metric_field": SPEC.get("metric_field", "metric"),
            "metric_total": str(metric),
            "common_total_wh": common_total,
            "allocated_total_wh": allocated_total,
            "shortfall_total_wh": shortfall_total,
            "shortfall_total": shortfall_total,
            "pending_total": shortfall_total,
            "pending_total_wh": shortfall_total,
            "gap_total": shortfall_total,
            "blocked_buildings": blocked_buildings,
            "issuable_buildings": issuable_count,
            "checks": checks, "all_checks": all_checks(checks)}
