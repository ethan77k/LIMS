"""工作台 / 展板 / 日夜班交接。"""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Equipment, Sample, Schedule, ShiftHandover, User
from ..schemas import HandoverCreate
from ..serializers import order_to_dict

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    return {
        "total_orders": db.query(EntrustOrder).count(),
        "pending_review": db.query(EntrustOrder).filter(EntrustOrder.status == "待审核").count(),
        "running": db.query(EntrustOrder).filter(EntrustOrder.status == "实验中").count(),
        "finished": db.query(EntrustOrder).filter(EntrustOrder.status == "已完成").count(),
        "rejected": db.query(EntrustOrder).filter(EntrustOrder.status == "已否决").count(),
        "total_equipment": db.query(Equipment).count(),
        "total_samples": db.query(Sample).count(),
    }


@router.get("/workbench")
def workbench(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    """待审核列表 + 待做实验列表。"""
    pending = db.query(EntrustOrder).filter(EntrustOrder.status == "待审核").order_by(EntrustOrder.id).all()
    todo = (
        db.query(EntrustOrder)
        .filter(EntrustOrder.status.in_(["已审核", "已排期", "实验中"]))
        .order_by(EntrustOrder.required_start, EntrustOrder.id)
        .all()
    )
    return {
        "pending": [order_to_dict(o, with_detail=False) for o in pending],
        "todo": [order_to_dict(o, with_detail=False) for o in todo],
    }


@router.get("/boards")
def boards(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    # 待试验展板：已审核/已排期的委托单，附设备清单与计划时间
    waiting_orders = (
        db.query(EntrustOrder)
        .options(selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment))
        .filter(EntrustOrder.status.in_(["已审核", "已排期"]))
        .order_by(EntrustOrder.id)
        .all()
    )
    waiting = []
    for o in waiting_orders:
        d = order_to_dict(o, with_detail=False)
        d["schedules"] = [
            {
                "equipment_name": s.equipment.name if s.equipment else "",
                "plan_start": s.plan_start.isoformat() if s.plan_start else None,
                "plan_end": s.plan_end.isoformat() if s.plan_end else None,
                "total_hours": s.total_hours,
            }
            for s in o.schedules
        ]
        d["equipment_list"] = "、".join(x["equipment_name"] for x in d["schedules"])
        d["plan_start_min"] = min((s.plan_start for s in o.schedules if s.plan_start), default=None)
        d["total_hours_sum"] = sum(s.total_hours for s in o.schedules)
        waiting.append(d)

    # 设备使用明细：正在实验中的排期
    in_use = (
        db.query(Schedule)
        .options(selectinload(Schedule.equipment), selectinload(Schedule.order), selectinload(Schedule.sample))
        .filter(Schedule.status == "实验中")
        .all()
    )
    usage = []
    for s in in_use:
        usage.append({
            "equipment_name": s.equipment.name if s.equipment else "",
            "order_no": s.order.experiment_no or s.order.order_no if s.order else "",
            "sample_no": s.sample.sample_no if s.sample else "",
            "actual_start": s.actual_start.isoformat() if s.actual_start else None,
            "plan_end": s.plan_end.isoformat() if s.plan_end else None,
        })

    # 设备排期展板：已排期（待开始）的排期
    upcoming = (
        db.query(Schedule)
        .options(selectinload(Schedule.equipment), selectinload(Schedule.order), selectinload(Schedule.sample))
        .filter(Schedule.status == "已排期")
        .order_by(Schedule.plan_start)
        .all()
    )
    schedule_board = []
    for s in upcoming:
        schedule_board.append({
            "equipment_name": s.equipment.name if s.equipment else "",
            "order_no": s.order.experiment_no or s.order.order_no if s.order else "",
            "sample_no": s.sample.sample_no if s.sample else "",
            "plan_start": s.plan_start.isoformat() if s.plan_start else None,
            "plan_end": s.plan_end.isoformat() if s.plan_end else None,
            "total_hours": s.total_hours,
        })

    return {"waiting": waiting, "usage": usage, "schedule_board": schedule_board}


# ---------------------------------------------------------------------------
# 日夜班交接
# ---------------------------------------------------------------------------
@router.get("/handover")
def list_handover(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    rows = db.query(ShiftHandover).order_by(ShiftHandover.id.desc()).all()
    return [
        {
            "id": h.id, "order_no": h.order_no, "note": h.note, "operator": h.operator,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in rows
    ]


@router.post("/handover")
def create_handover(data: HandoverCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    order_no = ""
    if data.order_id:
        order = db.get(EntrustOrder, data.order_id)
        order_no = order.experiment_no or order.order_no if order else ""
    h = ShiftHandover(order_id=data.order_id, order_no=order_no, note=data.note, operator=user.name)
    db.add(h)
    db.commit()
    return {"message": "交接记录已保存"}
