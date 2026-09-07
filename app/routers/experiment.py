"""开始 / 结束实验，填写实验结果。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Sample, SampleOperation, Schedule, User
from ..notify import notify_entruster
from ..schemas import ResultUpdate
from ..serializers import order_to_dict, schedule_to_dict

router = APIRouter(prefix="/api/experiment", tags=["experiment"])


@router.post("/schedule/{schedule_id}/start")
def start_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "排期计划不存在")
    if schedule.status != "已排期":
        raise HTTPException(400, "该排期状态不可开始")
    schedule.status = "实验中"
    schedule.actual_start = datetime.now()
    sample = db.get(Sample, schedule.sample_id)
    if sample:
        sample.status = "实验中"
        db.add(SampleOperation(sample_id=sample.id, action="开始实验", operator=user.name))
    order = db.get(EntrustOrder, schedule.order_id)
    if order and order.status in ("已排期", "已审核"):
        order.status = "实验中"
    log(db, user, "开始实验", "schedule", schedule.id, schedule.sample.sample_no if schedule.sample else "")
    db.commit()
    return schedule_to_dict(schedule)


@router.post("/schedule/{schedule_id}/end")
def end_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "排期计划不存在")
    if schedule.status != "实验中":
        raise HTTPException(400, "该排期状态不可结束")
    schedule.status = "已完成"
    schedule.actual_end = datetime.now()
    db.add(SampleOperation(sample_id=schedule.sample_id, action="结束实验", operator=user.name))
    db.flush()  # autoflush=False，需显式 flush 让后续 count 反映本次状态变更
    # 该样机所有排期均已完成时，回到「已接收」（可复用，供下一委托单排期）
    sample = db.get(Sample, schedule.sample_id)
    if sample is not None and sample.status == "实验中":
        remaining = (
            db.query(Schedule)
            .filter(Schedule.sample_id == sample.id, Schedule.status != "已完成")
            .count()
        )
        if remaining == 0:
            sample.status = "已接收"
            db.add(SampleOperation(sample_id=sample.id, action="实验完成", operator=user.name,
                                   remark="样机可复用，回到已接收"))
    log(db, user, "结束实验", "schedule", schedule.id, schedule.sample.sample_no if schedule.sample else "")
    db.commit()
    return schedule_to_dict(schedule)


@router.put("/result")
def update_result(data: ResultUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    schedule = db.get(Schedule, data.schedule_id)
    if schedule is None:
        raise HTTPException(404, "排期计划不存在")
    if data.result not in ("OK", "NG"):
        raise HTTPException(400, "实验结果必须为 OK 或 NG")
    order = db.get(EntrustOrder, schedule.order_id)
    if order is not None and order.status == "已完成":
        raise HTTPException(400, "该委托单实验已结束，不可再修改实验结果")
    schedule.result = data.result
    if data.remark:
        db.add(SampleOperation(sample_id=schedule.sample_id, action="填写结果", operator=user.name,
                               remark=f"结果 {data.result}：{data.remark}"))
    else:
        db.add(SampleOperation(sample_id=schedule.sample_id, action="填写结果", operator=user.name,
                               remark=f"结果 {data.result}"))
    log(db, user, "填写结果", "schedule", schedule.id,
        f"{schedule.sample.sample_no if schedule.sample else ''} = {data.result}")
    db.commit()
    return {"message": "结果已保存"}


@router.post("/order/{order_id}/finish")
def finish_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "委托单不存在")
    if order.status == "已完成":
        raise HTTPException(400, "该委托单已结束")
    if not order.schedules:
        raise HTTPException(400, "该委托单尚无排期，无法结束实验")
    # 所有排期必须已完成
    unfinished = [s for s in order.schedules if s.status != "已完成"]
    if unfinished:
        raise HTTPException(400, f"还有 {len(unfinished)} 条排期未结束，不能结束实验")
    # 所有排期必须已填写实验结果（OK/NG），防止未判定就结束导致报告结论失真
    no_result = [s for s in order.schedules if s.result not in ("OK", "NG")]
    if no_result:
        raise HTTPException(400, f"还有 {len(no_result)} 条排期未填写实验结果（OK/NG），不能结束实验")
    order.status = "已完成"
    order.finish_at = datetime.now()
    log(db, user, "实验完成", "order", order.id, f"{order.experiment_no or order.order_no}")
    notify_entruster(db, order, "实验已完成", f"{order.experiment_no or order.order_no} {order.sample_name} 已完成，可查看报告")
    db.commit()
    return order_to_dict(order)
