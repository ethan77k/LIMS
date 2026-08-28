"""二维码 + 公开样品信息页（手机扫码查询，无需登录）。

扫码后跳转到 /q/{sample_id}，实时查询该样品的字段信息。
"""
import io
from html import escape

import qrcode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ..config import PUBLIC_BASE_URL
from ..database import get_db
from ..models import Sample

router = APIRouter(tags=["qrcode"])


def _get_sample(db: Session, sample_id: int) -> Sample:
    s = db.get(Sample, sample_id)
    if s is None:
        raise HTTPException(404, "样品不存在")
    return s


@router.get("/q/{sample_id}/qr.png")
def sample_qrcode(sample_id: int, db: Session = Depends(get_db)):
    """返回样品二维码 PNG（内容为公开查询页 URL）。"""
    _get_sample(db, sample_id)
    url = f"{PUBLIC_BASE_URL}/q/{sample_id}"
    img = qrcode.make(url, box_size=10, border=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/q/{sample_id}")
def sample_public_page(sample_id: int, db: Session = Depends(get_db)):
    """手机扫码后展示的样品信息页（实时查询）。"""
    s = _get_sample(db, sample_id)
    b = s.batch
    rows = [
        ("批次号", b.batch_no if b else ""),
        ("样品编号", s.sample_no),
        ("SN号", s.sn or "-"),
        ("DHD型号", b.sample_model if b else ""),
        ("客户型号", b.customer_model if b else ""),
        ("样品名称", b.sample_name if b else ""),
        ("实时状态", s.status),
        ("状况", s.condition or "-"),
    ]
    rows_html = "".join(
        f'<tr><th>{escape(k)}</th><td>{escape(v or "-")}</td></tr>' for k, v in rows
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>样品查询 {escape(s.sample_no)}</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ font-family:'Microsoft YaHei',Arial,sans-serif; background:#f2f5f9; margin:0; padding:20px; }}
  .card {{ max-width:480px; margin:0 auto; background:#fff; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.08); overflow:hidden; }}
  .head {{ background:#1e5aa8; color:#fff; padding:16px 20px; font-size:18px; font-weight:700; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ padding:12px 20px; text-align:left; border-bottom:1px solid #eef1f5; font-size:15px; }}
  th {{ width:40%; color:#64748b; font-weight:600; background:#f8fafc; }}
  td {{ font-weight:600; word-break:break-all; }}
  .foot {{ padding:12px 20px; color:#94a3b8; font-size:12px; }}
</style></head><body>
<div class="card">
  <div class="head">样品信息</div>
  <table>{rows_html}</table>
  <div class="foot">数据实时更新 · 请以系统最新状态为准</div>
</div>
</body></html>"""
    return HTMLResponse(content=html)
