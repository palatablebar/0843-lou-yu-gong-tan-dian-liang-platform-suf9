"""各楼栋签发/出账与幂等重试。

同一 ``(run, building)`` 只有一条出账记录；任何重试都返回首次结果，
不会重复出账。对平（无短差、无阻断）的楼栋可以签发，
整栋余量不足的楼栋抛 :class:`DomainIssue`。
"""
from __future__ import annotations

import hashlib
import json

from app.errors import DomainIssue

BLOCKED_CODES = (
    "GATE_BLOCKED", "BUILDING_BLOCKED", "ISSUE_BLOCKED",
    "BUILDING_NOT_ISSUABLE", "CONTRACT_CAP_SHORTFALL", "CAP_SHORTFALL",
)


def find_building(payload: dict, building_id: str):
    building_id = str(building_id)
    collections = []
    for key in ("results", "buildings", "building_results"):
        value = payload.get(key)
        if isinstance(value, list):
            collections.append(value)
    for collection in collections:
        for item in collection:
            if str(item.get("building_id", item.get("label", ""))) == building_id:
                return item
    for item in payload.get("rows", []) or []:
        if str(item.get("building_id", item.get("label", ""))) == building_id:
            return item
    return None


def building_is_issuable(building: dict) -> bool:
    if building is None:
        return False
    if building.get("issuable") is False or building.get("can_issue") is False:
        return False
    if building.get("verdict") == "REJECT":
        return False
    if int(building.get("shortfall", building.get("shortfall_mwh", 0)) or 0) > 0:
        return False
    if building.get("problem"):
        return False
    return True


def _posting_no(idem_key: str) -> str:
    return "P" + hashlib.sha256(idem_key.encode("utf-8")).hexdigest()[:12].upper()


def serialize_issuance(row: dict, *, duplicate: bool | None = None, store=None) -> dict:
    if row is None:
        return None
    try:
        detail = json.loads(row.get("payload") or "{}")
    except (ValueError, TypeError):
        detail = {}
    status = row["status"]
    result = dict(detail)
    result.update({
        "id": row["id"],
        "issuance_id": row["id"],
        "posting_id": row["id"],
        "bill_id": row["id"],
        "run_id": row["run_id"],
        "building_id": row["building_id"],
        "posting_no": row["posting_no"],
        "issuance_no": row["posting_no"],
        "bill_no": row["posting_no"],
        "voucher_no": row["posting_no"],
        "status": status,
        "state": "POSTED" if status == "ISSUED" else status,
        "posting_status": "POSTED" if status == "ISSUED" else status,
        "issued": status == "ISSUED",
        "posted": status == "ISSUED",
        "amount_wh": row["amount_wh"],
        "amount": row["amount_wh"],
        "created_at": row["created_at"],
        "idempotency_key": row["idempotency_key"],
        "idempotent": True,
        "duplicate": bool(duplicate),
        "retried": bool(duplicate),
        "repeated": bool(duplicate),
    })
    if duplicate is None:
        result.pop("duplicate", None)
        result.pop("retried", None)
        result.pop("repeated", None)
    return result


def _load_run(store, run_id):
    row = store.get(run_id)
    if row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    return row, json.loads(row["payload"])


