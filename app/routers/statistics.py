"""统计分析：概览、趋势、费用、设备利用率、工作量、结果分布。"""
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Equipment, Sample, Schedule, User
from ..serializers import order_to_dict, sample_to_dict, schedule_to_dict

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    # 一次 group_by 统计各状态数量，替代多次 count
    status_counts = dict(
        db.query(EntrustOrder.status, func.count(EntrustOrder.id))
        .group_by(EntrustOrder.status)
        .all()
    )
    total_cost = (
        db.query(func.sum(EntrustOrder.total_cost))
        .filter(EntrustOrder.status == "已完成")
        .scalar()
    ) or 0
    finished_rows = (
        db.query(EntrustOrder.created_at, EntrustOrder.finish_at)
        .filter(EntrustOrder.status == "已完成", EntrustOrder.finish_at.isnot(None))
        .all()
    )
    cycles = [(f - c).total_seconds() / 86400 for c, f in finished_rows if f]
    avg_cycle = round(sum(cycles) / len(cycles), 1) if cycles else 0
    return {
        "total_orders": sum(status_counts.values()),
        "pending_review": status_counts.get("待审核", 0),
        "in_progress": sum(status_counts.get(k, 0) for k in ("已审核", "已排期", "实验中")),
        "finished": status_counts.get("已完成", 0),
        "rejected": status_counts.get("已否决", 0),
        "total_cost": round(total_cost, 2),
        "avg_cycle": avg_cycle,
        "total_samples": db.query(func.count(Sample.id)).scalar() or 0,
        "total_equipment": db.query(func.count(Equipment.id)).scalar() or 0,
    }


@router.get("/trend")
def trend(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    since = datetime.now() - timedelta(days=days)
    created_rows = db.query(EntrustOrder.created_at).filter(EntrustOrder.created_at >= since).all()
    finished_rows = db.query(EntrustOrder.finish_at).filter(
        EntrustOrder.finish_at >= since, EntrustOrder.finish_at.isnot(None)
    ).all()
    created_by_day: dict[str, int] = defaultdict(int)
    finished_by_day: dict[str, int] = defaultdict(int)
    for (c,) in created_rows:
        created_by_day[c.date().isoformat()] += 1
    for (f,) in finished_rows:
        finished_by_day[f.date().isoformat()] += 1
    today = datetime.now().date()
    result = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        result.append({"date": d, "created": created_by_day.get(d, 0), "finished": finished_by_day.get(d, 0)})
    return result


@router.get("/cost")
def cost(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    orders = db.query(EntrustOrder).filter(EntrustOrder.total_cost > 0).all()
    by_item: dict[str, float] = defaultdict(float)
    by_month: dict[str, float] = defaultdict(float)
    for o in orders:
        by_item[o.test_item or "未分类"] += o.total_cost
        by_month[o.created_at.strftime("%Y-%m")] += o.total_cost
    return {
        "by_item": [{"name": k, "value": round(v, 2)} for k, v in sorted(by_item.items(), key=lambda x: -x[1])],
        "by_month": [{"name": k, "value": round(v, 2)} for k, v in sorted(by_month.items())],
    }


@router.get("/equipment-usage")
def equipment_usage(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    rows = db.query(Schedule).options(selectinload(Schedule.equipment)).all()
    by_eq: dict[str, dict] = defaultdict(lambda: {"hours": 0.0, "count": 0, "finished": 0})
    for s in rows:
        name = s.equipment.name if s.equipment else "未知设备"
        e = by_eq[name]
        e["hours"] += s.total_hours or 0
        e["count"] += 1
        if s.status == "已完成":
            e["finished"] += 1
    return [
        {"name": k, "hours": round(v["hours"], 1), "count": v["count"], "finished": v["finished"]}
        for k, v in sorted(by_eq.items(), key=lambda x: -x[1]["hours"])
    ]


@router.get("/workload")
def workload(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    orders = (
        db.query(EntrustOrder)
        .options(selectinload(EntrustOrder.reviewer))
        .filter(EntrustOrder.reviewer_id.isnot(None))
        .all()
    )
    by_person: dict[str, dict] = defaultdict(lambda: {"orders": 0, "samples": 0, "finished": 0})
    for o in orders:
        name = o.reviewer.name if o.reviewer else "未知"
        p = by_person[name]
        p["orders"] += 1
        p["samples"] += o.sample_count or 0
        if o.status == "已完成":
            p["finished"] += 1
    return [
        {"name": k, "orders": v["orders"], "samples": v["samples"], "finished": v["finished"]}
        for k, v in sorted(by_person.items(), key=lambda x: -x[1]["orders"])
    ]


@router.get("/result-distribution")
def result_distribution(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    ok = db.query(Sample).filter(Sample.result == "OK").count()
    ng = db.query(Sample).filter(Sample.result == "NG").count()
    other = db.query(Sample).count() - ok - ng
    return [{"name": "OK", "value": ok}, {"name": "NG", "value": ng}, {"name": "未判定", "value": other}]


@router.get("/detail")
def detail(
    type: str = Query(..., description="trend / cost_item / cost_month / equipment / workload / result"),
    key: str = Query("", description="图表中点击的维度取值"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    """图表下钻：按图表类型 + 维度取值返回底层明细记录。"""
    if type == "trend":
        # key = YYYY-MM-DD，返回当天新建或完成的委托单
        try:
            d = datetime.strptime(key, "%Y-%m-%d")
        except ValueError:
            return []
        start, end = d, d + timedelta(days=1)
        orders = (
            db.query(EntrustOrder)
            .filter(or_(
                and_(EntrustOrder.created_at >= start, EntrustOrder.created_at < end),
                and_(EntrustOrder.finish_at.isnot(None), EntrustOrder.finish_at >= start, EntrustOrder.finish_at < end),
            ))
            .order_by(EntrustOrder.id.desc()).all()
        )
        return [order_to_dict(o, with_detail=False) for o in orders]

    if type == "cost_item":
        orders = db.query(EntrustOrder).filter(EntrustOrder.test_item == key).order_by(EntrustOrder.id.desc()).all()
        return [order_to_dict(o, with_detail=False) for o in orders]

    if type == "cost_month":
        orders = (
            db.query(EntrustOrder)
            .filter(func.strftime("%Y-%m", EntrustOrder.created_at) == key)
            .order_by(EntrustOrder.id.desc()).all()
        )
        return [order_to_dict(o, with_detail=False) for o in orders]

    if type == "equipment":
        rows = (
            db.query(Schedule)
            .join(Equipment, Schedule.equipment_id == Equipment.id)
            .filter(Equipment.name == key)
            .order_by(Schedule.id.desc()).all()
        )
        return [schedule_to_dict(s) for s in rows]

    if type == "workload":
        rows = (
            db.query(EntrustOrder)
            .join(User, EntrustOrder.reviewer_id == User.id)
            .filter(User.name == key)
            .order_by(EntrustOrder.id.desc()).all()
        )
        return [order_to_dict(o, with_detail=False) for o in rows]

    if type == "result":
        if key in ("OK", "NG"):
            rows = db.query(Sample).filter(Sample.result == key).order_by(Sample.id.desc()).all()
        else:  # 未判定
            rows = db.query(Sample).filter(~Sample.result.in_(["OK", "NG"])).order_by(Sample.id.desc()).all()
        return [sample_to_dict(s) for s in rows]

    return []
