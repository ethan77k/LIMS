"""密码哈希与 JWT 令牌。使用标准库 hashlib.pbkdf2_hmac，避免额外密码库依赖。"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta

import jwt

from .config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, SECRET_KEY

_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        iterations, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, role: str, name: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "name": name,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
