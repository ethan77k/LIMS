"""样品管理：接收、退还/报废/留存、操作明细。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import Sample, SampleOperation, User
from ..schemas import SampleDisposeRequest, SampleOperationRequest, SampleReceiveRequest
from ..serializers import sample_to_dict

router = APIRouter(prefix="/api/samples", tags=["samples"])


def _get_sample(db: Session, sample_id: int) -> Sample:
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(404, "样品不存在")
    return sample


def _log(db: Session, sample: Sample, action: str, operator: str, remark: str = ""):
    db.add(SampleOperation(sample_id=sample.id, action=action, operator=operator, remark=remark))


@router.get("")
def list_samples(
    order_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = db.query(Sample)
    if order_id:
        q = q.filter(Sample.order_id == order_id)
    return [sample_to_dict(s) for s in q.order_by(Sample.id).all()]


@router.get("/{sample_id}")
def get_sample(sample_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    return sample_to_dict(_get_sample(db, sample_id))


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
    sample.status = "已接收"
    sample.condition = data.condition or "样品正常"
    sample.remark = data.remark
    _log(db, sample, "接收", user.name, f"样品检查：{sample.condition}")
    log(db, user, "样品接收", "sample", sample.id, sample.sample_no)
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
