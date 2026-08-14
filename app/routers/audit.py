"""审计日志查询（仅管理员）。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import AuditLog, User
from ..serializers import audit_to_dict

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
    action: str | None = Query(None),
    username: str | None = Query(None),
    target_type: str | None = Query(None),
    keyword: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if username:
        q = q.filter(AuditLog.username.like(f"%{username}%"))
    if target_type:
        q = q.filter(AuditLog.target_type == target_type)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(AuditLog.detail.like(like), AuditLog.target_id.like(like)))
    if from_:
        try:
            q = q.filter(AuditLog.created_at >= datetime.fromisoformat(from_))
        except ValueError:
            pass
    if to:
        try:
            q = q.filter(AuditLog.created_at <= datetime.fromisoformat(to) + timedelta(days=1))
        except ValueError:
            pass
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [audit_to_dict(a) for a in rows]}
