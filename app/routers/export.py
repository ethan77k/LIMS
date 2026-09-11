"""数据导出 CSV（带 BOM，Excel 可直接打开中文）。"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Report, Schedule, User
from .. import onlyoffice

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
    """导出实验排期/测试记录（每个测试位一行，含实物样机 SN 与复用关系）。"""
    q = (
        db.query(Schedule)
        .options(selectinload(Schedule.sample), selectinload(Schedule.order), selectinload(Schedule.equipment),
                 selectinload(Schedule.experimenter))
    )
    if status:
        q = q.filter(Schedule.status == status)
    schedules = q.order_by(Schedule.id.desc()).all()
    rows = [
        [s.sample.sample_no if s.sample else "",
         s.sample.sn or "" if s.sample else "",
         (s.order.experiment_no or s.order.order_no) if s.order else "",
         s.equipment.name if s.equipment else "",
         s.experimenter.name if s.experimenter else "",
         s.result or "", s.status,
         s.actual_start.strftime("%Y-%m-%d %H:%M") if s.actual_start else ""]
        for s in schedules
    ]
    return _csv_response(
        ["样品编号", "SN", "实验编号", "设备", "实验员", "结果", "状态", "开始时间"],
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


# ---------------------------------------------------------------------------
# Excel 在线编辑：数据列表导出 .xlsx → OnlyOffice 表格编辑 → 下载
# ---------------------------------------------------------------------------
def build_export_xlsx(db: Session, kind: str) -> bytes:
    """按导出类型生成 .xlsx（全量列表，不含筛选）。"""
    if kind == "orders":
        orders = db.query(EntrustOrder).order_by(EntrustOrder.id.desc()).all()
        headers = ["委托编号", "实验编号", "状态", "委托单位", "委托人", "样品型号", "检测项目", "样品数量", "试验成本", "委托时间", "完成时间"]
        rows = [
            [o.order_no, o.experiment_no or "", o.status, o.entrust_org, o.entruster,
             o.sample_model, o.test_item, o.sample_count, o.total_cost,
             o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
             o.finish_at.strftime("%Y-%m-%d %H:%M") if o.finish_at else ""]
            for o in orders
        ]
    elif kind == "samples":
        schedules = (
            db.query(Schedule)
            .options(selectinload(Schedule.sample), selectinload(Schedule.order),
                     selectinload(Schedule.equipment), selectinload(Schedule.experimenter))
            .order_by(Schedule.id.desc()).all()
        )
        headers = ["样品编号", "SN", "实验编号", "设备", "实验员", "结果", "状态", "开始时间"]
        rows = [
            [s.sample.sample_no if s.sample else "", s.sample.sn or "" if s.sample else "",
             (s.order.experiment_no or s.order.order_no) if s.order else "",
             s.equipment.name if s.equipment else "", s.experimenter.name if s.experimenter else "",
             s.result or "", s.status,
             s.actual_start.strftime("%Y-%m-%d %H:%M") if s.actual_start else ""]
            for s in schedules
        ]
    elif kind == "reports":
        reports = db.query(Report).join(EntrustOrder, Report.order_id == EntrustOrder.id).order_by(Report.id.desc()).all()
        headers = ["报告编号", "报告类型", "版本", "状态", "实验编号", "签发人", "签发时间"]
        rows = [
            [r.report_no, r.report_type, r.version or "", r.status,
             r.order.experiment_no or r.order.order_no,
             r.issuer.name if r.issuer else "",
             r.issued_at.strftime("%Y-%m-%d %H:%M") if r.issued_at else ""]
            for r in reports
        ]
    else:
        raise HTTPException(404, "未知导出类型")
    return onlyoffice.xlsx_bytes(headers, rows, kind)


@router.post("/online")
def export_online(
    kind: str = Query("orders"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """生成 .xlsx 并返回 OnlyOffice 表格编辑器配置（在线编辑后再下载）。"""
    if not onlyoffice.is_enabled():
        raise HTTPException(503, "未配置 OnlyOffice，请设置 LIMS_ONLYOFFICE_URL / LIMS_ONLYOFFICE_JWT_SECRET 后启用")
    if kind not in ("orders", "samples", "reports"):
        raise HTTPException(404, "未知导出类型")
    data = build_export_xlsx(db, kind)
    key = onlyoffice.make_key({"kind": "export", "export": kind})
    onlyoffice.work_file(key, "xlsx").write_bytes(data)
    config = onlyoffice.editor_config(
        key=key,
        title=f"{kind}_{datetime.now().strftime('%Y%m%d')}.xlsx",
        file_type="xlsx",
        document_type="cell",
        user_id=user.id,
        user_name=user.name,
        download_path=f"/api/oo/download?key={key}",
        callback_path="/api/oo/callback",
    )
    return config


@router.get("/online/download")
def export_online_download(
    key: str = Query(...),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    """下载 OnlyOffice 编辑后的 .xlsx。"""
    try:
        payload = onlyoffice.parse_key(key)
    except ValueError:
        raise HTTPException(400, "非法文档 key")
    if payload.get("kind") != "export":
        raise HTTPException(400, "不是导出文档")
    fp = onlyoffice.work_file(key, "xlsx")
    if not fp.exists():
        raise HTTPException(404, "尚未编辑保存，请先在在线表格中保存")
    filename = f"{payload.get('export')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        iter([fp.read_bytes()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
