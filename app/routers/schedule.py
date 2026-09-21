"""实验排期：为样品选择设备、预估用时，生成排期计划。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Sample, SampleOperation, Schedule, User
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
    """排期仅做「委托单 + 样品」分配；实验员/设备/用时/时间留到「实验开始」时填写。"""
    sample = db.get(Sample, data.sample_id)
    if sample is None:
        raise HTTPException(404, "样品不存在")

    # 样品池样品（未绑单）需指定目标委托单；不再改写 sample.order_id，保留样机复用能力
    order_id = sample.order_id or data.order_id
    if order_id is None:
        raise HTTPException(400, "样品池样品排期需指定目标委托单")
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "目标委托单不存在")
    if order.status not in ("已审核", "已排期"):
        raise HTTPException(400, "目标委托单状态不可排期")

    # 已排计划数达到需求数量后不再允许继续排期（可增量逐条排，但不得超过需求数量）
    scheduled_count = db.query(Schedule).filter(Schedule.order_id == order.id).count()
    if scheduled_count >= order.sample_count:
        raise HTTPException(400, f"该委托单已排满需求数量（{order.sample_count}），无法继续排期")

    if sample.status not in ("已接收", "已排期", "实验中", "已完成"):
        raise HTTPException(400, f"样品当前状态（{sample.status}）不可排期")

    if data.plan_start is None:
        raise HTTPException(400, "预计开始时间必填")
    if data.plan_end is None:
        raise HTTPException(400, "预计完成时间必填")
    if data.plan_end <= data.plan_start:
        raise HTTPException(400, "预计完成时间必须晚于预计开始时间")

    # 同一委托单内一台样机只允许一条排期（跨单复用不受限）
    dup = db.query(Schedule).filter(Schedule.order_id == order.id, Schedule.sample_id == sample.id).first()
    if dup is not None:
        raise HTTPException(400, f"样机 {sample.sample_no} 已在本委托单排期，不可重复排期")

    schedule = Schedule(order_id=order.id, sample_id=sample.id, plan_start=data.plan_start,
                        plan_end=data.plan_end, sample_prev_status=sample.status, status="已排期")
    db.add(schedule)

    # 空闲（已接收/已完成）样机排期后进入「已排期」；已在「已排期/实验中」的保持不变（复用）
    if sample.status in ("已接收", "已完成"):
        sample.status = "已排期"
    db.add(SampleOperation(sample_id=sample.id, action="排期", operator=user.name,
                           remark=f"排期至 {order.experiment_no or order.order_no}"))

    # 委托单进入已排期
    if order and order.status == "已审核":
        order.status = "已排期"

    log(db, user, "排期", "schedule", schedule.id, f"{sample.sample_no}")
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
    prev_status = schedule.sample_prev_status or ""
    log(db, user, "删除排期", "schedule", schedule.id, schedule.sample.sample_no if schedule.sample else "")
    db.delete(schedule)
    db.flush()  # autoflush=False，需显式 flush 让后续 count 反映删除

    # 样品：若无剩余「活跃」排期（已排期/实验中），回退到排期前的状态（已接收 / 已完成）；
    # 历史「已完成」排期不应阻止回退，否则复用过的样机会卡在「已排期」。
    sample = db.get(Sample, sample_id)
    if sample is not None and sample.status == "已排期":
        active = db.query(Schedule).filter(
            Schedule.sample_id == sample_id, Schedule.status.in_(("已排期", "实验中"))
        ).count()
        if active == 0:
            rollback_to = prev_status if prev_status in ("已接收", "已完成") else "已接收"
            sample.status = rollback_to
            db.add(SampleOperation(sample_id=sample_id, action="取消排期", operator=user.name, remark=f"排期已删除，样品回退{rollback_to}"))
    db.add(SampleOperation(sample_id=sample_id, action="删除排期", operator=user.name))

    # 委托单：若再无任何排期，回退「已排期」→「已审核」
    order = db.get(EntrustOrder, order_id)
    if order is not None and order.status == "已排期":
        remaining = db.query(Schedule).filter(Schedule.order_id == order_id).count()
        if remaining == 0:
            order.status = "已审核"

    db.commit()
    return {"message": "删除成功"}
