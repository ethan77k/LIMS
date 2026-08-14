"""通知辅助：按角色或指定用户创建站内通知。"""
from sqlalchemy.orm import Session

from .models import Notification, User


def notify(
    db: Session,
    title: str,
    content: str = "",
    *,
    role: str = "",
    user: User | None = None,
    order_id: int | None = None,
) -> None:
    """创建一条通知。

    - user 指定时定向到该用户；否则 role 指定时广播给该角色（user_id 为空）。
    """
    db.add(
        Notification(
            user_id=user.id if user else None,
            role=role if not user else "",
            title=title,
            content=content,
            order_id=order_id,
        )
    )


def notify_entruster(db: Session, order, title: str, content: str = "") -> None:
    """通知委托人：优先按姓名匹配系统内的 entruster 账号，匹配不到则广播给 entruster 角色。"""
    matched = None
    if order.entruster:
        matched = (
            db.query(User)
            .filter(User.role == "entruster", User.name == order.entruster, User.is_active.is_(True))
            .first()
        )
    if matched:
        notify(db, title, content, user=matched, order_id=order.id)
    else:
        notify(db, title, content, role="entruster", order_id=order.id)
