"""全局配置。"""
import os
import socket
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


def _lan_ip() -> str:
    """探测本机局域网 IP（UDP 连接不实际发包，无需外网）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# 二维码扫码后跳转的公开基址：手机需与服务器同网段，默认自动探测局域网 IP。
# 可通过环境变量 LIMS_PUBLIC_URL 覆盖（如 "http://192.168.1.10:8000"）。
PUBLIC_BASE_URL = os.getenv("LIMS_PUBLIC_URL", "").rstrip("/") or f"http://{_lan_ip()}:8000"


# ---------------------------------------------------------------------------
# OnlyOffice 在线编辑（可选集成）：未配置 ONLYOFFICE_URL 时自动禁用，
# 报告编辑回退到「本机 Word COM / 浏览器 HTML 编辑」，不影响现有功能。
# ---------------------------------------------------------------------------
# OnlyOffice Document Server 对外地址（浏览器访问用），如 "http://192.168.1.10:8088"
ONLYOFFICE_URL = os.getenv("LIMS_ONLYOFFICE_URL", "").rstrip("/")
# 与 OnlyOffice 容器一致的 JWT 密钥（容器 -e JWT_SECRET 的值）；未配置则视为未启用
ONLYOFFICE_JWT_SECRET = os.getenv("LIMS_ONLYOFFICE_JWT_SECRET", "")
# OnlyOffice 工作文件目录：落盘会被 TSD 加密，必须放在明文区 D:/temp 下
ONLYOFFICE_WORK_DIR = Path(os.getenv("LIMS_ONLYOFFICE_WORK_DIR", "D:/temp/lims_oo"))
# LIMS 对外基址：OnlyOffice 容器（服务器端）用它回调/下载文档，须为其可访问的地址（默认局域网 IP）
ONLYOFFICE_CALLBACK_BASE = os.getenv("LIMS_ONLYOFFICE_CALLBACK_BASE", "").rstrip("/") or PUBLIC_BASE_URL
