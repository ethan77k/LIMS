"""OnlyOffice 文档存储服务：下载 / 保存回调。

由 OnlyOffice Document Server（服务器端）调用，不依赖 LIMS 会话鉴权，
而是用「HMAC 签名的文档 key」（下载）+「OnlyOffice JWT」（回调）互信。
"""
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import onlyoffice
from ..database import get_db
from . import export as export_module
from . import reports

router = APIRouter(prefix="/api/oo", tags=["onlyoffice"])

_DOCX_MT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/info")
def oo_info():
    """前端据此判断是否显示「在线编辑」入口，并获取编辑器脚本地址。"""
    return {"enabled": onlyoffice.is_enabled(), "url": onlyoffice.ONLYOFFICE_URL}


@router.get("/download")
def oo_download(key: str = Query(...), db=Depends(get_db)):
    """Document Server 拉取文档（真 .docx / .xlsx）。key 签名即鉴权。"""
    if not onlyoffice.is_enabled():
        raise HTTPException(503, "未配置 OnlyOffice")
    try:
        payload = onlyoffice.parse_key(key)
    except ValueError:
        raise HTTPException(400, "非法文档 key")
    kind = payload.get("kind")
    if kind == "report":
        data, _name = reports.build_report_docx(db, payload["order_id"], payload["report_type"], payload["version"])
        return Response(data, media_type=_DOCX_MT)
    if kind == "export":
        fp = onlyoffice.work_file(key, "xlsx")
        if not fp.exists():
            fp.write_bytes(export_module.build_export_xlsx(db, payload.get("export")))
        return Response(fp.read_bytes(), media_type=_XLSX_MT)
    raise HTTPException(404, "未知文档类型")


@router.post("/callback")
async def oo_callback(request: Request, db=Depends(get_db)):
    """Document Server 保存回调：status 2/6 时下载编辑后的文档并持久化。"""
    if not onlyoffice.is_enabled():
        return {"error": 0}
    try:
        body = await request.json()
    except Exception:
        return {"error": 1}
    token = (body.get("token") or "").strip() or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return {"error": 1}
    try:
        onlyoffice.verify_token(token)
    except Exception:
        return {"error": 1}

    status = body.get("status")
    key = body.get("key") or ""
    if status not in (2, 6) or not key:
        return {"error": 0}
    try:
        payload = onlyoffice.parse_key(key)
    except ValueError:
        return {"error": 1}

    url = body.get("url")
    if not url:
        return {"error": 1}
    data = _download(url, token)
    if data is None:
        return {"error": 1}

    if payload.get("kind") == "report":
        reports.save_report_docx(db, payload["order_id"], payload["report_type"], payload["version"], data)
    elif payload.get("kind") == "export":
        onlyoffice.work_file(key, "xlsx").write_bytes(data)
    return {"error": 0}


def _download(url: str, token: str) -> bytes | None:
    """从 Document Server 下载编辑后的文件（JWT 时带 Authorization 头，失败则裸取）。"""
    for with_auth in (True, False):
        try:
            req = urllib.request.Request(url)
            if with_auth and token:
                req.add_header("Authorization", "Bearer " + token)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception:
            if not with_auth:
                return None
    return None
