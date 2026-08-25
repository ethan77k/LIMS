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
from ..models import EntrustOrder, Report, Sample, User

router = APIRouter(prefix="/api/export", tags=["export"])


def _csv_response(headers: list[str], rows: list[list], prefix: str) -> StreamingResponse:
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    data = "﻿" + output.getvalue()
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    rows = [
        [o.order_no, o.experiment_no or "", o.status, o.entrust_org, o.entruster,
         o.sample_model, o.test_item, o.sample_count, o.total_cost,
         o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
         o.finish_at.strftime("%Y-%m-%d %H:%M") if o.finish_at else ""]
        for o in orders
    ]
    return _csv_response(
        ["委托编号", "实验编号", "状态", "委托单位", "委托人", "样品型号", "检测项目", "样品数量", "试验成本", "委托时间", "完成时间"],
        rows, "orders",
    )


@router.get("/samples")
def export_samples(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
    status: str | None = Query(None),
):
    q = db.query(Sample).join(EntrustOrder, Sample.order_id == EntrustOrder.id)
    if status:
        q = q.filter(Sample.status == status)
    samples = q.order_by(Sample.id.desc()).all()
    rows = [
        [s.sample_no, s.order.experiment_no or s.order.order_no,
         s.status, s.condition, s.result or "", s.remark,
         s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else ""]
        for s in samples
    ]
    return _csv_response(
        ["样品编号", "实验编号", "状态", "状况", "结果", "备注", "创建时间"],
        rows, "samples",
    )


@router.get("/reports")
def export_reports(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    reports = db.query(Report).join(EntrustOrder, Report.order_id == EntrustOrder.id).order_by(Report.id.desc()).all()
    rows = [
        [r.report_no, r.report_type, r.version or "", r.status,
         r.order.experiment_no or r.order.order_no,
         r.issuer.name if r.issuer else "",
         r.issued_at.strftime("%Y-%m-%d %H:%M") if r.issued_at else ""]
        for r in reports
    ]
    return _csv_response(
        ["报告编号", "报告类型", "版本", "状态", "实验编号", "签发人", "签发时间"],
        rows, "reports",
    )
