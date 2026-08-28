"""编号生成规则。

参考同行系统：
- 委托单编号：YYMM-四位流水，如 2312-3898
- 实验编号：YYMM-三位流水（审核通过后分配），如 2401-002
- 样品编号：实验编号-两位流水，如 2401-001-01
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import EntrustOrder, Report, Sample, SampleBatch


def retry_on_number_conflict(db: Session, fn, attempts: int = 3):
    """编号唯一冲突时回滚重试（并发 MAX+1 撞号兜底）。

    fn 内应完成所有 db.add/flush 并返回新对象；本函数负责 commit。
    撞号时回滚后重新调用 fn（重新取号），最多 attempts 次。
    """
    for i in range(attempts):
        try:
            result = fn()
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            if i == attempts - 1:
                raise
    raise RuntimeError("unreachable")  # pragma: no cover


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


def max_sample_seq(db: Session, experiment_no: str) -> int:
    """该实验编号下已使用的最大两位流水（无则 0）。"""
    row = (
        db.query(func.max(Sample.sample_no))
        .filter(Sample.sample_no.like(f"{experiment_no}-%"))
        .scalar()
    )
    if not row:
        return 0
    try:
        return int(row.rsplit("-", 1)[1])
    except (ValueError, IndexError):
        return 0


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


def next_batch_no(db: Session) -> str:
    """样品批次号：PC{YYMM}-四位流水，如 PC2608-0001。"""
    prefix = "PC" + datetime.now().strftime("%y%m")
    row = (
        db.query(func.max(SampleBatch.batch_no))
        .filter(SampleBatch.batch_no.like(f"{prefix}-%"))
        .scalar()
    )
    current = 0
    if row:
        try:
            current = int(row.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            current = 0
    return f"{prefix}-{current + 1:04d}"


def next_pool_sample_no(db: Session, batch_no: str) -> str:
    """池样品编号 = 批次号 + '-' + 两位流水，如 PC2608-0001-01。"""
    row = (
        db.query(func.max(Sample.sample_no))
        .filter(Sample.sample_no.like(f"{batch_no}-%"))
        .scalar()
    )
    current = 0
    if row:
        try:
            current = int(row.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            current = 0
    return f"{batch_no}-{current + 1:02d}"
