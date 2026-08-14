"""数据导出 CSV（带 BOM，Excel 可直接打开中文）。"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, User

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/orders")
def export_orders(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    q = db.query(EntrustOrder)
    if status:
        q = q.filter(EntrustOrder.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(
            EntrustOrder.order_no.like(like),
            EntrustOrder.experiment_no.like(like),
            EntrustOrder.entruster.like(like),
            EntrustOrder.entrust_org.like(like),
            EntrustOrder.sample_model.like(like),
            EntrustOrder.sample_name.like(like),
        ))
    orders = q.order_by(EntrustOrder.id.desc()).all()

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["委托编号", "实验编号", "状态", "委托单位", "委托人", "样品名称", "样品型号", "检测项目", "样品数量", "试验成本", "委托时间", "完成时间"])
    for o in orders:
        w.writerow([
            o.order_no, o.experiment_no or "", o.status, o.entrust_org, o.entruster,
            o.sample_name, o.sample_model, o.test_item, o.sample_count, o.total_cost,
            o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
            o.finish_at.strftime("%Y-%m-%d %H:%M") if o.finish_at else "",
        ])
    data = "﻿" + output.getvalue()
    filename = f"orders_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
