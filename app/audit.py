"""审计日志辅助：所有关键操作统一留痕。"""
from sqlalchemy.orm import Session

from .models import AuditLog, User


def field_diff(before: dict, after: dict) -> str:
    """生成「字段: 旧→新；…」的改前/改后差异描述（仅含真正变化的字段）。"""
    parts = []
    for k, new in after.items():
        old = before.get(k)
        if str(old) != str(new):
            parts.append(f"{k}: {old if old not in (None, '') else '（空）'}→{new if new not in (None, '') else '（空）'}")
    return "；".join(parts)


def log(
    db: Session,
    user: User | None,
    action: str,
    target_type: str = "",
    target_id: object = None,
    detail: str = "",
) -> None:
    """记录一条审计日志。user 可为 None（如公开委托提交）。"""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.name if user else "",
            action=action,
            target_type=target_type,
            target_id="" if target_id is None else str(target_id),
            detail=detail,
        )
    )
