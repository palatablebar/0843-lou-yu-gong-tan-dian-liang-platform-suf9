def approval_allowed(payload):
    return int(payload["summary"].get("REJECT", 0)) == 0


def building_approval_allowed(building):
    """单栋签发闸门：无阻断判定、无留待核短差。"""
    if not isinstance(building, dict):
        return False
    if building.get("issuable") is False or building.get("can_issue") is False:
        return False
    if building.get("verdict") == "REJECT":
        return False
    if building.get("problem"):
        return False
    try:
        if int(building.get("shortfall", building.get("shortfall_mwh", 0)) or 0) > 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


# 常见命名别名
can_issue = building_approval_allowed
issue_allowed = building_approval_allowed
issuance_allowed = building_approval_allowed
