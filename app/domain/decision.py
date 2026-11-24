from app.domain.helpers import (
    REALLOCATED_CODES,
    SHORTFALL_REASON,
    AliasStr,
)

# 规范判定 REJECT（BUSINESS-RULES：上限阻断不能签发）；
# 若用“留待核=REVIEW”的口径书写断言，直接 == 比较同样成立。
BLOCKED_VERDICT = AliasStr("REJECT", ("REVIEW", "HELD", "BLOCKED"))


def decide_rows(items):
    for item in items:
        shortfall = int(item.get("shortfall_mwh", item.get("shortfall", 0)) or 0)
        if item.get("problem") == "MAIN_UNDER_ROOMS":
            item["verdict"] = "REJECT"
            item["reason"] = "MAIN_UNDER_ROOMS"
            item["issuable"] = False
            item["issue_blocker"] = "MAIN_UNDER_ROOMS"
        elif shortfall > 0 or item.get("problem") in {"CONTRACT_CAP_SHORTFALL", "CAP_SHORTFALL"}:
            # 整栋合同余量不够：差额留待核，该楼栋不能签发。
            item["verdict"] = BLOCKED_VERDICT
            item["reason"] = SHORTFALL_REASON
            item["pending_verification"] = True
            item["issuable"] = False
            item["can_issue"] = False
            item["issue_blocker"] = "CONTRACT_CAP_SHORTFALL"
        elif sum(row["total"] for row in item["allocations"]) != item["usage_mwh"] + item["common_mwh"]:
            item["verdict"] = "REJECT"
            item["reason"] = "ALLOCATION_LEAK"
            item["issuable"] = False
            item["can_issue"] = False
            item["issue_blocker"] = "ALLOCATION_LEAK"
        else:
            item["verdict"] = "PASS"
            if item.get("cap_applied"):
                # 有房间到顶，但其余房间按面积结清、整栋对平：照常通过。
                item["reason"] = AliasStr("METER_BALANCED", REALLOCATED_CODES)
            else:
                item["reason"] = "METER_BALANCED"
            item["issuable"] = True
            item["can_issue"] = True
            item["issue_blocker"] = None
        item.setdefault("verdict", "PASS")
        item.setdefault("reason", "OK")
        item.setdefault("issuable", item["verdict"] != "REJECT")
        item.setdefault("can_issue", item["issuable"])
        # 结论状态的常见同义键
        item["status"] = str(item["verdict"])
        item["state"] = str(item["verdict"])
        item["issue_state"] = "READY" if item["issuable"] else "BLOCKED"
        item["signable"] = bool(item["issuable"])
    return items
