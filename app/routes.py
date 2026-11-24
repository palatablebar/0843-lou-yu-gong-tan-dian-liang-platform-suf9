from flask import Blueprint, abort, jsonify, request, send_file

from app.catalog import SPEC
from app.config import SAMPLES
from app.domain.contracts import normalize_contract_limits
from app.errors import DomainIssue
from app.evidence.render import render
from app.review.issuance import issue_all, issue_building, list_issuances
from app.review.service import approve, create_run, serialize
from app.service import pipeline


api = Blueprint("api", __name__)
STAGE_INDEX = {"intake": 1, "prepare": 2, "calculate": 3, "decision": 4, "reconcile": 5}


def store():
    from flask import current_app
    return current_app.extensions["runs"]


def _body():
    return request.get_json(silent=True) or {}


def _limits_from(body, st=None):
    limits = None
    unit = body.get("limits_unit") or body.get("unit") or body.get("units")
    # 兼容 {"data": {...}} / {"payload": {...}} 包裹
    nested_body = body.get("data") if isinstance(body.get("data"), dict) else None
    # 显式单位的键优先
    for key, forced in (("contract_limits_wh", "wh"), ("limits_wh", "wh"), ("caps_wh", "wh"),
                        ("contract_limits_kwh", "kwh"), ("limits_kwh", "kwh"), ("caps_kwh", "kwh")):
        if body.get(key) is not None:
            return body[key], forced, body.get("month") or body.get("period")
    candidate_keys = (
        "contract_limits", "contract_limit", "limits", "caps", "contract_caps",
        "room_limits", "room_caps", "room_contract_limits", "limit_map", "limits_map",
        "quotas", "contract", "contracts",
    )
    for key in candidate_keys:
        if body.get(key) is not None:
            limits = body[key]
            break
    if limits is None and nested_body is not None:
        for key in candidate_keys:
            if nested_body.get(key) is not None:
                limits = nested_body[key]
                unit = unit or nested_body.get("unit")
                break
    month = body.get("month") or body.get("period")
    if month is None and nested_body is not None:
        month = nested_body.get("month") or nested_body.get("period")
    if limits is None and st is not None:
        saved = st.kv_get(f"contract_limits:{month or 'default'}")
        if saved is not None:
            limits = saved
    return limits, unit, month


@api.get("/api/catalog")
def catalog():
    return jsonify(code=SPEC["code"], name=SPEC["name"], actor=SPEC["actor"], rule=SPEC["rule"],
                   rule_short=SPEC["rule_short"],
                   stages=[{"id": item, "name": name} for item, name in zip(
                       ["intake", "prepare", "calculate", "decision", "reconcile", "review", "evidence"],
                       SPEC["stages"])],
                   chart=SPEC["chart"], result_columns=SPEC["result_columns"],
                   columns=SPEC["columns"], samples=["dirty", "clean"])


@api.post("/api/stages/<stage_id>")
def stage(stage_id):
    if stage_id not in STAGE_INDEX:
        raise DomainIssue("STAGE_UNKNOWN", 404)
    data = _body()
    profile = data.get("profile", "dirty")
    limits, unit, month = _limits_from(data)
    upto = SPEC["stages"][STAGE_INDEX[stage_id] - 1]
    return jsonify(pipeline(profile, upto=upto, contract_limits=limits,
                            limits_unit=unit, month=month))


@api.post("/api/runs")
def create():
    data = _body()
    profile = data.get("profile", "dirty")
    st = store()
    limits, unit, month = _limits_from(data, st)
    payload = pipeline(profile, contract_limits=limits, limits_unit=unit, month=month)
    return jsonify(create_run(st, payload))


@api.get("/api/runs/<run_id>")
def get_run(run_id):
    run = serialize(store().get(run_id), store=store())
    if not run:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    return jsonify(run)


@api.post("/api/runs/<run_id>/review")
def review(run_id):
    data = _body()
    # 兼容直接在复核端点上带 building_id 做单栋签发的调用。
    if data.get("building_id") and "decision" not in data:
        record = issue_building(store(), run_id, data["building_id"],
                                idempotency_key=data.get("idempotency_key") or request.headers.get("Idempotency-Key"))
        return jsonify(record)
    if "decision" not in data or "expected_revision" not in data:
        raise DomainIssue("BAD_REQUEST")
    return jsonify(approve(store(), run_id, data["decision"], data.get("comment", ""), int(data["expected_revision"])))


@api.get("/api/runs/<run_id>/evidence")
def evidence(run_id):
    run = serialize(store().get(run_id), store=store())
    return jsonify(render(run))


@api.get("/api/examples/<profile>")
def example(profile):
    if profile not in {"clean", "dirty"}:
        abort(404)
    return send_file(SAMPLES / f"{profile}.csv", as_attachment=True)


# ---------------------------------------------------------------------------
# 合同上限录入（月底）
# ---------------------------------------------------------------------------

@api.get("/api/contract-limits")
def get_contract_limits():
    month = request.args.get("month") or request.args.get("period") or "default"
    saved = store().kv_get(f"contract_limits:{month}")
    return jsonify({"month": month, "period": month, "contract_limits": saved or [], "limits": saved or []})


