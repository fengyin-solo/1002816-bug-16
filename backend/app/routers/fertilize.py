"""施肥作业接口：填报与确认分离——填报人只写不确认，确认归本组组长。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.fertilize import FertilizeService

router = APIRouter(prefix="/api/fertilize", tags=["施肥作业"])

service = FertilizeService()

LIST_FIELDS = ["施肥编号", "施肥区域", "肥料类型", "施肥量", "施肥面积", "所属班组", "填报人", "经手人", "确认人", "施肥状态"]
STATUSES = ["待施肥", "已施肥", "过量", "已补施"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按施肥编号检索"),
    region: str | None = Query(default=None, description="按施肥区域检索"),
    fertilizer: str | None = Query(default=None, description="按肥料类型检索"),
    status: str | None = Query(default=None, description="待施肥、已施肥、过量、已补施"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、区域、肥料类型与状态过滤施肥列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, region=region, fertilizer=fertilizer, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """施肥看板：已施面积随明细实时重算，与列表同源。"""
    return service.summary()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出施肥作业清单：与列表同一序列化口径，经手人保持一致。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fertilize", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条施肥记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"施肥记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """填报施肥记录：同一片地重复提交只认第一次；只读岗不能登记。"""
    entry, message = service.create_entry(payload.values)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行确认施肥、登记过量、补施肥料、转交；越权与重复提交当场拦下并说明缺哪个角色。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    return ActionResult(ok=entry is not None, message=message, entry=entry)
