"""委托申请 / 委托查询。

同行系统：委托申请无需登录；委托人可查询/修改/删除"未审核"的委托单。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import get_current_user, get_current_user_optional, require_roles
from ..models import EntrustOrder, User
from ..notify import notify
from ..numbering import next_order_no
from ..schemas import OrderCreate, OrderUpdate
from ..serializers import order_to_dict

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _get_order(db: Session, order_id: int) -> EntrustOrder:
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "委托单不存在")
    return order


@router.post("")
def create_order(
    data: OrderCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    values = data.model_dump()
    # 登录的委托人提交时，绑定到当前账号（委托人姓名强制取账号姓名，避免填错对不上）
    if user is not None and user.role == "entruster":
        values["entruster"] = user.name

    # 服务端必填校验（防止绕过前端直接调接口提交空单）
    _require_fields = {
        "委托单位": values.get("entrust_org"),
        "委托人": values.get("entruster"),
        "样品名称": values.get("sample_name"),
        "检测项目": values.get("test_item"),
        "联系电话": values.get("phone"),
        "内网邮箱": values.get("email"),
    }
    missing = [k for k, v in _require_fields.items() if not str(v or "").strip()]
    if missing:
        raise HTTPException(400, "必填项缺失：" + "、".join(missing))
    email = str(values.get("email") or "").strip()
    if "@" not in email:
        raise HTTPException(400, "内网邮箱格式不正确（需包含 @）")
    if int(values.get("sample_count") or 0) < 1:
        raise HTTPException(400, "样品数量至少为 1")

    order = EntrustOrder(**values, order_no=next_order_no(db))
    db.add(order)
    db.flush()
    log(db, None, "委托申请", "order", order.id, f"{order.order_no} {order.sample_name}")
    notify(db, "新委托待审核", f"{order.order_no} {order.sample_name}（{order.entrust_org}）", role="admin", order_id=order.id)
    notify(db, "新委托待审核", f"{order.order_no} {order.sample_name}（{order.entrust_org}）", role="experimenter", order_id=order.id)
    db.commit()
    db.refresh(order)
    return {"id": order.id, "order_no": order.order_no, "message": "委托申请提交成功"}


@router.get("")
def list_orders(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter", "entruster")),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    q = db.query(EntrustOrder)
    # 委托人只能看到自己名下（委托人姓名匹配）的委托单
    if user.role == "entruster":
        q = q.filter(EntrustOrder.entruster == user.name)
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
    return [order_to_dict(o, with_detail=False) for o in orders]


@router.get("/query")
def public_query(
    order_no: str = Query(""),
    phone: str = Query(""),
    db: Session = Depends(get_db),
):
    """委托人无需登录，凭委托单编号 + 联系电话查询。"""
    q = db.query(EntrustOrder)
    if order_no:
        q = q.filter(EntrustOrder.order_no == order_no)
    if phone:
        q = q.filter(EntrustOrder.phone == phone)
    if not order_no and not phone:
        return []
    orders = q.order_by(EntrustOrder.id.desc()).all()
    return [order_to_dict(o, with_detail=False) for o in orders]


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    return order_to_dict(_get_order(db, order_id))


def _check_editable(order: EntrustOrder, user: User) -> None:
    """校验修改/删除权限：仅待审核可改，且委托人只能操作本人委托单。"""
    if order.status != "待审核":
        raise HTTPException(400, "仅未审核的委托单可修改/删除")
    if user.role == "entruster" and order.entruster != user.name:
        raise HTTPException(403, "只能修改/删除本人名下的委托单")


@router.put("/{order_id}")
def update_order(order_id: int, data: OrderUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = _get_order(db, order_id)
    _check_editable(order, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    log(db, user, "修改委托", "order", order.id, order.order_no)
    db.commit()
    return {"message": "修改成功"}


@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = _get_order(db, order_id)
    _check_editable(order, user)
    log(db, user, "删除委托", "order", order.id, order.order_no)
    db.delete(order)
    db.commit()
    return {"message": "删除成功"}
