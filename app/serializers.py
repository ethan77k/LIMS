"""把 ORM 对象转成可 JSON 序列化的 dict（含关联对象与 datetime）。"""
from datetime import datetime


def _dt(v):
    return v.isoformat() if isinstance(v, datetime) else v


def sample_to_dict(s) -> dict:
    return {
        "id": s.id, "sample_no": s.sample_no, "order_id": s.order_id,
        "status": s.status, "condition": s.condition, "result": s.result, "remark": s.remark,
        "created_at": _dt(s.created_at),
        "operations": [
            {"id": o.id, "action": o.action, "operator": o.operator,
             "remark": o.remark, "created_at": _dt(o.created_at)}
            for o in sorted(s.operations, key=lambda x: x.id)
        ],
    }


def cost_to_dict(c) -> dict:
    return {
        "id": c.id, "equipment_id": c.equipment_id, "test_item": c.test_item,
        "equipment_name": c.equipment_name, "open_fee": c.open_fee, "power_fee": c.power_fee,
        "depreciation_fee": c.depreciation_fee, "consumable_fee": c.consumable_fee,
        "count": c.count, "quantity": c.quantity,
        "discount": c.discount, "amount": round(c.amount, 2),
    }


def schedule_to_dict(s) -> dict:
    return {
        "id": s.id, "order_id": s.order_id, "sample_id": s.sample_id,
        "sample_no": s.sample.sample_no if s.sample else "",
        "equipment_id": s.equipment_id,
        "equipment_name": s.equipment.name if s.equipment else "",
        "experiment_hours": s.experiment_hours, "transition_hours": s.transition_hours,
        "total_hours": s.total_hours,
        "plan_start": _dt(s.plan_start), "plan_end": _dt(s.plan_end),
        "actual_start": _dt(s.actual_start), "actual_end": _dt(s.actual_end),
        "status": s.status,
    }


def order_to_dict(o, with_detail=True) -> dict:
    d = {
        "id": o.id, "order_no": o.order_no, "experiment_no": o.experiment_no,
        "status": o.status,
        "entrust_org": o.entrust_org, "entrust_org_en": o.entrust_org_en,
        "entruster": o.entruster, "entruster_en": o.entruster_en,
        "sample_name": o.sample_name, "sample_name_en": o.sample_name_en,
        "test_item": o.test_item, "test_item_en": o.test_item_en,
        "test_basis": o.test_basis, "test_basis_en": o.test_basis_en,
        "test_stage": o.test_stage,
        "sample_model": o.sample_model, "customer_model": o.customer_model,
        "sample_count": o.sample_count, "sample_unit": o.sample_unit,
        "phone": o.phone, "email": o.email, "tracker": o.tracker, "tracker_email": o.tracker_email,
        "test_reason": o.test_reason, "report_lang": o.report_lang,
        "sample_status": o.sample_status, "storage_require": o.storage_require,
        "sample_dispose": o.sample_dispose, "test_condition": o.test_condition,
        "criteria": o.criteria, "remark": o.remark,
        "required_start": _dt(o.required_start), "created_at": _dt(o.created_at),
        "reviewer_id": o.reviewer_id, "review_at": _dt(o.review_at),
        "reject_reason": o.reject_reason, "total_cost": round(o.total_cost, 2),
        "finish_at": _dt(o.finish_at), "case_id": o.case_id,
        "images": [order_image_to_dict(i) for i in sorted(o.images, key=lambda x: x.id)],
    }
    if with_detail:
        d["samples"] = [sample_to_dict(s) for s in sorted(o.samples, key=lambda x: x.id)]
        d["costs"] = [cost_to_dict(c) for c in sorted(o.costs, key=lambda x: x.id)]
        d["schedules"] = [schedule_to_dict(s) for s in sorted(o.schedules, key=lambda x: x.id)]
        d["case_images"] = (
            [case_image_to_dict(i) for i in sorted(o.case.images, key=lambda x: x.id)]
            if o.case else []
        )
    return d


def equipment_to_dict(e) -> dict:
    return {
        "id": e.id, "name": e.name, "model": e.model, "code": e.code,
        "exp_type": e.exp_type, "status": e.status, "sort_order": e.sort_order,
        "valid_from": _dt(e.valid_from), "valid_to": _dt(e.valid_to),
        "open_fee": e.open_fee, "power_fee": e.power_fee, "depreciation_fee": e.depreciation_fee,
        "consumable_fee": e.consumable_fee, "unit_price": e.unit_price, "power_kw": e.power_kw,
        "remark": e.remark,
    }


def audit_to_dict(a) -> dict:
    return {
        "id": a.id, "user_id": a.user_id, "username": a.username, "action": a.action,
        "target_type": a.target_type, "target_id": a.target_id, "detail": a.detail,
        "created_at": _dt(a.created_at),
    }


def notification_to_dict(n) -> dict:
    return {
        "id": n.id, "user_id": n.user_id, "role": n.role, "title": n.title,
        "content": n.content, "order_id": n.order_id, "is_read": n.is_read,
        "created_at": _dt(n.created_at),
    }


def maintenance_to_dict(m) -> dict:
    return {
        "id": m.id, "equipment_id": m.equipment_id, "type": m.type,
        "date": _dt(m.date), "next_date": _dt(m.next_date), "cost": m.cost,
        "note": m.note, "operator": m.operator, "created_at": _dt(m.created_at),
    }


def customer_to_dict(c) -> dict:
    return {
        "id": c.id, "name": c.name, "contact": c.contact, "phone": c.phone,
        "email": c.email, "address": c.address, "remark": c.remark,
        "created_at": _dt(c.created_at),
    }


def report_to_dict(r) -> dict:
    return {
        "id": r.id, "order_id": r.order_id, "report_no": r.report_no,
        "report_type": r.report_type, "version": r.version, "status": r.status,
        "issuer_id": r.issuer_id, "issuer_name": r.issuer.name if r.issuer else "",
        "issued_at": _dt(r.issued_at), "created_at": _dt(r.created_at),
        "order_no": r.order.order_no if r.order else "",
        "experiment_no": r.order.experiment_no if r.order else "",
        "sample_name": r.order.sample_name if r.order else "",
        "entrust_org": r.order.entrust_org if r.order else "",
    }


def case_image_to_dict(img) -> dict:
    return {"id": img.id, "case_id": img.case_id, "filename": img.filename, "path": img.path}


def order_image_to_dict(img) -> dict:
    return {"id": img.id, "order_id": img.order_id, "filename": img.filename, "path": img.path}


def case_to_dict(c) -> dict:
    return {
        "id": c.id, "group_id": c.group_id, "group_name": c.group.name if c.group else "",
        "test_item": c.test_item, "test_condition": c.test_condition, "criteria": c.criteria,
        "count": c.count, "unit": c.unit,
        "remark": c.remark, "created_at": _dt(c.created_at), "updated_at": _dt(c.updated_at),
        "images": [case_image_to_dict(i) for i in sorted(c.images, key=lambda x: x.id)],
    }


def case_group_to_dict(g, with_cases: bool = False) -> dict:
    d = {
        "id": g.id, "name": g.name, "remark": g.remark, "created_at": _dt(g.created_at),
        "case_count": len(g.cases),
    }
    if with_cases:
        d["cases"] = [case_to_dict(c) for c in sorted(g.cases, key=lambda x: x.id)]
    return d
