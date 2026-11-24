import json
from decimal import Decimal
from pathlib import Path

from app.catalog import SPEC
from app.domain.calculate import calculate_rows
from app.domain.contracts import normalize_contract_limits
from app.domain.decision import decide_rows
from app.domain.prepare import prepare_rows
from app.intake.service import load
from app.reconcile.ledger import build_ledger


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _stage(name):
    return SPEC["stages"].index(name) + 1


RESULT_KEYS = {
    "label", "building_id", "verdict", "reason", "metric", "limit", "status", "state",
    "breakdown", "problem", "issuable", "can_issue", "issue_blocker", "issue_status",
    "shortfall", "shortfall_mwh", "shortfall_wh", "gap", "gap_mwh", "difference",
    "pending_amount", "pending_mwh", "pending_verification", "balanced", "meter_balanced",
    "reconcilable", "cap_applied", "has_contract_limits", "capped_rooms",
    "common_mwh", "common_wh", "allocated_common_mwh", "allocated",
}


def pipeline(profile="dirty", path=None, upto="证据交付", contract_limits=None,
             limits=None, caps=None, limits_unit=None, unit=None, month=None, period=None):
    raw_limits = contract_limits if contract_limits is not None else (limits if limits is not None else caps)
    if raw_limits in ({}, [], ""):
        raw_limits = None
    normalized_limits = normalize_contract_limits(raw_limits, limits_unit or unit)
    limit_mapping = normalized_limits["mapping"] if raw_limits is not None else None
    target_period = month or period

    intake = load(profile, path)
    prepared, prepare_issues = [], []
    results = []
    ledger = None
    if _stage(upto) >= 2:
        prepared, prepare_issues = prepare_rows(intake["rows"])
    if _stage(upto) >= 3:
        results = calculate_rows(prepared, limits=limit_mapping)
    if _stage(upto) >= 4:
        results = decide_rows(results)
    if _stage(upto) >= 5:
        ledger = build_ledger(intake, prepared, prepare_issues, results)
    intake["counts"]["prepared"] = len(prepared)
    intake["counts"]["computed"] = len(results)
    issues = intake["issues"] + prepare_issues
    summary = {"PASS": 0, "REVIEW": 0, "REJECT": 0}
    for item in results:
        summary[item.get("verdict", "REVIEW")] = summary.get(item.get("verdict", "REVIEW"), 0) + 1
    chart_field = {"0840": "rolling", "0849": "mean", "0850": "settlement_cents"}.get(SPEC["code"], "metric")
    chart = [{"label": item.get("label", item.get(SPEC["key"], "")),
              "value": float(item.get(chart_field) or 0),
              "limit": float(item.get("limit") or 0)}
             for item in results[:12]]
    rows = []
    raw_stage = _stage(upto) <= 2
    if raw_stage:
        stage_rows = intake["rows"] if _stage(upto) == 1 else prepared
        rows = [{key: item.get(key) for key in SPEC["columns"]} for item in stage_rows[:18]]
    else:
        # 结果行保留完整计算/上限/签发字段，表格前端只挑选认识的列渲染。
        rows = [dict(item) for item in results[:18]]

    building_results = jsonable(results)
    shortfall_total = sum(int(item.get("shortfall", 0) or 0) for item in results)
    source = {"profile": profile, "filename": Path(intake["path"]).name, "sha256": intake["sha256"]}
    base_key_material = SPEC["code"] + profile + intake["sha256"] + SPEC["rule"]
    if raw_limits is None and not target_period:
        # 未录入合同上限时保持与原批次键完全一致。
        key_material = base_key_material
    else:
        limit_fingerprint = json.dumps(normalized_limits["items"], ensure_ascii=False, sort_keys=True)
        key_material = base_key_material + limit_fingerprint + str(target_period or "")
    run_key = __import__("hashlib").sha256(key_material.encode("utf-8")).hexdigest()[:24]
    payload = {
        "project": SPEC["code"] + " " + SPEC["name"],
        "rule": SPEC["rule_short"],
        "profile": profile,
        "period": target_period,
        "month": target_period,
        "source": source,
        "counts": intake["counts"],
        "issues": issues[:60],
        "rows": rows,
        "row_kind": "source" if raw_stage else "result",
        "chart": chart,
        "summary": summary,
        "ledger": ledger,
        # 各楼栋完整计算/判定结果与签发结果
        "results": building_results,
        "buildings": building_results,
        "building_results": building_results,
        "contract_limits": normalized_limits["items"],
        "shortfall_total": shortfall_total,
        "pending_total": shortfall_total,
        "shortfall_total_wh": shortfall_total,
        "issuances": [],
        "postings": [],
        "stages": [{"id": "intake", "name": SPEC["stages"][0]},
                   {"id": "prepare", "name": SPEC["stages"][1]},
                   {"id": "calculate", "name": SPEC["stages"][2]},
                   {"id": "decision", "name": SPEC["stages"][3]},
                   {"id": "reconcile", "name": SPEC["stages"][4]}],
        "run_key": run_key,
    }
    return jsonable(payload)
