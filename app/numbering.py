"""编号生成规则。

参考同行系统：
- 委托单编号：YYMM-四位流水，如 2312-3898
- 实验编号：YYMM-三位流水（审核通过后分配），如 2401-002
- 样品编号：实验编号-两位流水，如 2401-001-01
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import EntrustOrder, Report, Sample


def _next_sequence(db: Session, prefix: str, model, field, width: int) -> str:
    """在指定前缀（YYMM-）下取下一个流水号。"""
    like = f"{prefix}-%"
    row = (
        db.query(func.max(getattr(model, field)))
        .filter(getattr(model, field).like(like))
        .scalar()
    )
    current = 0
    if row:
        try:
            current = int(row.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            current = 0
    return f"{prefix}-{current + 1:0{width}d}"


def next_order_no(db: Session) -> str:
    prefix = datetime.now().strftime("%y%m")
    return _next_sequence(db, prefix, EntrustOrder, "order_no", 4)


def next_experiment_no(db: Session) -> str:
    prefix = datetime.now().strftime("%y%m")
    return _next_sequence(db, prefix, EntrustOrder, "experiment_no", 3)


def next_sample_no(db: Session, experiment_no: str, existing_count: int) -> str:
    """样品编号 = 实验编号 + '-' + 两位流水（全局按实验编号计数）。"""
    prefix = experiment_no
    row = (
        db.query(func.max(Sample.sample_no))
        .filter(Sample.sample_no.like(f"{prefix}-%"))
        .scalar()
    )
    current = existing_count
    if row:
        try:
            current = max(current, int(row.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            pass
    return f"{prefix}-{current + 1:02d}"


def next_report_no(db: Session) -> str:
    """报告编号：BG{YYMM}-四位流水，如 BG2608-0001。"""
    prefix = "BG" + datetime.now().strftime("%y%m")
    row = (
        db.query(func.max(Report.report_no))
        .filter(Report.report_no.like(f"{prefix}-%"))
        .scalar()
    )
    current = 0
    if row:
        try:
            current = int(row.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            current = 0
    return f"{prefix}-{current + 1:04d}"
