"""自定义报告模板库：上传 / 列表 / 设默认 / 删除（.docx 二进制存 DB，避免落盘被 TSD 加密）。"""
import os

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import require_roles
from ..models import ReportTemplate, User
from ..serializers import _dt

router = APIRouter(prefix="/api/report-templates", tags=["report-templates"])

_MAX_TEMPLATE_BYTES = 10 * 1024 * 1024  # 10MB


def _template_to_dict(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "filename": t.filename,
        "is_default": t.is_default,
        "created_at": _dt(t.created_at),
    }


@router.get("")
def list_templates(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    rows = db.query(ReportTemplate).order_by(ReportTemplate.id.desc()).all()
    return [_template_to_dict(t) for t in rows]


@router.post("")
async def upload_template(
    name: str = Form(...),
    file: UploadFile = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "请填写模板名称")
    if file is None:
        raise HTTPException(400, "请选择要上传的 .docx 模板文件")
    if os.path.splitext(file.filename or "")[1].lower() != ".docx":
        raise HTTPException(400, "仅支持 .docx 格式的 Word 模板")
    if db.query(ReportTemplate).filter(ReportTemplate.name == name).first():
        raise HTTPException(400, "模板名称已存在，请换一个名称")
    content = await file.read()
    if not content:
        raise HTTPException(400, "模板文件内容为空")
    if len(content) > _MAX_TEMPLATE_BYTES:
        raise HTTPException(400, "模板文件不能超过 10MB")

    # 首个模板自动设为默认
    is_default = db.query(ReportTemplate).count() == 0
    t = ReportTemplate(name=name, filename=file.filename or "", content=content, is_default=is_default)
    db.add(t)
    log(db, user, "上传报告模板", "report_template", None, name)
    db.commit()
    db.refresh(t)
    return _template_to_dict(t)


@router.post("/{template_id}/default")
def set_default_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    t = db.get(ReportTemplate, template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    db.query(ReportTemplate).filter(ReportTemplate.id != template_id).update({"is_default": False})
    t.is_default = True
    log(db, user, "设置默认报告模板", "report_template", t.id, t.name)
    db.commit()
    return _template_to_dict(t)


@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    t = db.get(ReportTemplate, template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    name = t.name
    db.delete(t)
    log(db, user, "删除报告模板", "report_template", template_id, name)
    db.commit()
    return {"message": "已删除"}
