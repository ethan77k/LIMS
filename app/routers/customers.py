"""客户 / 委托单位档案。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import Customer, EntrustOrder, User
from ..schemas import CustomerCreate, CustomerUpdate
from ..serializers import customer_to_dict, order_to_dict

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("")
def list_customers(
    keyword: str | None = Query(None),
    page: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = db.query(Customer)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(Customer.name.like(like), Customer.contact.like(like), Customer.phone.like(like)))
    # 未传 page 时保持返回数组（兼容旧前端）；传 page 时返回分页结构
    if page is None:
        return [customer_to_dict(c) for c in q.order_by(Customer.id.desc()).all()]
    size = size or 20
    total = q.count()
    rows = q.order_by(Customer.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [customer_to_dict(c) for c in rows]}


@router.post("")
def create_customer(data: CustomerCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    if db.query(Customer).filter(Customer.name == data.name).first():
        raise HTTPException(400, "该客户已存在")
    c = Customer(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    log(db, user, "新增客户", "customer", c.id, c.name)
    db.commit()
    return customer_to_dict(c)


@router.put("/{cid}")
def update_customer(cid: int, data: CustomerUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    c = db.get(Customer, cid)
    if c is None:
        raise HTTPException(404, "客户不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    log(db, user, "修改客户", "customer", c.id, c.name)
    db.commit()
    return customer_to_dict(c)


@router.delete("/{cid}")
def delete_customer(cid: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    c = db.get(Customer, cid)
    if c is None:
        raise HTTPException(404, "客户不存在")
    log(db, user, "删除客户", "customer", c.id, c.name)
    db.delete(c)
    db.commit()
    return {"message": "删除成功"}


@router.get("/{cid}/orders")
def customer_orders(cid: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    c = db.get(Customer, cid)
    if c is None:
        raise HTTPException(404, "客户不存在")
    orders = (
        db.query(EntrustOrder)
        .filter(EntrustOrder.entrust_org == c.name)
        .order_by(EntrustOrder.id.desc())
        .all()
    )
    return [order_to_dict(o, with_detail=False) for o in orders]
