"""测试用例库：按客户分组，维护「检测项目 / 试验条件 / 判定标准」与参考图片。

全实验室共享（委托人 / 实验员 / 管理员均可查看与维护）。
"""
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session, selectinload

from ..config import UPLOAD_DIR
from ..database import get_db
from ..deps import require_roles
from ..models import TestCase, TestCaseGroup, TestCaseImage, User
from ..schemas import TestCaseCreate, TestCaseGroupCreate, TestCaseGroupUpdate, TestCaseUpdate
from ..serializers import case_group_to_dict, case_image_to_dict, case_to_dict

router = APIRouter(prefix="/api/cases", tags=["cases"])

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _case_image_dir():
    d = UPLOAD_DIR / "cases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _remove_image_file(path: str) -> None:
    if not path:
        return
    try:
        (UPLOAD_DIR / "cases" / os.path.basename(path)).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 分组
# ---------------------------------------------------------------------------
@router.get("/groups")
def list_groups(
    with_cases: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter", "entruster")),
):
    q = db.query(TestCaseGroup)
    if with_cases:
        q = q.options(selectinload(TestCaseGroup.cases).selectinload(TestCase.images))
    else:
        q = q.options(selectinload(TestCaseGroup.cases))
    groups = q.order_by(TestCaseGroup.id).all()
    return [case_group_to_dict(g, with_cases=with_cases) for g in groups]


@router.post("/groups")
def create_group(data: TestCaseGroupCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    if not (data.name or "").strip():
        raise HTTPException(400, "分组名（客户名）不能为空")
    g = TestCaseGroup(name=data.name.strip(), remark=data.remark)
    db.add(g)
    db.commit()
    db.refresh(g)
    return case_group_to_dict(g)


@router.put("/groups/{group_id}")
def update_group(group_id: int, data: TestCaseGroupUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    g = db.get(TestCaseGroup, group_id)
    if g is None:
        raise HTTPException(404, "分组不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(g, field, value)
    db.commit()
    return case_group_to_dict(g)


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    g = db.get(TestCaseGroup, group_id)
    if g is None:
        raise HTTPException(404, "分组不存在")
    for case in g.cases:
        for img in case.images:
            _remove_image_file(img.path)
    db.delete(g)  # cascade 删除用例与图片记录
    db.commit()
    return {"message": "删除成功"}


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
@router.get("")
def list_cases(
    group_id: int | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter", "entruster")),
):
    q = db.query(TestCase).options(selectinload(TestCase.images))
    if group_id:
        q = q.filter(TestCase.group_id == group_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(TestCase.test_item.like(like) | TestCase.criteria.like(like) | TestCase.remark.like(like))
    cases = q.order_by(TestCase.id.desc()).all()
    return [case_to_dict(c) for c in cases]


@router.post("")
def create_case(data: TestCaseCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    if db.get(TestCaseGroup, data.group_id) is None:
        raise HTTPException(404, "分组不存在")
    c = TestCase(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return case_to_dict(c)


@router.put("/{case_id}")
def update_case(case_id: int, data: TestCaseUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    c = db.get(TestCase, case_id)
    if c is None:
        raise HTTPException(404, "用例不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return case_to_dict(c)


@router.delete("/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    c = db.get(TestCase, case_id)
    if c is None:
        raise HTTPException(404, "用例不存在")
    for img in c.images:
        _remove_image_file(img.path)
    db.delete(c)  # cascade 删除图片记录
    db.commit()
    return {"message": "删除成功"}


# ---------------------------------------------------------------------------
# 图片
# ---------------------------------------------------------------------------
@router.post("/{case_id}/images")
async def upload_case_image(
    case_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter", "entruster")),
):
    case = db.get(TestCase, case_id)
    if case is None:
        raise HTTPException(404, "用例不存在")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, "仅支持图片格式：jpg / png / gif / webp / bmp")
    content = await file.read()
    if not content:
        raise HTTPException(400, "图片内容为空")
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(400, "图片大小不能超过 5MB")
    stored_name = f"{uuid.uuid4().hex}{ext}"
    (_case_image_dir() / stored_name).write_bytes(content)
    img = TestCaseImage(
        case_id=case_id, filename=file.filename or stored_name,
        path=f"/uploads/cases/{stored_name}",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return case_image_to_dict(img)


@router.delete("/images/{image_id}")
def delete_case_image(image_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter", "entruster"))):
    img = db.get(TestCaseImage, image_id)
    if img is None:
        raise HTTPException(404, "图片不存在")
    _remove_image_file(img.path)
    db.delete(img)
    db.commit()
    return {"message": "删除成功"}
