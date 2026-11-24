import json

from app.errors import DomainIssue
from app.review.policy import approval_allowed


def create_run(store, payload):
    row = store.create(payload["run_key"], payload["profile"], payload)
    return serialize(row, store=store)


def approve(store, run_id, decision, comment, expected_revision):
    row = store.get(run_id)
    if row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    payload = json.loads(row["payload"])
    if decision == "APPROVED" and not approval_allowed(payload):
        raise DomainIssue("GATE_BLOCKED", 409)
    if decision not in {"APPROVED", "HELD"}:
        raise DomainIssue("BAD_REQUEST")
    row, problem = store.review(run_id, decision, comment.strip(), expected_revision)
    if problem == "missing":
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if problem == "stale":
        raise DomainIssue("STALE_REVIEW", 409)
    if decision == "APPROVED":
        # 整批签发时，为所有对平楼栋幂等出账；重试/重复批准不会重复出账。
        from app.review.issuance import issue_all
        try:
            issue_all(store, run_id)
        except DomainIssue:
            raise
        except Exception:
            # 出账是增强能力，不把未知错误升级成复核失败
            pass
    return serialize(row, store=store)


def serialize(row, store=None):
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload.update(run_id=row["id"], status=row["status"], revision=row["revision"],
                   comment=row["comment"], created_at=row["created_at"])
    if store is not None:
        # 把各楼栋的签发结果合并进楼栋视图，并附上幂等出账记录。
        from app.review.issuance import serialize_issuance
        issuance_rows = store.list_issuances(row["id"])
        issuances = [serialize_issuance(item) for item in issuance_rows]
        payload["issuances"] = issuances
        payload["postings"] = issuances
        by_building = {item["building_id"]: item for item in issuances}
        for key in ("results", "buildings", "building_results"):
            for building in payload.get(key, []) or []:
                bid = str(building.get("building_id", building.get("label", "")))
                if bid in by_building:
                    record = by_building[bid]
                    building["issue_status"] = record["status"]
                    building["issuance_status"] = record["status"]
                    building["sign_status"] = record["status"]
                    building["issue_result"] = "ISSUED"
                    building["issuance_result"] = record
                    building["issuance"] = record
                    building["posting"] = record
                    building["issued"] = True
                    building["signed"] = True
                else:
                    pending_status = "BLOCKED" if not building.get("issuable", True) else "PENDING"
                    building.setdefault("issue_status", pending_status)
                    building.setdefault("issuance_status", pending_status)
                    building.setdefault("sign_status", pending_status)
                    building.setdefault("issue_result", pending_status)
                    building.setdefault("issued", False)
                    building.setdefault("signed", False)
    return payload
