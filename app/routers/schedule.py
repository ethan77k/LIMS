"""实验排期：为样品选择设备、预估用时，生成排期计划。"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Equipment, Sample, SampleOperation, Schedule, User
from ..schemas import ScheduleCreate
from ..serializers import schedule_to_dict

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("")
def list_schedules(
    order_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = db.query(Schedule)
    if order_id:
        q = q.filter(Schedule.order_id == order_id)
    return [schedule_to_dict(s) for s in q.order_by(Schedule.id).all()]


@router.post("")
def create_schedule(
    data: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    sample = db.get(Sample, data.sample_id)
    if sample is None:
        raise HTTPException(404, "样品不存在")
    equipment = db.get(Equipment, data.equipment_id)
    if equipment is None:
        raise HTTPException(404, "设备不存在")
    if equipment.status in ("停用", "报废"):
        raise HTTPException(400, "该设备已停用/报废，不可排期")

    total = data.experiment_hours + data.transition_hours
    plan_start = data.plan_start
    plan_end = plan_start + timedelta(hours=total) if plan_start else None

    schedule = Schedule(
        order_id=sample.order_id, sample_id=sample.id, equipment_id=equipment.id,
        experiment_hours=data.experiment_hours, transition_hours=data.transition_hours,
        total_hours=total, plan_start=plan_start, plan_end=plan_end, status="已排期",
    )
    db.add(schedule)

    # 样品进入已排期
    if sample.status in ("已接收",):
        sample.status = "已排期"
    db.add(SampleOperation(sample_id=sample.id, action="排期", operator=user.name,
                           remark=f"排期至 {equipment.name}，用时 {total} 小时"))

    # 委托单进入已排期
    order = db.get(EntrustOrder, sample.order_id)
    if order and order.status == "已审核":
        order.status = "已排期"

    log(db, user, "排期", "schedule", schedule.id, f"{sample.sample_no} → {equipment.name}")
    db.commit()
    db.refresh(schedule)
    return schedule_to_dict(schedule)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "排期计划不存在")
    if schedule.status == "已完成":
        raise HTTPException(400, "已完成的排期不可删除")
    log(db, user, "删除排期", "schedule", schedule.id, schedule.sample.sample_no if schedule.sample else "")
    db.delete(schedule)
    db.add(SampleOperation(sample_id=schedule.sample_id, action="删除排期", operator=user.name))
    db.commit()
    return {"message": "删除成功"}
