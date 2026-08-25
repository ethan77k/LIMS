"""委托申请 / 委托查询。

同行系统：委托申请无需登录；委托人可查询/修改/删除"未审核"的委托单。
"""
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from ..audit import field_diff, log
from ..config import UPLOAD_DIR
from ..database import get_db
from ..deps import get_current_user, get_current_user_optional, require_roles
from ..models import EntrustOrder, Notification, OrderImage, Sample, Schedule, TestCase, User
from ..notify import notify
from ..numbering import next_order_no, retry_on_number_conflict
from ..schemas import OrderCreate, OrderUpdate
from ..serializers import order_image_to_dict, order_to_dict

router = APIRouter(prefix="/api/orders", tags=["orders"])

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _order_image_dir():
    d = UPLOAD_DIR / "orders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_order_images(db: Session, new_order: EntrustOrder, image_ids: list[int]) -> None:
    """复制委托申请时，把原单指定 id 的附件图片实体复制到新单。"""
    if not image_ids:
        return
    imgs = db.query(OrderImage).filter(OrderImage.id.in_(image_ids)).all()
    imgs.sort(key=lambda x: x.id)
    for img in imgs:
        name = os.path.basename(img.path or "")
        ext = os.path.splitext(name)[1].lower()
        stored_name = f"{uuid.uuid4().hex}{ext}"
        content = b""
        if name:
            src_file = _order_image_dir() / name
            if src_file.exists():
                try:
                    content = src_file.read_bytes()
                except OSError:
                    content = b""
        if content:
            (_order_image_dir() / stored_name).write_bytes(content)
        db.add(OrderImage(
            order_id=new_order.id,
            filename=img.filename or stored_name,
            path=f"/uploads/orders/{stored_name}",
        ))
    db.commit()


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
    copy_image_ids = values.pop("copy_image_ids", []) or []
    # 登录的委托人提交时，绑定到当前账号（委托人姓名强制取账号姓名，避免填错对不上）
    if user is not None and user.role == "entruster":
        values["entruster"] = user.name

    # 服务端必填校验（防止绕过前端直接调接口提交空单）
    _require_fields = {
        "委托单位": values.get("entrust_org"),
        "委托人": values.get("entruster"),
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

    def _do():
        order = EntrustOrder(**values, order_no=next_order_no(db))
        if user is not None and user.role == "entruster":
            order.entruster_user_id = user.id
        db.add(order)
        db.flush()
        log(db, None, "委托申请", "order", order.id, f"{order.order_no} {order.sample_name}")
        notify(db, "新委托待审核", f"{order.order_no} {order.sample_name}（{order.entrust_org}）", role="admin", order_id=order.id)
        notify(db, "新委托待审核", f"{order.order_no} {order.sample_name}（{order.entrust_org}）", role="experimenter", order_id=order.id)
        return order

    order = retry_on_number_conflict(db, _do)
    if copy_image_ids:
        _copy_order_images(db, order, copy_image_ids)
    db.refresh(order)
    return {"id": order.id, "order_no": order.order_no, "message": "委托申请提交成功"}


@router.get("")
def list_orders(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter", "entruster")),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    page: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=500),
):
    q = db.query(EntrustOrder)
    # 委托人只能看到自己名下的委托单：优先按账号 id 隔离，历史无 id 数据按姓名兜底
    if user.role == "entruster":
        q = q.filter(or_(
            EntrustOrder.entruster_user_id == user.id,
            EntrustOrder.entruster == user.name,
        ))
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
    # 未传 page 时保持返回数组（兼容旧前端）；传 page 时返回分页结构
    if page is None:
        orders = q.options(selectinload(EntrustOrder.images)).order_by(EntrustOrder.id.desc()).all()
        return [order_to_dict(o, with_detail=False) for o in orders]
    size = size or 20
    total = q.count()
    rows = q.options(selectinload(EntrustOrder.images)).order_by(EntrustOrder.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [order_to_dict(o, with_detail=False) for o in rows]}


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
    orders = q.options(selectinload(EntrustOrder.images)).order_by(EntrustOrder.id.desc()).all()
    return [order_to_dict(o, with_detail=False) for o in orders]


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    order = (
        db.query(EntrustOrder)
        .options(
            selectinload(EntrustOrder.samples).selectinload(Sample.operations),
            selectinload(EntrustOrder.schedules).selectinload(Schedule.sample),
            selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment),
            selectinload(EntrustOrder.costs),
            selectinload(EntrustOrder.reviewer),
            selectinload(EntrustOrder.case).selectinload(TestCase.images),
            selectinload(EntrustOrder.images),
        )
        .filter(EntrustOrder.id == order_id)
        .first()
    )
    if order is None:
        raise HTTPException(404, "委托单不存在")
    return order_to_dict(order)


@router.post("/{order_id}/images")
async def upload_order_image(
    order_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User | None = Depends(get_current_user_optional),
):
    """为委托单上传附件图片（试验条件附图等）。委托申请本身免登录，故上传同样开放。"""
    order = db.get(EntrustOrder, order_id)
    if order is None:
        raise HTTPException(404, "委托单不存在")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, "仅支持图片格式：jpg / png / gif / webp / bmp")
    content = await file.read()
    if not content:
        raise HTTPException(400, "图片内容为空")
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(400, "图片大小不能超过 5MB")
    stored_name = f"{uuid.uuid4().hex}{ext}"
    (_order_image_dir() / stored_name).write_bytes(content)
    img = OrderImage(
        order_id=order_id, filename=file.filename or stored_name,
        path=f"/uploads/orders/{stored_name}",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return order_image_to_dict(img)


def _check_editable(order: EntrustOrder, user: User) -> None:
    """校验修改/删除权限：仅管理员可操作，且仅未审核的委托单可改。"""
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可修改/删除委托单")
    if order.status != "待审核":
        raise HTTPException(400, "仅未审核的委托单可修改/删除")


@router.put("/{order_id}")
def update_order(order_id: int, data: OrderUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = _get_order(db, order_id)
    _check_editable(order, user)
    changes = data.model_dump(exclude_unset=True)
    before = {k: getattr(order, k) for k in changes}
    for field, value in changes.items():
        setattr(order, field, value)
    diff = field_diff(before, changes)
    log(db, user, "修改委托", "order", order.id, (order.order_no + " ｜ " + diff) if diff else order.order_no)
    db.commit()
    return {"message": "修改成功"}


@router.delete("/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = _get_order(db, order_id)
    _check_editable(order, user)
    log(db, user, "删除委托", "order", order.id, order.order_no)
    # 先清掉指向该委托单的通知，避免外键约束导致删除失败
    db.query(Notification).filter(Notification.order_id == order.id).delete(synchronize_session=False)
    db.delete(order)
    db.commit()
    return {"message": "删除成功"}
