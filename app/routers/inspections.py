"""实验跟踪：巡检记录（实验过程中对样品与设备巡检、检查与更换）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Equipment, ExperimentInspection, Sample, SampleOperation, Schedule, User
from ..schemas import InspectionCreate
from ..serializers import inspection_to_dict

router = APIRouter(prefix="/api/inspections", tags=["inspections"])

_ACTIONS = ("无", "更换样品", "更换设备", "报修")
_SCHEDULABLE = ("已接收", "已排期", "实验中", "已完成")


@router.get("")
def list_inspections(
    order_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    rows = (
        db.query(ExperimentInspection)
        .filter(ExperimentInspection.order_id == order_id)
        .order_by(ExperimentInspection.id.desc())
        .all()
    )
    return [inspection_to_dict(x) for x in rows]


@router.post("")
def create_inspection(
    data: InspectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    order = db.get(EntrustOrder, data.order_id)
    if order is None:
        raise HTTPException(404, "委托单不存在")
    if order.status != "实验中":
        raise HTTPException(400, "实验未在进行中，暂不能记录巡检")
    if data.sample_condition not in ("正常", "异常"):
        raise HTTPException(400, "样品状况必须为 正常/异常")
    if data.equipment_condition not in ("正常", "异常"):
        raise HTTPException(400, "设备状况必须为 正常/异常")
    if data.action not in _ACTIONS:
        raise HTTPException(400, "处理措施必须为 无/更换样品/更换设备/报修")

    detail = ""
    schedule = None
    if data.action in ("更换样品", "更换设备"):
        if data.schedule_id is None:
            raise HTTPException(400, "更换样品/设备需选择目标排期（测试位）")
        schedule = db.get(Schedule, data.schedule_id)
        if schedule is None or schedule.order_id != order.id:
            raise HTTPException(400, "所选排期不属于该委托单")

    if data.action == "更换样品":
        old = schedule.sample
        if old is None:
            raise HTTPException(400, "该排期未绑定样机")
        if data.replacement_sample_id is None:
            raise HTTPException(400, "请选择替换样机")
        new = db.get(Sample, data.replacement_sample_id)
        if new is None:
            raise HTTPException(404, "替换样机不存在")
        if new.id == old.id:
            raise HTTPException(400, "替换样机不能与原样机相同")
        if new.status not in _SCHEDULABLE:
            raise HTTPException(400, f"替换样机当前状态（{new.status}）不可排期")
        dup = db.query(Schedule).filter(Schedule.order_id == order.id, Schedule.sample_id == new.id).first()
        if dup is not None:
            raise HTTPException(400, f"样机 {new.sample_no} 已在本委托单排期，不可重复使用")
        # 换出本条排期前统计旧样机剩余未完成排期（autoflush=False，须先于变更统计）
        old_remaining = (
            db.query(Schedule)
            .filter(Schedule.sample_id == old.id, Schedule.status != "已完成")
            .count()
        )
        detail = f"样品 {old.sample_no}（SN {old.sn or '-'}）→ {new.sample_no}（SN {new.sn or '-'}）"
        schedule.sample_id = new.id
        new.status = "实验中"
        db.add(SampleOperation(sample_id=new.id, action="巡检更换", operator=user.name,
                               remark=f"顶替进入 {order.experiment_no or order.order_no}（{detail}）"))
        if old.status == "实验中" and old_remaining <= 1:
            old.status = "已接收"
            db.add(SampleOperation(sample_id=old.id, action="巡检更换", operator=user.name,
                                   remark="被替换出实验，回退已接收"))
    elif data.action == "更换设备":
        old_eq = schedule.equipment
        if old_eq is None:
            raise HTTPException(400, "该排期未绑定设备")
        if data.replacement_equipment_id is None:
            raise HTTPException(400, "请选择替换设备")
        new_eq = db.get(Equipment, data.replacement_equipment_id)
        if new_eq is None:
            raise HTTPException(404, "替换设备不存在")
        if new_eq.status in ("停用", "报废"):
            raise HTTPException(400, "替换设备已停用/报废，不可使用")
        if new_eq.id == old_eq.id:
            raise HTTPException(400, "替换设备不能与原设备相同")
        detail = f"设备 {old_eq.name} → {new_eq.name}"
        schedule.equipment_id = new_eq.id
    elif data.action == "报修":
        detail = data.remark or "设备报修"

    insp = ExperimentInspection(
        order_id=order.id, operator=user.name,
        inspect_at=data.inspect_at or datetime.now(),
        sample_condition=data.sample_condition,
        equipment_condition=data.equipment_condition,
        action=data.action, action_detail=detail, remark=data.remark,
    )
    db.add(insp)
    log(db, user, "实验巡检", "order", order.id,
        f"{order.experiment_no or order.order_no} {data.action} {detail}")
    db.commit()
    db.refresh(insp)
    return inspection_to_dict(insp)
