"""命名兼容：出账（posting）入口。"""
from app.review.issuance import (  # noqa: F401
    issue_all as post_all,
    issue_building as post_building,
    issue_building,
    list_issuances as list_postings,
    serialize_issuance,
)


def create_posting(store, run_id, building_id, **kwargs):
    return issue_building(store, run_id, building_id, **kwargs)
