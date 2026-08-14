"""站内通知：当前用户列表、未读数、已读标记。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Notification, User
from ..serializers import notification_to_dict

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _visible(db: Session, user: User):
    return db.query(Notification).filter(
        or_(Notification.user_id == user.id, Notification.role == user.role)
    )


@router.get("")
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = _visible(db, user).order_by(Notification.id.desc()).limit(100).all()
    return [notification_to_dict(n) for n in rows]


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = _visible(db, user).filter(Notification.is_read.is_(False)).count()
    return {"count": count}


@router.post("/{nid}/read")
def mark_read(nid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.get(Notification, nid)
    if n is None:
        raise HTTPException(404, "通知不存在")
    if n.user_id == user.id or n.role == user.role:
        n.is_read = True
        db.commit()
    return {"message": "已读"}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = _visible(db, user).filter(Notification.is_read.is_(False)).all()
    for n in rows:
        n.is_read = True
    db.commit()
    return {"message": f"已读 {len(rows)} 条"}
