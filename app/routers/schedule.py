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

    # 样品池样品（未绑单）需指定目标委托单并完成绑定
    order = db.get(EntrustOrder, sample.order_id) if sample.order_id else None
    if sample.order_id is None:
        if not data.order_id:
            raise HTTPException(400, "样品池样品排期需指定目标委托单")
        order = db.get(EntrustOrder, data.order_id)
        if order is None:
            raise HTTPException(404, "目标委托单不存在")
        if order.status not in ("已审核", "已排期", "实验中"):
            raise HTTPException(400, "目标委托单状态不可排期")
        sample.order_id = order.id

    if sample.status not in ("已接收",):
        raise HTTPException(400, f"样品当前状态（{sample.status}）不可排期")

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
    sample.status = "已排期"
    db.add(SampleOperation(sample_id=sample.id, action="排期", operator=user.name,
                           remark=f"排期至 {equipment.name}，用时 {total} 小时"))

    # 委托单进入已排期
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
    if schedule.status != "已排期":
        raise HTTPException(400, "仅「已排期」的排期可删除")
    sample_id = schedule.sample_id
    order_id = schedule.order_id
    log(db, user, "删除排期", "schedule", schedule.id, schedule.sample.sample_no if schedule.sample else "")
    db.delete(schedule)
    db.flush()  # autoflush=False，需显式 flush 让后续 count 反映删除

    # 样品：若无剩余排期，回退「已排期」→「已接收」
    sample = db.get(Sample, sample_id)
    if sample is not None and sample.status == "已排期":
        remaining = db.query(Schedule).filter(Schedule.sample_id == sample_id).count()
        if remaining == 0:
            sample.status = "已接收"
            db.add(SampleOperation(sample_id=sample_id, action="取消排期", operator=user.name, remark="排期已删除，样品回退已接收"))
    db.add(SampleOperation(sample_id=sample_id, action="删除排期", operator=user.name))

    # 委托单：若再无任何排期，回退「已排期」→「已审核」
    order = db.get(EntrustOrder, order_id)
    if order is not None and order.status == "已排期":
        remaining = db.query(Schedule).filter(Schedule.order_id == order_id).count()
        if remaining == 0:
            order.status = "已审核"

    db.commit()
    return {"message": "删除成功"}
