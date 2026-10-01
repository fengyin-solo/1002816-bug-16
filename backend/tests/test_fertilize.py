"""施肥作业规则回归测试：岗位权限、重复提交、经手人留痕与看板口径。

运行：.venv/bin/python -m pytest tests/test_fertilize.py -q
"""
from __future__ import annotations

import threading
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import app
from app.store import store

client = TestClient(app)

REPORTER = {"name": "李填报", "role": "填报人", "group": "一班"}
LEADER = {"name": "赵组长", "role": "组长", "group": "一班"}
OTHER_LEADER = {"name": "钱组长", "role": "组长", "group": "二班"}
READONLY = {"name": "孙观察", "role": "只读岗", "group": "一班"}


def as_headers(operator: dict[str, str]) -> dict[str, str]:
    return {
        "X-Operator-Name": quote(operator["name"]),
        "X-Operator-Role": quote(operator["role"]),
        "X-Operator-Group": quote(operator["group"]),
    }


def create(plot: str, operator: dict[str, str] = REPORTER, **extra) -> dict:
    values = {"施肥编号": f"FERT-T-{plot}", "施肥区域": plot, "肥料类型": "复合肥", **extra}
    return client.post("/api/fertilize", json={"values": values}, headers=as_headers(operator)).json()


def test_reporter_cannot_confirm_and_message_names_missing_role() -> None:
    created = create("测试地块-填报人不能确认")
    assert created["ok"] is True
    entry_id = created["entry"]["id"]
    result = client.post(f"/api/fertilize/{entry_id}/confirm", json={"values": {}}, headers=as_headers(REPORTER)).json()
    assert result["ok"] is False
    assert "组长" in result["message"]
    assert "填报人" in result["message"]


def test_cross_group_leader_blocked_with_group_named() -> None:
    created = create("测试地块-跨组确认")
    entry_id = created["entry"]["id"]
    result = client.post(f"/api/fertilize/{entry_id}/confirm", json={"values": {}}, headers=as_headers(OTHER_LEADER)).json()
    assert result["ok"] is False
    assert "一班" in result["message"]
    assert "二班" in result["message"]


def test_leader_confirm_wins_over_reporter_values() -> None:
    created = create("测试地块-组长为准", 施肥量="30kg")
    entry_id = created["entry"]["id"]
    confirmed = client.post(
        f"/api/fertilize/{entry_id}/confirm",
        json={"values": {"施肥量": "45kg"}},
        headers=as_headers(LEADER),
    ).json()
    assert confirmed["ok"] is True
    assert confirmed["entry"]["施肥量"] == "45kg"
    assert confirmed["entry"]["确认人"] == LEADER["name"]
    assert confirmed["entry"]["status"] == "已确认"
    # 确认后填报人再改，直接被挡：以组长确认为准
    edited = client.put(
        f"/api/fertilize/{entry_id}",
        json={"values": {"施肥量": "10kg"}},
        headers=as_headers(REPORTER),
    ).json()
    assert edited["ok"] is False
    assert "组长" in edited["message"]
    after = client.get(f"/api/fertilize/{entry_id}").json()
    assert after["施肥量"] == "45kg"


def test_reconfirm_is_rejected() -> None:
    created = create("测试地块-重复确认")
    entry_id = created["entry"]["id"]
    first = client.post(f"/api/fertilize/{entry_id}/confirm", json={"values": {}}, headers=as_headers(LEADER)).json()
    assert first["ok"] is True
    second = client.post(f"/api/fertilize/{entry_id}/confirm", json={"values": {}}, headers=as_headers(LEADER)).json()
    assert second["ok"] is False
    assert "重复确认" in second["message"]


def test_readonly_cannot_touch_fertilizer_fields() -> None:
    created = create("测试地块-只读岗", 施肥量="30kg")
    entry_id = created["entry"]["id"]
    blocked = client.put(
        f"/api/fertilize/{entry_id}",
        json={"values": {"肥料类型": "尿素", "施肥量": "99kg"}},
        headers=as_headers(READONLY),
    ).json()
    assert blocked["ok"] is False
    assert "只读岗" in blocked["message"]
    assert "肥料类型" in blocked["message"] and "施肥量" in blocked["message"]
    # 只读岗未改这两个字段时可以改其他字段
    allowed = client.put(
        f"/api/fertilize/{entry_id}",
        json={"values": {"施肥方式": "沟施"}},
        headers=as_headers(READONLY),
    ).json()
    assert allowed["ok"] is True
    # 只读岗不能填报
    denied = create("测试地块-只读岗填报", operator=READONLY)
    assert denied["ok"] is False
    assert "填报人" in denied["message"]


