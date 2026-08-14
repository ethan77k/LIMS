"""设备管理 + 设备计价 + 校准/维保记录。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import field_diff, log
from ..database import get_db
from ..deps import require_roles
from ..models import Equipment, EquipmentMaintenance, User
from ..schemas import EquipmentCreate, EquipmentUpdate, MaintenanceCreate, MaintenanceUpdate
from ..serializers import equipment_to_dict, maintenance_to_dict

router = APIRouter(prefix="/api/equipment", tags=["equipment"])


@router.get("")
def list_equipment(
    exp_type: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = db.query(Equipment)
    if exp_type:
        q = q.filter(Equipment.exp_type == exp_type)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(Equipment.name.like(like), Equipment.code.like(like), Equipment.model.like(like)))
    return [equipment_to_dict(e) for e in q.order_by(Equipment.sort_order, Equipment.id).all()]


@router.post("")
def create_equipment(data: EquipmentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    eq = Equipment(**data.model_dump())
    db.add(eq)
    log(db, user, "新增设备", "equipment", None, f"{data.name}（{data.exp_type}）")
    db.commit()
    db.refresh(eq)
    return equipment_to_dict(eq)


@router.put("/{eq_id}")
def update_equipment(eq_id: int, data: EquipmentUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    eq = db.get(Equipment, eq_id)
    if eq is None:
        raise HTTPException(404, "设备不存在")
    changes = data.model_dump(exclude_unset=True)
    before = {k: getattr(eq, k) for k in changes}
    for field, value in changes.items():
        setattr(eq, field, value)
    diff = field_diff(before, changes)
    log(db, user, "修改设备", "equipment", eq.id, (eq.name + " ｜ " + diff) if diff else eq.name)
    db.commit()
    return equipment_to_dict(eq)


@router.delete("/{eq_id}")
def delete_equipment(eq_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    eq = db.get(Equipment, eq_id)
    if eq is None:
        raise HTTPException(404, "设备不存在")
    log(db, user, "删除设备", "equipment", eq.id, eq.name)
    db.delete(eq)
    db.commit()
    return {"message": "删除成功"}


@router.post("/{eq_id}/stop")
def stop_equipment(eq_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    eq = db.get(Equipment, eq_id)
    if eq is None:
        raise HTTPException(404, "设备不存在")
    if eq.status in ("停用", "报废"):
        eq.status = "可用"
        action = "设备启用"
    else:
        eq.status = "停用"
        action = "设备停用"
    log(db, user, action, "equipment", eq.id, eq.name)
    db.commit()
    return equipment_to_dict(eq)


# ---------------------------------------------------------------------------
# 校准 / 维保记录
# ---------------------------------------------------------------------------
@router.get("/{eq_id}/maintenance")
def list_maintenance(eq_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    rows = db.query(EquipmentMaintenance).filter(EquipmentMaintenance.equipment_id == eq_id).order_by(EquipmentMaintenance.id.desc()).all()
    return [maintenance_to_dict(m) for m in rows]


@router.post("/{eq_id}/maintenance")
def create_maintenance(eq_id: int, data: MaintenanceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    eq = db.get(Equipment, eq_id)
    if eq is None:
        raise HTTPException(404, "设备不存在")
    m = EquipmentMaintenance(equipment_id=eq_id, **data.model_dump())
    db.add(m)
    # 校准记录同步设备校准有效期
    if data.type == "校准" and data.next_date:
        eq.valid_to = data.next_date
    log(db, user, f"设备{data.type}", "equipment", eq.id, eq.name)
    db.commit()
    db.refresh(m)
    return maintenance_to_dict(m)


@router.put("/maintenance/{mid}")
def update_maintenance(mid: int, data: MaintenanceUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    m = db.get(EquipmentMaintenance, mid)
    if m is None:
        raise HTTPException(404, "维保记录不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    log(db, user, "修改维保记录", "equipment", m.equipment_id, m.type)
    db.commit()
    return maintenance_to_dict(m)


@router.delete("/maintenance/{mid}")
def delete_maintenance(mid: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    m = db.get(EquipmentMaintenance, mid)
    if m is None:
        raise HTTPException(404, "维保记录不存在")
    log(db, user, "删除维保记录", "equipment", m.equipment_id, m.type)
    db.delete(m)
    db.commit()
    return {"message": "删除成功"}


# ---------------------------------------------------------------------------
# 到期提醒
# ---------------------------------------------------------------------------
@router.get("/expiring/list")
def expiring(days: int = Query(30, ge=1), db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    """即将到期的设备：校准有效期（valid_to）或最近一次维保下次到期日在 N 天内。"""
    today = datetime.now().date()
    deadline = today + timedelta(days=days)
    result = []
    eqs = db.query(Equipment).filter(Equipment.valid_to.isnot(None)).all()
    for eq in eqs:
        d = eq.valid_to.date()
        if today <= d <= deadline:
            result.append({"id": eq.id, "name": eq.name, "code": eq.code, "valid_to": eq.valid_to.isoformat(), "days_left": (d - today).days})
    result.sort(key=lambda x: x["days_left"])
    return result
