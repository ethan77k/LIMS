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

    - user 指定时定向到该用户。
    - role 指定时**为每个该角色的在用账号各建一条**（各自独立已读），而非共享一条广播。
    - 两者都空时发给所有在用账号。
    """
    recipients: list[User] = []
    if user is not None:
        recipients = [user]
    elif role:
        recipients = db.query(User).filter(User.role == role, User.is_active.is_(True)).all()
    else:
        recipients = db.query(User).filter(User.is_active.is_(True)).all()
    for u in recipients:
        db.add(
            Notification(
                user_id=u.id,
                role="",
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
