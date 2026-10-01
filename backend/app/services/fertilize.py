"""施肥作业业务规则：填报、确认、改交、补施与看板口径都收在这里。

岗位分工：填报人只写不确认，确认归本组组长，只读岗不能碰肥料类型与施肥量。
所有写操作都在 store.lock 里完成，并发提交同一片地只落第一条。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "fertilize"

ROLE_REPORTER = "填报人"
ROLE_LEADER = "组长"
ROLE_READONLY = "只读岗"
ROLES = [ROLE_REPORTER, ROLE_LEADER, ROLE_READONLY]

STATUS_PENDING = "待确认"
STATUS_CONFIRMED = "已确认"
STATUS_OVER = "过量"
STATUS_REFILL = "已补施"
STATUS_ORDER = [STATUS_PENDING, STATUS_CONFIRMED, STATUS_OVER, STATUS_REFILL]
DONE_STATUSES = {STATUS_CONFIRMED, STATUS_REFILL}  # 计入看板已施面积

REQUIRED_FIELDS = ["施肥编号", "施肥区域", "肥料类型"]
EDITABLE_FIELDS = ["施肥区域", "肥料类型", "施肥量", "施肥面积", "施肥方式", "施肥日期", "作业人员"]
READONLY_LOCKED_FIELDS = ["肥料类型", "施肥量"]
CONFIRM_FIELDS = ["肥料类型", "施肥量", "施肥面积", "施肥方式", "施肥日期", "作业人员"]
ACTION_RULES = {"登记过量": STATUS_OVER, "补施肥料": STATUS_REFILL}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _area(value: Any) -> float:
    try:
        return float(str(value).replace("亩", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _trace(kind: str, old: str, new: str, operator: dict[str, str], note: str) -> dict[str, str]:
    return {
        "时间": _now(),
        "类型": kind,
        "原经手人": old,
        "新经手人": new,
        "操作人": operator["name"],
        "说明": note,
    }


class FertilizeService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("施肥编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any], operator: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        role = operator["role"]
        if role == ROLE_READONLY:
            return None, f"当前岗位是「{ROLE_READONLY}」，只能查看，填报施肥需要「{ROLE_REPORTER}」角色"
        if role not in ROLES:
            return None, f"岗位「{role}」未登记，可填报的岗位：{'、'.join(ROLES)}"
        missing = [field for field in REQUIRED_FIELDS if not _text(values.get(field))]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        plot = _text(values.get("施肥区域"))
        with store.lock:
            rows = store.rows(MODULE)
            for row in rows:
                if _text(row.get("施肥区域")) == plot:
                    return None, f"施肥区域「{plot}」已有记录（编号 {row.get('施肥编号')}），同一片地重复提交只认第一次"
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in REQUIRED_FIELDS + EDITABLE_FIELDS:
                if field in values:
                    entry[field] = values[field]
            entry["status"] = STATUS_PENDING
            entry["pending"] = True
            entry["abnormal"] = False
            entry["施肥状态"] = STATUS_PENDING
            entry["所属班组"] = operator["group"]
            entry["填报人"] = operator["name"]
            entry["经手人"] = operator["name"]
            entry["确认人"] = ""
            entry["确认时间"] = ""
            entry["经手记录"] = [_trace("登记", "", operator["name"], operator, "填报登记，待本组组长确认")]
            rows.append(entry)
        return entry, "施肥记录已登记，待本组组长确认"

    def update_entry(self, entry_id: int, values: dict[str, Any], operator: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施肥记录 {entry_id} 不存在或已归档"
        if operator["role"] == ROLE_READONLY:
            touched = [
                field for field in READONLY_LOCKED_FIELDS
                if field in values and _text(values.get(field)) != _text(entry.get(field))
            ]
            if touched:
                return None, f"「{ROLE_READONLY}」不能修改{'、'.join(touched)}，需要「{ROLE_REPORTER}」或「{ROLE_LEADER}」角色"
        if entry.get("status") in DONE_STATUSES and not self._is_own_leader(entry, operator):
            return None, f"记录状态为「{entry.get('status')}」，填报人与组长冲突时以组长的确认为准，如需调整请联系本组组长"
        with store.lock:
            if "施肥区域" in values:
                plot = _text(values.get("施肥区域"))
                for row in store.rows(MODULE):
                    if row is not entry and _text(row.get("施肥区域")) == plot:
                        return None, f"施肥区域「{plot}」已有记录（编号 {row.get('施肥编号')}），同一片地只认一条记录"
            changed = []
            for field in EDITABLE_FIELDS:
                if field in values and _text(values.get(field)) != _text(entry.get(field)):
                    entry[field] = values[field]
                    changed.append(field)
            if changed:
                handler = _text(entry.get("经手人"))
                entry.setdefault("经手记录", []).append(
                    _trace("修改", handler, handler, operator, f"修改字段：{'、'.join(changed)}")
                )
        if not changed:
            return entry, "没有字段发生变化"
        return entry, "施肥记录已更新"

    def confirm_entry(self, entry_id: int, values: dict[str, Any], operator: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施肥记录 {entry_id} 不存在或已归档"
        if operator["role"] != ROLE_LEADER:
            return None, f"当前岗位是「{operator['role']}」，确认施肥需要「{ROLE_LEADER}」角色"
        group = _text(entry.get("所属班组"))
        if _text(operator["group"]) != group:
            return None, f"记录属于「{group}」，需要该班组的组长确认，当前是「{operator['group']}」组长"
        status = entry.get("status")
        if status == STATUS_CONFIRMED:
            return None, f"记录已由「{entry.get('确认人')}」于 {entry.get('确认时间')} 确认，重复确认已被拦截"
        if status != STATUS_PENDING:
            return None, f"记录当前状态是「{status}」，只有「{STATUS_PENDING}」的记录可以确认"
        with store.lock:
            corrections = []
            for field in CONFIRM_FIELDS:
                if field in values and _text(values.get(field)) != _text(entry.get(field)):
                    entry[field] = values[field]
                    corrections.append(field)
            entry["status"] = STATUS_CONFIRMED
            entry["施肥状态"] = STATUS_CONFIRMED
            entry["pending"] = False
            entry["确认人"] = operator["name"]
            entry["确认时间"] = _now()
            note = "组长确认"
            if corrections:
                note += f"，与填报冲突处以组长为准：{'、'.join(corrections)}"
            handler = _text(entry.get("经手人"))
            entry.setdefault("经手记录", []).append(_trace("确认", handler, handler, operator, note))
        return entry, "施肥记录已确认"

    def transfer_entry(self, entry_id: int, values: dict[str, Any], operator: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施肥记录 {entry_id} 不存在或已归档"
        if operator["role"] == ROLE_READONLY:
            return None, f"「{ROLE_READONLY}」只能查看，不能改交经手人"
        target = _text(values.get("target"))
        if not target:
            return None, "新经手人不能为空"
        current = _text(entry.get("经手人"))
        if target == current:
            return None, f"经手人已经是「{target}」，无需改交"
        note = _text(values.get("note")) or "改交经手人"
        with store.lock:
            entry["经手人"] = target
            entry.setdefault("经手记录", []).append(_trace("转移", current, target, operator, note))
        return entry, f"经手人已由「{current}」改交「{target}」，转移记录已留痕"

    def run_action(self, entry_id: int, action: str, operator: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施肥记录 {entry_id} 不存在或已归档"
        if operator["role"] == ROLE_READONLY:
            return None, f"「{ROLE_READONLY}」只能查看，不能执行「{action}」"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于施肥作业可执行范围"
        status = entry.get("status")
        if action == "补施肥料":
            if status == STATUS_REFILL:
                return None, f"记录已补施（{entry.get('补施时间') or '此前'}），重复提交已被拦截"
            if status == STATUS_PENDING:
                return None, f"记录还未确认，需本组组长确认后才能补施"
        if action == "登记过量" and status == STATUS_REFILL:
            return None, "记录已补施完成，不能再登记过量"
        target = ACTION_RULES[action]
        with store.lock:
            entry["status"] = target
            entry["施肥状态"] = target
            entry["pending"] = target not in DONE_STATUSES
            entry["abnormal"] = target == STATUS_OVER
            if action == "补施肥料":
                entry["补施时间"] = _now()
            handler = _text(entry.get("经手人"))
            entry.setdefault("经手记录", []).append(_trace(action, handler, handler, operator, action))
        return entry, f"施肥记录已{action}"

    def board(self) -> dict[str, Any]:
        """施肥看板：已施面积随明细实时重算，经手人与列表同源。"""
        rows = store.rows(MODULE)
        groups: dict[str, dict[str, Any]] = {}
        handlers = []
        for row in rows:
            name = _text(row.get("所属班组")) or "未分组"
            bucket = groups.setdefault(name, {"班组": name, "记录数": 0, "已施面积": 0.0, "待确认面积": 0.0})
            bucket["记录数"] += 1
            area = _area(row.get("施肥面积"))
            if row.get("status") in DONE_STATUSES:
                bucket["已施面积"] += area
            else:
                bucket["待确认面积"] += area
            handlers.append({
                "id": row.get("id"),
                "施肥编号": row.get("施肥编号"),
                "施肥区域": row.get("施肥区域"),
                "经手人": row.get("经手人"),
                "状态": row.get("status"),
            })
        group_list = sorted(groups.values(), key=lambda item: item["班组"])
        for item in group_list:
            item["已施面积"] = round(item["已施面积"], 2)
            item["待确认面积"] = round(item["待确认面积"], 2)
        return {
            "已施面积合计": round(sum(item["已施面积"] for item in group_list), 2),
            "待确认条数": sum(1 for row in rows if row.get("status") == STATUS_PENDING),
            "已确认条数": sum(1 for row in rows if row.get("status") in DONE_STATUSES),
            "异常条数": sum(1 for row in rows if row.get("abnormal")),
            "班组": group_list,
            "经手人一览": handlers,
        }

    @staticmethod
    def _is_own_leader(entry: dict[str, Any], operator: dict[str, str]) -> bool:
        return operator["role"] == ROLE_LEADER and _text(operator["group"]) == _text(entry.get("所属班组"))