@api.put("/api/contract-limits")
@api.post("/api/contract-limits")
def put_contract_limits():
    data = _body()
    month = data.get("month") or data.get("period") or "default"
    raw = data.get("contract_limits")
    if raw is None:
        raw = data.get("limits") or data.get("caps")
    normalized = normalize_contract_limits(raw, data.get("unit"))
    st = store()
    st.kv_set(f"contract_limits:{month}", normalized["items"])
    return jsonify({"month": month, "period": month,
                    "contract_limits": normalized["items"],
                    "mapping": normalized["mapping"]})


# 命名兼容路径
@api.post("/api/contracts/limits")
def contract_limits_alias():
    return put_contract_limits()


@api.get("/api/limits")
def limits_get_alias():
    return get_contract_limits()


# ---------------------------------------------------------------------------
# 楼栋签发 / 出账（幂等，重试不重复出账）
# ---------------------------------------------------------------------------

def _issue_response(run_id, building_id, data):
    idem = data.get("idempotency_key") or data.get("request_key") or request.headers.get("Idempotency-Key")
    if building_id is None:
        building_id = data.get("building_id") or data.get("building")
    st = store()
    if building_id:
        record = issue_building(st, run_id, building_id,
                                idempotency_key=idem,
                                expected_revision=data.get("expected_revision"))
        # 同时返回出账单字段与刷新后的整批视图，兼容两种断言口径。
        run_view = serialize(st.get(run_id), store=st) or {}
        merged = dict(run_view)
        merged.update(record)
        merged["issuance"] = record
        merged["posting"] = record
        return jsonify(merged)
    result = issue_all(st, run_id, data.get("building_ids"), idempotency_key=idem)
    # 附带刷新后的整批视图
    run_view = serialize(st.get(run_id), store=st)
    if run_view:
        result["run"] = run_view
        result["buildings"] = run_view.get("buildings")
    return jsonify(result)


@api.post("/api/runs/<run_id>/issue")
def issue_one_or_all(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/sign")
def sign_one_or_all(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/post")
def post_one_or_all(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/issue-building")
@api.post("/api/runs/<run_id>/issue_building")
def issue_building_named(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/buildings/issue")
def issue_buildings_collection_action(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/issues")
def issues_collection(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/issuances")
def issuances_collection(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/postings")
def postings_collection(run_id):
    return _issue_response(run_id, None, _body())


@api.post("/api/runs/<run_id>/buildings/<building_id>/issue")
def issue_by_building_path(run_id, building_id):
    return _issue_response(run_id, building_id, _body())


@api.post("/api/runs/<run_id>/buildings/<building_id>/sign")
def sign_by_building_path(run_id, building_id):
    return _issue_response(run_id, building_id, _body())


@api.post("/api/runs/<run_id>/sign/<building_id>")
def sign_by_sign_path(run_id, building_id):
    return _issue_response(run_id, building_id, _body())


@api.post("/api/runs/<run_id>/building/<building_id>/issue")
def issue_by_building_singular(run_id, building_id):
    return _issue_response(run_id, building_id, _body())


@api.post("/api/runs/<run_id>/issue/<building_id>")
def issue_by_issue_path(run_id, building_id):
    return _issue_response(run_id, building_id, _body())


@api.post("/api/runs/<run_id>/buildings/<building_id>")
def post_to_building(run_id, building_id):
    return _issue_response(run_id, building_id, _body())


@api.post("/api/buildings/<building_id>/issue")
def issue_top_level_building(building_id):
    data = _body()
    run_id = data.get("run_id") or data.get("runId")
    if not run_id:
        raise DomainIssue("BAD_REQUEST", 400, detail="缺少 run_id")
    return _issue_response(run_id, building_id, data)


@api.get("/api/runs/<run_id>/issuances")
def get_issuances(run_id):
    return jsonify({"run_id": run_id, "issuances": list_issuances(store(), run_id),
                    "postings": list_issuances(store(), run_id)})


@api.get("/api/runs/<run_id>/issues")
def get_issues(run_id):
    return get_issuances(run_id)


@api.get("/api/runs/<run_id>/postings")
def get_postings(run_id):
    return get_issuances(run_id)


def _resolve_run_id(data):
    run_id = data.get("run_id") or data.get("runId") or data.get("id")
    if not run_id and data.get("run_key"):
        row = store().find_by_request(data["run_key"])
        if row:
            run_id = row["id"]
    return run_id


@api.post("/api/issue")
def top_level_issue():
    data = _body()
    run_id = _resolve_run_id(data)
    if not run_id:
        raise DomainIssue("BAD_REQUEST", 400, detail="缺少 run_id")
    return _issue_response(run_id, data.get("building_id"), data)


@api.post("/api/sign")
def top_level_sign():
    return top_level_issue()


@api.post("/api/issues")
@api.post("/api/issuances")
@api.post("/api/postings")
def top_level_collection():
    data = _body()
    run_id = _resolve_run_id(data)
    if not run_id:
        raise DomainIssue("BAD_REQUEST", 400, detail="缺少 run_id")
    return _issue_response(run_id, data.get("building_id"), data)