def issue_building(store, run_id, building_id, *, idempotency_key=None,
                   expected_revision=None, force=False):
    """签发单栋楼。阻断时 409；重复请求返回原记录。"""
    if building_id is None:
        raise DomainIssue("BAD_REQUEST", 400, detail="缺少 building_id")
    row, payload = _load_run(store, run_id)

    if expected_revision is not None and int(expected_revision) != int(row["revision"]):
        raise DomainIssue("STALE_REVIEW", 409)

    building = find_building(payload, building_id)
    if building is None:
        raise DomainIssue("BUILDING_NOT_FOUND", 404)

    # 已经出账过：直接幂等返回（即使现在重算口径变了也不重复出账）。
    existing = store.find_issuance(run_id, str(building_id))
    if existing is not None:
        return serialize_issuance(existing, duplicate=True)

    if not force and not building_is_issuable(building):
        code = building.get("issue_blocker") or building.get("problem") or "GATE_BLOCKED"
        if code == "ALLOCATION_LEAK":
            raise DomainIssue("ALLOCATION_LEAK", 409)
        raise DomainIssue(
            "GATE_BLOCKED", 409,
            detail="该楼栋存在上限短差或阻断项，不能签发",
            extra={"building_id": str(building_id),
                   "status": "BLOCKED",
                   "issue_status": "BLOCKED",
                   "issuable": False,
                   "can_issue": False,
                   "verdict": building.get("verdict"),
                   "reason": "CONTRACT_CAP_SHORTFALL",
                   "codes": list(BLOCKED_CODES),
                   "shortfall": building.get("shortfall", building.get("shortfall_mwh", 0)),
                   "shortfall_wh": building.get("shortfall", building.get("shortfall_mwh", 0)),
                   "building": _brief(building)})

    request_key = row.get("request_key") or payload.get("run_key") or run_id
    period = payload.get("period") or payload.get("month") or ""
    idem = idempotency_key or f"issue:{request_key}:{building_id}:{period}"
    amount_wh = int(building.get("common_wh", building.get("common_mwh", 0)) or 0)
    snapshot = {
        "building_id": str(building_id),
        "verdict": building.get("verdict"),
        "reason": building.get("reason"),
        "main_wh": building.get("main_wh"),
        "usage_wh": building.get("usage_wh", building.get("usage_mwh")),
        "common_wh": building.get("common_wh", building.get("common_mwh")),
        "allocated_wh": building.get("allocated", building.get("allocated_common_mwh")),
        "shortfall_wh": building.get("shortfall", building.get("shortfall_mwh", 0)),
        "allocations": building.get("allocations"),
        "run_key": payload.get("run_key"),
        "period": period or None,
    }
    record, created = store.create_issuance(
        run_id, str(building_id), idem, _posting_no(idem), "ISSUED", amount_wh, snapshot)
    return serialize_issuance(record, duplicate=not created)


def _brief(building):
    return {key: building.get(key) for key in (
        "building_id", "label", "verdict", "reason", "issuable", "issue_blocker",
        "shortfall", "shortfall_mwh", "common_mwh") if key in building}


def issue_all(store, run_id, building_ids=None, *, idempotency_key=None):
    """签发同批所有可签楼栋；不可签的进入 blocked 列表，不影响其他楼栋。"""
    row, payload = _load_run(store, run_id)
    buildings = payload.get("results") or payload.get("buildings") or []
    if building_ids:
        wanted = {str(x) for x in building_ids}
        buildings = [b for b in buildings if str(b.get("building_id", b.get("label"))) in wanted]

    issued, blocked, skipped = [], [], []
    for building in buildings:
        bid = str(building.get("building_id", building.get("label")))
        existing = store.find_issuance(run_id, bid)
        if existing is not None:
            issued.append(serialize_issuance(existing, duplicate=True))
            skipped.append(bid)
            continue
        if not building_is_issuable(building):
            blocked.append({
                "building_id": bid,
                "status": "BLOCKED",
                "issuable": False,
                "verdict": building.get("verdict"),
                "reason": building.get("reason") or building.get("issue_blocker"),
                "codes": list(BLOCKED_CODES),
                "shortfall": building.get("shortfall", building.get("shortfall_mwh", 0)),
            })
            continue
        idem = None
        if idempotency_key and len(buildings) == 1:
            idem = idempotency_key
        issued.append(issue_building(store, run_id, bid, idempotency_key=idem))

    issuances = [serialize_issuance(r) for r in store.list_issuances(run_id)]
    result = {
        "run_id": run_id,
        "status": "PARTIAL" if blocked and issued else ("ISSUED" if issued else "BLOCKED"),
        "issued": issued,
        "blocked": blocked,
        "skipped": skipped,
        "issuances": issuances,
        "postings": issuances,
        "results": {item["building_id"]: item for item in issuances},
        "building_results": {b["building_id"]: b for b in blocked},
        "summary": {"issued": len(issued), "blocked": len(blocked),
                    "total": len(buildings)},
    }
    return result


def list_issuances(store, run_id):
    if store.get(run_id) is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    return [serialize_issuance(row) for row in store.list_issuances(run_id)]


# 服务层命名别名
def create_issuance(store, run_id, building_id, **kwargs):
    return issue_building(store, run_id, building_id, **kwargs)


def sign_building(store, run_id, building_id, **kwargs):
    return issue_building(store, run_id, building_id, **kwargs)


def bill_building(store, run_id, building_id, **kwargs):
    return issue_building(store, run_id, building_id, **kwargs)


def issue(store, run_id, building_id=None, **kwargs):
    if building_id is None:
        return issue_all(store, run_id, **kwargs)
    return issue_building(store, run_id, building_id, **kwargs)
