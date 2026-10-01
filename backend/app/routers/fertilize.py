"""施肥作业接口：填报、确认、改交、补施与看板。

当班人身份通过请求头传入（前端会话统一带上）：
X-Operator-Name / X-Operator-Role / X-Operator-Group，值做了 URL 编码以兼容中文。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.fertilize import FertilizeService

router = APIRouter(prefix="/api/fertilize", tags=["施肥作业"])

service = FertilizeService()

LIST_FIELDS = ["施肥编号", "施肥区域", "肥料类型", "施肥量", "施肥面积", "所属班组", "填报人", "经手人", "确认人", "施肥状态"]
STATUSES = ["待确认", "已确认", "过量", "已补施"]

DEFAULT_OPERATOR = {"name": "值班管理员", "role": "填报人", "group": "一班"}


def current_operator(
    x_operator_name: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
    x_operator_group: str | None = Header(default=None),
) -> dict[str, str]:
    """从请求头还原当班人；缺省时按只写不确认的填报人兜底。"""
    name = unquote(x_operator_name).strip() if x_operator_name else ""
    role = unquote(x_operator_role).strip() if x_operator_role else ""
    group = unquote(x_operator_group).strip() if x_operator_group else ""
    return {
        "name": name or DEFAULT_OPERATOR["name"],
        "role": role or DEFAULT_OPERATOR["role"],
        "group": group or DEFAULT_OPERATOR["group"],
    }


Operator = Depends(current_operator)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按施肥编号检索"),
    status: str | None = Query(default=None, description="待确认、已确认、过量、已补施"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按施肥编号与状态过滤施肥作业列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/board")
def board() -> dict[str, Any]:
    """施肥看板：已施面积随明细实时重算，经手人一览与列表同源。"""
    return service.board()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出施肥作业清单：返回当前全量数据，经手人与列表口径一致。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fertilize", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条施肥记录明细（含经手记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"施肥记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, operator: dict[str, str] = Operator) -> ActionResult:
    """填报施肥记录：同一片地重复提交只认第一次，缺字段时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload, operator: dict[str, str] = Operator) -> ActionResult:
    """修改施肥记录：只读岗不能碰肥料类型与施肥量；已确认的记录以组长确认为准。"""
    entry, message = service.update_entry(entry_id, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/confirm", response_model=ActionResult)
def confirm_entry(entry_id: int, payload: EntryPayload, operator: dict[str, str] = Operator) -> ActionResult:
    """确认施肥记录：只有本组组长能确认，越权当场挡下并说明缺的是哪个角色。"""
    entry, message = service.confirm_entry(entry_id, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/transfer", response_model=ActionResult)
def transfer_entry(entry_id: int, payload: EntryPayload, operator: dict[str, str] = Operator) -> ActionResult:
    """改交经手人：经手人随记录留痕，改交必留转移记录。"""
    entry, message = service.transfer_entry(entry_id, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload, operator: dict[str, str] = Operator) -> ActionResult:
    """执行登记过量、补施肥料；补施重复提交会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
