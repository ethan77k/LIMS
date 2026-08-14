"""认证与用户管理。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..audit import log
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..models import User
from ..schemas import ChangePasswordRequest, LoginRequest, TokenResponse, UserCreate, UserOut, UserUpdate
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if user is None or not verify_password(data.password, user.password_hash):
        log(db, None, "登录失败", "user", None, data.username)
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(401, "账号已停用")
    token = create_access_token(user.id, user.role, user.name)
    log(db, user, "登录", "user", user.id)
    db.commit()
    return TokenResponse(access_token=token, role=user.role, name=user.name, username=user.username)


@router.post("/change-password")
def change_password(data: ChangePasswordRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    user.password_hash = hash_password(data.new_password)
    log(db, user, "修改密码", "user", user.id)
    db.commit()
    return {"message": "密码已修改"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "experimenter"))):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db), operator: User = Depends(require_roles("admin"))):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=data.username, password_hash=hash_password(data.password),
        name=data.name, role=data.role, department=data.department,
        email=data.email, phone=data.phone,
    )
    db.add(user)
    log(db, operator, "新增用户", "user", None, f"{data.username}（{data.role}）")
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), operator: User = Depends(require_roles("admin"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "password" and value:
            user.password_hash = hash_password(value)
        elif field != "password":
            setattr(user, field, value)
    log(db, operator, "修改用户", "user", user.id, f"{user.username} 角色/属性变更")
    db.commit()
    db.refresh(user)
    return user
