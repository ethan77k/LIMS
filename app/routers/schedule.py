"""实验排期：为样品选择设备、预估用时，生成排期计划。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Equipment, Sample, SampleOperation, Schedule, User
from ..schemas import OrderBatchScheduleRequest, ScheduleCreate
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

    # 样品池样品（未绑单）需指定目标委托单；不再改写 sample.order_id，保留样机复用能力
    order_id = sample.order_id or data.order_id
    if order_id is None:
        raise HTTPException(400, "样品池样品排期需指定目标委托单")
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "目标委托单不存在")
    if order.status not in ("已审核", "已排期", "实验中"):
        raise HTTPException(400, "目标委托单状态不可排期")

    # 已排计划数达到需求数量后不再允许继续排期（可增量逐条排，但不得超过需求数量）
    scheduled_count = db.query(Schedule).filter(Schedule.order_id == order.id).count()
    if scheduled_count >= order.sample_count:
        raise HTTPException(400, f"该委托单已排满需求数量（{order.sample_count}），无法继续排期")

    if sample.status not in ("已接收", "已排期", "实验中", "已完成"):
        raise HTTPException(400, f"样品当前状态（{sample.status}）不可排期")

    if data.plan_start is None:
        raise HTTPException(400, "预计开始时间必填")

    # 实验员：不传则默认取委托单审核时指定的实验员；传了则校验角色
    experimenter_id = data.experimenter_id or order.reviewer_id
    if experimenter_id is not None:
        experimenter = db.get(User, experimenter_id)
        if experimenter is None:
            raise HTTPException(400, "指定的实验员不存在")
        if experimenter.role not in ("admin", "experimenter"):
            raise HTTPException(400, "实验员必须为实验员或管理员角色")

    # 同一委托单内一台样机只允许一条排期（跨单复用不受限）
    dup = db.query(Schedule).filter(Schedule.order_id == order.id, Schedule.sample_id == sample.id).first()
    if dup is not None:
        raise HTTPException(400, f"样机 {sample.sample_no} 已在本委托单排期，不可重复排期")

    total = data.experiment_hours + data.transition_hours
    plan_start = data.plan_start
    plan_end = plan_start + timedelta(hours=total) if plan_start else None

    schedule = Schedule(
        order_id=order.id, sample_id=sample.id, equipment_id=equipment.id,
        experimenter_id=experimenter_id,
        experiment_hours=data.experiment_hours, transition_hours=data.transition_hours,
        total_hours=total, plan_start=plan_start, plan_end=plan_end, status="已排期",
    )
    db.add(schedule)

    # 空闲（已接收/已完成）样机排期后进入「已排期」；已在「已排期/实验中」的保持不变（复用）
    if sample.status in ("已接收", "已完成"):
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


@router.post("/order/{order_id}")
def schedule_order(
    order_id: int,
    data: OrderBatchScheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """整单批量排期（样品池实物复用）：从样品池选已确认样机，按复用次数覆盖委托单需求数量，
    每个测试位生成一条排期，并自动开始实验。"""
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "委托单不存在")
    if order.status not in ("已审核", "已排期", "实验中"):
        raise HTTPException(400, f"委托单当前状态（{order.status}）不可排期")

    equipment = db.get(Equipment, data.equipment_id)
    if equipment is None:
        raise HTTPException(404, "设备不存在")
    if equipment.status != "可用":
        raise HTTPException(400, "该设备当前不可用（停用/报废/使用中），不可排期")

    assignments = [a for a in data.assignments if a.count > 0]
    if not assignments:
        raise HTTPException(400, "请至少选择一台已确认样机")

    sample_ids = [a.sample_id for a in assignments]
    if len(sample_ids) != len(set(sample_ids)):
        raise HTTPException(400, "样机重复选择，请用「复用次数」表示同一台样机承担多个测试位")

    total_positions = sum(a.count for a in assignments)
    if total_positions != order.sample_count:
        raise HTTPException(
            400,
            f"排期测试位（{total_positions}）与委托单需求数量（{order.sample_count}）不一致，请调整复用次数",
        )

    total = data.experiment_hours + data.transition_hours
    plan_start = data.plan_start
    plan_end = plan_start + timedelta(hours=total) if plan_start else None
    now = datetime.now()

    created = 0
    for a in assignments:
        sample = db.get(Sample, a.sample_id)
        if sample is None:
            raise HTTPException(404, "样机不存在")
        if sample.status not in ("已接收", "已排期", "实验中", "已完成"):
            raise HTTPException(
                400, f"样机 {sample.sample_no}（{sample.sn or '无SN'}）当前状态（{sample.status}）不可排期"
                     "——仅已接收/已排期/实验中/已完成的样机可排期"
            )
        for _ in range(a.count):
            db.add(Schedule(
                order_id=order.id, sample_id=sample.id, equipment_id=equipment.id,
                experimenter_id=order.reviewer_id,
                experiment_hours=data.experiment_hours, transition_hours=data.transition_hours,
                total_hours=total, plan_start=plan_start, plan_end=plan_end,
                status="实验中", actual_start=now,
            ))
            created += 1
        sample.status = "实验中"
        db.add(SampleOperation(sample_id=sample.id, action="排期并开始实验", operator=user.name,
                               remark=f"{order.experiment_no or order.order_no} 复用 {a.count} 次 → {equipment.name}"))

    order.status = "实验中"
    log(db, user, "整单排期并开始实验", "order", order.id,
        f"{order.experiment_no or order.order_no} 排期 {created} 个测试位 → {equipment.name}")
    db.commit()
    return {"message": f"已排期并开始 {created} 个测试位", "count": created}
