"""全局配置。"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 数据库文件（放在项目根目录下，方便备份）
DATABASE_URL = os.getenv("LIMS_DATABASE_URL", f"sqlite:///{BASE_DIR / 'lims.db'}")

# JWT 密钥（生产环境请通过环境变量 LIMS_SECRET_KEY 覆盖）
SECRET_KEY = os.getenv("LIMS_SECRET_KEY", "change-me-in-production-please-2024")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 小时

# 静态文件目录
STATIC_DIR = BASE_DIR / "static"

# 上传文件目录（测试用例图片等，位于 static 下便于直接访问）
UPLOAD_DIR = STATIC_DIR / "uploads"

# 报告抬头：公司名（用于文字显示）与 LOGO 路径
COMPANY_NAME = os.getenv("LIMS_COMPANY_NAME", "得辉达集团")
COMPANY_NAME_EN = os.getenv("LIMS_COMPANY_NAME_EN", "")
LOGO_PATH = STATIC_DIR / "logo.png"
