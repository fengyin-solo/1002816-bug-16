"""施肥作业业务规则：填报与确认分离、角色权限、重复提交拦截与看板口径都收在这里。"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "fertilize"

# 角色口径：填报人只写不确认，确认归本组组长，只读岗不能碰肥料类型与施肥量
ROLE_REPORTER = "填报人"
ROLE_LEADER = "组长"
ROLE_READONLY = "只读"
ROLES = (ROLE_REPORTER, ROLE_LEADER, ROLE_READONLY)

REQUIRED_FIELDS = ["施肥区域", "肥料类型", "施肥量"]
# 组长确认时可以更正、并与填报值冲突时以组长为准的字段
LEADER_OVERRIDE_FIELDS = ["肥料类型", "施肥量", "施肥面积", "施肥方式", "施肥日期"]

STATUS_PENDING = "待施肥"  # 已填报、待本组组长确认
STATUS_DONE = "已施肥"
STATUS_OVER = "过量"
STATUS_RESUPPLY = "已补施"
STATUS_ORDER = [STATUS_PENDING, STATUS_DONE, STATUS_OVER, STATUS_RESUPPLY]
# 已施面积统计口径：除待确认外都算肥料已下地
DONE_STATUSES = (STATUS_DONE, STATUS_OVER, STATUS_RESUPPLY)

ACTION_RULES = {"确认施肥": STATUS_DONE, "登记过量": STATUS_OVER, "补施肥料": STATUS_RESUPPLY}
TRANSFER_ACTION = "转交"

# 填报查重与状态流转共用一把锁：同一片地的"查了再建"必须原子化，并发提交只认第一次
_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def operator_from(values: dict[str, Any]) -> dict[str, str]:
    """从请求里取操作人上下文：姓名、角色、班组；角色缺失或不在册时按最低权限（填报人）处理。"""
    role = str(values.get("role") or "").strip()
    return {
        "name": str(values.get("operator") or "").strip() or "未署名",
        "role": role if role in ROLES else ROLE_REPORTER,
        "group": str(values.get("group") or "").strip() or "未分组",
    }


def _area(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


class FertilizeService:
    def _serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        """统一出参口径：列表、详情、导出、看板都走这里，经手人读到的永远是同一份。"""
        data = dict(row)
        data["施肥状态"] = str(row.get("status") or STATUS_PENDING)
        data.setdefault("经手人", "")
        data.setdefault("填报人", "")
        data.setdefault("所属班组", "")
        data.setdefault("确认人", "")
        data.setdefault("转移记录", [])
        return data

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        region: str | None = None,
        fertilizer: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("施肥编号", ""))]
        if region:
            rows = [row for row in rows if region in str(row.get("施肥区域", ""))]
        if fertilizer:
            rows = [row for row in rows if fertilizer in str(row.get("肥料类型", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._serialize(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        operator = operator_from(values)
        if operator["role"] == ROLE_READONLY:
            return None, "只读岗只能查看，不能登记施肥记录：肥料类型与施肥量对只读岗不可写"
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        region = str(values.get("施肥区域")).strip()
        with _lock:
            rows = store.rows(MODULE)
            for row in rows:
                if str(row.get("施肥区域", "")).strip() == region:
                    handler = row.get("经手人") or row.get("填报人") or "未知"
                    return None, (
                        f"重复提交已拦截：{region} 已由「{handler}」填报（{row.get('施肥编号')}），"
                        "同一片地只认第一次提交"
                    )
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry["施肥编号"] = str(values.get("施肥编号") or "").strip() or f"FERT-{entry['id']:04d}"
            for field in ("施肥区域", "肥料类型", "施肥量", "施肥方式", "施肥日期"):
                entry[field] = str(values.get(field) or "").strip()
            entry["施肥面积"] = _area(values.get("施肥面积"))
            entry["所属班组"] = operator["group"]
            entry["填报人"] = operator["name"]
            entry["经手人"] = operator["name"]
            entry["确认人"] = ""
            entry["转移记录"] = []
            entry["status"] = STATUS_PENDING
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return self._serialize(entry), f"施肥记录已填报（{entry['施肥编号']}），待本组组长确认"

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施肥记录 {entry_id} 不存在或已归档"
        if action == TRANSFER_ACTION:
            return self._transfer(entry, values, operator_from(values))
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于施肥作业可执行范围"
        operator = operator_from(values)
        if operator["role"] == ROLE_READONLY:
            return None, f"只读岗只能查看，不能执行「{action}」：肥料类型与施肥量对只读岗不可写"
        handler = {
            "确认施肥": self._confirm,
            "登记过量": self._mark_over,
            "补施肥料": self._resupply,
        }[action]
        return handler(entry, values, operator)

    def _confirm(
        self, entry: dict[str, Any], values: dict[str, Any], operator: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str]:
        if operator["role"] != ROLE_LEADER:
            return None, (
                f"越权确认已拦截：「确认施肥」需要「组长」角色，"
                f"当前角色为「{operator['role']}」，缺少「组长」权限"
            )
        group = str(entry.get("所属班组") or "")
        if group and operator["group"] != group:
            return None, (
                f"越权确认已拦截：该记录属于「{group}」，仅本组组长可确认，"
                f"当前身份为「{operator['group']}」组长，缺少「{group}组长」角色"
            )
        if entry.get("status") != STATUS_PENDING:
            return None, f"该记录当前状态为「{entry.get('status')}」，仅「待施肥」可确认，请勿重复确认"
        # 填报与确认不一致时，以组长的确认值为准
        corrected: list[str] = []
        with _lock:
            for field in LEADER_OVERRIDE_FIELDS:
                incoming = values.get(field)
                if incoming is None or str(incoming).strip() == "":
                    continue
                if field == "施肥面积":
                    incoming = _area(incoming)
                if entry.get(field) != incoming:
                    entry[field] = incoming
                    corrected.append(field)
            entry["status"] = STATUS_DONE
            entry["pending"] = False
            entry["确认人"] = operator["name"]
            entry["确认时间"] = _now()
        message = f"施肥记录已由{operator['group']}组长「{operator['name']}」确认"
        if corrected:
            message += f"；填报与确认不一致，已按组长确认值更新：{'、'.join(corrected)}"
        return self._serialize(entry), message

    def _mark_over(
        self, entry: dict[str, Any], values: dict[str, Any], operator: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != STATUS_DONE:
            return None, f"仅「已施肥」记录可登记过量，当前状态为「{entry.get('status')}」"
        with _lock:
            entry["status"] = STATUS_OVER
            entry["pending"] = True  # 过量后待补施
            entry["abnormal"] = True
        return self._serialize(entry), "已登记过量，待补施肥料"

    def _resupply(
        self, entry: dict[str, Any], values: dict[str, Any], operator: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status == STATUS_RESUPPLY:
            return None, "重复提交已拦截：该记录已补施，补施记录不可反复提交"
        if status != STATUS_OVER:
            return None, f"仅「过量」记录需要补施，当前状态为「{status}」"
        with _lock:
            entry["status"] = STATUS_RESUPPLY
            entry["pending"] = False
            entry["abnormal"] = False
            entry["补施人"] = operator["name"]
            entry["补施时间"] = _now()
        return self._serialize(entry), "补施肥料已登记，记录归档为已补施"

    def _transfer(
        self, entry: dict[str, Any], values: dict[str, Any], operator: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str]:
        if operator["role"] == ROLE_READONLY:
            return None, "只读岗只能查看，不能转交施肥记录"
        target = str(values.get("新经手人") or "").strip()
        if not target:
            return None, "转交需要填写「新经手人」"
        current = str(entry.get("经手人") or "")
        if target == current:
            return None, f"新经手人与当前经手人「{current}」相同，无需转交"
        is_handler = operator["name"] == current
        is_own_leader = operator["role"] == ROLE_LEADER and (
            not entry.get("所属班组") or operator["group"] == entry.get("所属班组")
        )
        if not (is_handler or is_own_leader):
            return None, (
                f"越权转交已拦截：仅当前经手人「{current}」或本组组长可转交，"
                f"当前操作人「{operator['name']}」（{operator['role']}）不具备权限"
            )
        with _lock:
            log = entry.setdefault("转移记录", [])
            log.append({
                "时间": _now(),
                "原经手人": current,
                "新经手人": target,
                "操作人": operator["name"],
                "备注": str(values.get("备注") or "").strip(),
            })
            entry["经手人"] = target
        return self._serialize(entry), f"经手人已由「{current}」转交「{target}」，转移记录已留痕（第{len(log)}次）"

    def summary(self) -> dict[str, Any]:
        """施肥看板：已施面积等指标每次都按明细重算，不落库、不缓存。"""
        rows = store.rows(MODULE)
        done_area = sum(_area(row.get("施肥面积")) for row in rows if row.get("status") in DONE_STATUSES)
        return {
            "待确认": sum(1 for row in rows if row.get("status") == STATUS_PENDING),
            "已施肥": sum(1 for row in rows if row.get("status") == STATUS_DONE),
            "过量": sum(1 for row in rows if row.get("status") == STATUS_OVER),
            "已补施": sum(1 for row in rows if row.get("status") == STATUS_RESUPPLY),
            "已施面积": round(done_area, 2),
        }
