"""委托审核。

通过：分配实验编号、生成样品列表、录入费用明细（可动态选择实验员）。
否决：记录否决原因。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import CostItem, EntrustOrder, Equipment, Sample, SampleOperation, User
from ..notify import notify_entruster
from ..numbering import next_experiment_no, next_sample_no
from ..schemas import ReviewRequest
from ..serializers import order_to_dict

router = APIRouter(prefix="/api/review", tags=["review"])

# 费用公式：amount = (开机费 + (电费/小时 + 折旧费/小时 + 辅耗材/小时) × 次数) × 数量 × 折扣
_COST_FORMULA = "金额 = (开机费 + (电费/小时 + 折旧费/小时 + 辅耗材/小时) × 次数) × 数量 × 折扣"


@router.post("/{order_id}")
def review_order(
    order_id: int,
    data: ReviewRequest,
    db: Session = Depends(get_db),
    reviewer: User = Depends(require_roles("admin", "experimenter")),
):
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "委托单不存在")
    if order.status != "待审核":
        raise HTTPException(400, "该委托单已审核，不能重复操作")

    # 否决
    if not data.approve:
        if not (data.reject_reason or "").strip():
            raise HTTPException(400, "否决时必须填写否决原因")
        order.status = "已否决"
        order.reject_reason = data.reject_reason
        order.reviewer_id = reviewer.id
        order.review_at = datetime.now()
        log(db, reviewer, "审核否决", "order", order.id, f"{order.order_no} 原因：{data.reject_reason}")
        notify_entruster(db, order, "委托被否决", f"{order.order_no} {order.sample_name} 未通过审核")
        db.commit()
        return {"message": "已否决", "status": "已否决"}

    # 通过
    order.experiment_no = next_experiment_no(db)
    order.status = "已审核"
    order.reviewer_id = data.reviewer_id or reviewer.id
    order.review_at = datetime.now()
    if data.required_start:
        order.required_start = data.required_start

    # 生成样品
    for i in range(order.sample_count):
        sample_no = next_sample_no(db, order.experiment_no, i)
        sample = Sample(sample_no=sample_no, order_id=order.id, status="待接收", condition="未检查")
        db.add(sample)

    # 费用明细
    total = 0.0
    for item in data.costs:
        eq = db.get(Equipment, item.get("equipment_id")) if item.get("equipment_id") else None
        open_fee = float(eq.open_fee if eq else item.get("open_fee", 0))
        power_fee = float(eq.power_fee if eq else item.get("power_fee", 0))
        dep_fee = float(eq.depreciation_fee if eq else item.get("depreciation_fee", 0))
        cons_fee = float(eq.consumable_fee if eq else item.get("consumable_fee", 0))
        count = int(item.get("count", 1) or 1)
        quantity = int(item.get("quantity", 1) or 1)
        discount = float(item.get("discount", 1.0) or 1.0)
        amount = (open_fee + (power_fee + dep_fee + cons_fee) * count) * quantity * discount
        cost = CostItem(
            order_id=order.id,
            equipment_id=item.get("equipment_id"),
            test_item=item.get("test_item", order.test_item),
            equipment_name=eq.name if eq else item.get("equipment_name", ""),
            open_fee=open_fee, power_fee=power_fee, depreciation_fee=dep_fee,
            consumable_fee=cons_fee,
            count=count, quantity=quantity, discount=discount, amount=amount,
        )
        db.add(cost)
        total += amount
    order.total_cost = round(total, 2)

    # 记录样品操作（生成）
    db.flush()
    for sample in order.samples:
        db.add(SampleOperation(sample_id=sample.id, action="生成", operator=reviewer.name, remark="审核通过自动生成"))

    log(db, reviewer, "审核通过", "order", order.id, f"{order.experiment_no} 实验编号已分配")
    notify_entruster(db, order, "委托审核通过", f"{order.order_no} 已通过审核，实验编号 {order.experiment_no}")
    db.commit()
    db.refresh(order)
    return {"message": "审核通过", "experiment_no": order.experiment_no}


@router.get("/formula")
def cost_formula():
    return {"formula": _COST_FORMULA}
