"""样品管理：样品池（批次录入 / 整批或逐样确认 / 处置 / SN 录入 / 编辑 / 明细 / 打印条码）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import Sample, SampleBatch, SampleOperation, Schedule, User
from ..numbering import next_batch_no
from ..schemas import (
    SampleBatchConfirmRequest,
    SampleBatchCreate,
    SampleDisposeRequest,
    SampleOperationRequest,
    SampleReceiveRequest,
    SampleSNUpdateRequest,
    SampleUpdateRequest,
)
from ..serializers import batch_to_dict, sample_to_dict, schedule_to_dict

router = APIRouter(prefix="/api/samples", tags=["samples"])


def _get_sample(db: Session, sample_id: int) -> Sample:
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(404, "样品不存在")
    return sample


def _get_batch(db: Session, batch_id: int) -> SampleBatch:
    batch = db.get(SampleBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "样品批次不存在")
    return batch


def _log(db: Session, sample: Sample, action: str, operator: str, remark: str = ""):
    db.add(SampleOperation(sample_id=sample.id, action=action, operator=operator, remark=remark))


def _check_sn_unique(db: Session, sn: str, exclude_id: int | None = None):
    q = db.query(Sample).filter(Sample.sn == sn)
    if exclude_id is not None:
        q = q.filter(Sample.id != exclude_id)
    if q.first() is not None:
        raise HTTPException(400, f"SN「{sn}」已存在，请勿重复录入")


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------
@router.get("")
def list_samples(
    order_id: int | None = Query(None),
    status: str | None = Query(None),
    unbound: bool = Query(False),  # 仅样品池未绑单样品
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = db.query(Sample)
    if order_id:
        q = q.filter(Sample.order_id == order_id)
    if status:
        q = q.filter(Sample.status == status)
    if unbound:
        q = q.filter(Sample.order_id.is_(None))
    return [sample_to_dict(s) for s in q.order_by(Sample.id).all()]


# ---------------------------------------------------------------------------
# 样品批次（样品池）
# ---------------------------------------------------------------------------
@router.get("/batches")
def list_batches(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    return [batch_to_dict(b) for b in db.query(SampleBatch).order_by(SampleBatch.id.desc()).all()]


@router.post("/batches")
def create_batch(
    data: SampleBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    sns = [s.strip() for s in data.sn_list if s and s.strip()]
    if not sns:
        raise HTTPException(400, "SN 列表不能为空")

    # 本批内去重
    seen: set[str] = set()
    dup: list[str] = []
    for s in sns:
        if s in seen:
            dup.append(s)
        seen.add(s)
    if dup:
        raise HTTPException(400, f"SN 重复：{', '.join(dup)}")

    # 全局唯一校验
    existing = db.query(Sample).filter(Sample.sn.in_(sns)).all()
    if existing:
        raise HTTPException(400, f"SN 已存在：{', '.join(s.sn for s in existing if s.sn)}")

    batch_no = next_batch_no(db)
    batch = SampleBatch(
        batch_no=batch_no, entrust_org=data.entrust_org, entruster=data.entruster,
        sample_name=data.sample_name, sample_model=data.sample_model,
        customer_model=data.customer_model, sample_stage=data.sample_stage, quantity=len(sns), unit=data.unit,
        operator=user.name, remark=data.remark,
    )
    db.add(batch)
    db.flush()

    for i, sn in enumerate(sns, start=1):
        sample = Sample(
            sample_no=f"{batch_no}-{i:03d}", order_id=None, status="待接收",
            condition="未检查", sn=sn, batch_id=batch.id,
        )
        db.add(sample)
        db.flush()
        _log(db, sample, "录入", user.name, f"批次 {batch_no} 录入 SN {sn}")

    log(db, user, "样品批次录入", "sample_batch", batch.id, f"{batch_no} 共 {len(sns)} 条")
    db.commit()
    db.refresh(batch)
    return batch_to_dict(batch)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    return batch_to_dict(_get_batch(db, batch_id))


@router.post("/batches/{batch_id}/confirm")
def confirm_batch(
    batch_id: int,
    data: SampleBatchConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    batch = _get_batch(db, batch_id)
    confirmed = 0
    for s in batch.samples:
        if s.status == "待接收":
            s.status = "已接收"
            s.condition = data.condition or "样品正常"
            if data.remark:
                s.remark = data.remark
            _log(db, s, "确认", user.name, f"样品确认：{s.condition}")
            confirmed += 1
    if confirmed == 0:
        raise HTTPException(400, "该批次没有待确认样品")
    log(db, user, "样品批次确认", "sample_batch", batch.id, f"{batch.batch_no} 确认 {confirmed} 条")
    db.commit()
    db.refresh(batch)
    return batch_to_dict(batch)


@router.post("/batches/{batch_id}/dispose")
def dispose_batch(
    batch_id: int,
    data: SampleDisposeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    mapping = {"退还": "已退还", "报废": "已报废", "留存": "已留存"}
    if data.action not in mapping:
        raise HTTPException(400, "处置动作必须为：退还 / 报废 / 留存")
    batch = _get_batch(db, batch_id)
    done = 0
    for s in batch.samples:
        if s.status in ("已接收", "已排期", "实验中", "已完成"):
            s.status = mapping[data.action]
            _log(db, s, data.action, user.name, data.remark)
            done += 1
    if done == 0:
        raise HTTPException(400, "该批次没有可处置样品")
    log(db, user, f"样品批次{data.action}", "sample_batch", batch.id, f"{batch.batch_no} {data.action} {done} 条")
    db.commit()
    db.refresh(batch)
    return batch_to_dict(batch)


# ---------------------------------------------------------------------------
# 单样品
# ---------------------------------------------------------------------------
@router.get("/{sample_id}")
def get_sample(sample_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    return sample_to_dict(_get_sample(db, sample_id))


@router.get("/{sample_id}/history")
def sample_history(sample_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    """样品明细：操作记录 + 实验排期 + 关联委托单。"""
    sample = _get_sample(db, sample_id)
    data = sample_to_dict(sample)
    data["schedules"] = [
        schedule_to_dict(x)
        for x in db.query(Schedule).filter(Schedule.sample_id == sample.id).order_by(Schedule.id).all()
    ]
    if sample.order is not None:
        o = sample.order
        data["order"] = {
            "experiment_no": o.experiment_no, "order_no": o.order_no,
            "test_item": o.test_item, "entrust_org": o.entrust_org, "status": o.status,
        }
    else:
        data["order"] = None
    return data


@router.post("/{sample_id}/receive")
def receive_sample(
    sample_id: int,
    data: SampleReceiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    sample = _get_sample(db, sample_id)
    if sample.status not in ("待接收",):
        raise HTTPException(400, "该样品状态不可接收")
    if data.sn:
        _check_sn_unique(db, data.sn.strip(), exclude_id=sample.id)
        sample.sn = data.sn.strip()
    sample.status = "已接收"
    sample.condition = data.condition or "样品正常"
    sample.remark = data.remark
    _log(db, sample, "接收", user.name, f"样品检查：{sample.condition}")
    log(db, user, "样品接收", "sample", sample.id, sample.sample_no)
    db.commit()
    return sample_to_dict(sample)


@router.post("/{sample_id}/sn")
def update_sn(
    sample_id: int,
    data: SampleSNUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    sample = _get_sample(db, sample_id)
    sn = data.sn.strip()
    if not sn:
        raise HTTPException(400, "SN 不能为空")
    _check_sn_unique(db, sn, exclude_id=sample.id)
    old = sample.sn
    sample.sn = sn
    _log(db, sample, "SN录入", user.name, f"{old or '空'} → {sn}")
    log(db, user, "SN录入", "sample", sample.id, f"{sample.sample_no} SN={sn}")
    db.commit()
    return sample_to_dict(sample)


@router.post("/{sample_id}/update")
def update_sample(
    sample_id: int,
    data: SampleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """编辑样品字段（SN / 状态 / 状况），未传的字段不修改。"""
    sample = _get_sample(db, sample_id)
    valid_status = ("待接收", "已接收", "已排期", "实验中", "已完成", "已退还", "已报废", "已留存")
    changes: list[str] = []

    if data.sn is not None:
        sn = data.sn.strip()
        if sn != (sample.sn or ""):
            if sn:
                _check_sn_unique(db, sn, exclude_id=sample.id)
            changes.append(f"SN {sample.sn or '空'} → {sn or '空'}")
            sample.sn = sn or None

    if data.status is not None:
        if data.status not in valid_status:
            raise HTTPException(400, f"无效状态：{data.status}")
        if data.status != sample.status:
            changes.append(f"状态 {sample.status} → {data.status}")
            sample.status = data.status

    if data.condition is not None:
        cond = data.condition.strip()
        if cond != (sample.condition or ""):
            changes.append(f"状况 {sample.condition or '空'} → {cond or '空'}")
            sample.condition = cond

    if not changes:
        return sample_to_dict(sample)

    _log(db, sample, "编辑", user.name, "；".join(changes))
    log(db, user, "编辑样品", "sample", sample.id, f"{sample.sample_no}: {'；'.join(changes)}")
    db.commit()
    return sample_to_dict(sample)


@router.post("/{sample_id}/dispose")
def dispose_sample(
    sample_id: int,
    data: SampleDisposeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    sample = _get_sample(db, sample_id)
    mapping = {"退还": "已退还", "报废": "已报废", "留存": "已留存"}
    if data.action not in mapping:
        raise HTTPException(400, "处置动作必须为：退还 / 报废 / 留存")
    if sample.status not in ("已接收", "已排期", "实验中", "已完成"):
        raise HTTPException(400, f"样品当前状态（{sample.status}）不可处置")
    sample.status = mapping[data.action]
    _log(db, sample, data.action, user.name, data.remark)
    log(db, user, f"样品{data.action}", "sample", sample.id, sample.sample_no)
    db.commit()
    return sample_to_dict(sample)


@router.post("/{sample_id}/operation")
def add_operation(
    sample_id: int,
    data: SampleOperationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    sample = _get_sample(db, sample_id)
    _log(db, sample, data.action, user.name, data.remark)
    db.commit()
    return sample_to_dict(sample)