def test_duplicate_plot_only_first_counts() -> None:
    first = create("测试地块-重复提交")
    assert first["ok"] is True
    second = create("测试地块-重复提交", operator={"name": "别人", "role": "填报人", "group": "二班"})
    assert second["ok"] is False
    assert "只认第一次" in second["message"]
    rows = [row for row in store.rows("fertilize") if row.get("施肥区域") == "测试地块-重复提交"]
    assert len(rows) == 1


def test_concurrent_create_same_plot_only_one_lands() -> None:
    plot = "测试地块-并发"
    results: list[dict] = []
    lock = threading.Lock()

    def submit(name: str) -> None:
        operator = {"name": name, "role": "填报人", "group": "一班"}
        payload = {"values": {"施肥编号": f"FERT-C-{name}", "施肥区域": plot, "肥料类型": "复合肥"}}
        result = client.post("/api/fertilize", json=payload, headers=as_headers(operator)).json()
        with lock:
            results.append(result)

    threads = [threading.Thread(target=submit, args=(f"并发员{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for result in results if result["ok"]) == 1
    assert sum(1 for result in results if not result["ok"]) == 7
    rows = [row for row in store.rows("fertilize") if row.get("施肥区域") == plot]
    assert len(rows) == 1


def test_refill_is_idempotent() -> None:
    created = create("测试地块-补施")
    entry_id = created["entry"]["id"]
    client.post(f"/api/fertilize/{entry_id}/confirm", json={"values": {}}, headers=as_headers(LEADER))
    client.post(f"/api/fertilize/{entry_id}/actions", json={"values": {"action": "登记过量"}}, headers=as_headers(REPORTER))
    first = client.post(f"/api/fertilize/{entry_id}/actions", json={"values": {"action": "补施肥料"}}, headers=as_headers(REPORTER)).json()
    assert first["ok"] is True
    assert first["entry"]["status"] == "已补施"
    second = client.post(f"/api/fertilize/{entry_id}/actions", json={"values": {"action": "补施肥料"}}, headers=as_headers(REPORTER)).json()
    assert second["ok"] is False
    assert "重复提交" in second["message"]


def test_transfer_leaves_trail_and_all_entries_agree() -> None:
    created = create("测试地块-改交")
    entry_id = created["entry"]["id"]
    transferred = client.post(
        f"/api/fertilize/{entry_id}/transfer",
        json={"values": {"target": "周航", "note": "李填报请假"}},
        headers=as_headers(REPORTER),
    ).json()
    assert transferred["ok"] is True
    assert transferred["entry"]["经手人"] == "周航"
    trail = transferred["entry"]["经手记录"]
    assert any(item["类型"] == "转移" and item["新经手人"] == "周航" for item in trail)
    # 详情、看板、导出三个入口读到的经手人必须一致
    detail = client.get(f"/api/fertilize/{entry_id}").json()
    assert detail["经手人"] == "周航"
    board = client.get("/api/fertilize/board").json()
    board_row = next(item for item in board["经手人一览"] if item["id"] == entry_id)
    assert board_row["经手人"] == "周航"
    exported = client.get("/api/fertilize/export").json()
    export_row = next(item for item in exported["items"] if item["id"] == entry_id)
    assert export_row["经手人"] == "周航"
    # 改交给同一个人没有意义
    same = client.post(
        f"/api/fertilize/{entry_id}/transfer",
        json={"values": {"target": "周航"}},
        headers=as_headers(REPORTER),
    ).json()
    assert same["ok"] is False


def test_board_area_recalculates_from_details() -> None:
    before = client.get("/api/fertilize/board").json()
    created = create("测试地块-看板", 施肥面积=10)
    entry_id = created["entry"]["id"]
    pending_board = client.get("/api/fertilize/board").json()
    assert pending_board["已施面积合计"] == before["已施面积合计"]
    client.post(f"/api/fertilize/{entry_id}/confirm", json={"values": {}}, headers=as_headers(LEADER))
    after = client.get("/api/fertilize/board").json()
    assert after["已施面积合计"] == round(before["已施面积合计"] + 10, 2)


def test_no_store_header_on_api() -> None:
    response = client.get("/api/fertilize")
    assert response.headers.get("Cache-Control") == "no-store"
