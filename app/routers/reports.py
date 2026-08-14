"""报告生成：实验委托记录单 + 检测报告（HTML，浏览器打印即可导出 PDF）。"""
import base64

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import log
from ..config import COMPANY_NAME, COMPANY_NAME_EN, LOGO_PATH
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Report, User
from ..notify import notify_entruster
from ..numbering import next_report_no
from ..schemas import ReportIssueRequest
from ..serializers import report_to_dict

router = APIRouter(prefix="/api/reports", tags=["reports"])

_BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Microsoft YaHei',Arial,sans-serif;color:#222;padding:30px;font-size:13px}
.report{max-width:820px;margin:0 auto;border:1px solid #000;padding:16px 20px}
.report-head{text-align:center;margin-bottom:4px}
.logo{display:block;margin:0 auto 8px;max-height:52px;max-width:100%}
.company{font-size:19px;font-weight:700;letter-spacing:2px}
.sub{text-align:center;font-size:12px;color:#555;margin:3px 0 2px}
.form-no{text-align:right;font-size:12px;margin-bottom:6px}
table{width:100%;border-collapse:collapse;margin-top:6px}
td,th{border:1px solid #000;padding:6px 8px;font-size:13px;vertical-align:top}
.lbl{background:#f2f2f2;font-weight:600;white-space:nowrap;width:96px}
.sig{height:46px}
.result-ok{color:#0a7d32;font-weight:700}
.result-ng{color:#c62828;font-weight:700}
@media print{body{padding:0}.report{border:none}}
.footer{font-size:11px;color:#666;margin-top:8px;line-height:1.6}
"""


def _logo_data_uri() -> str:
    """把 LOGO 转成 base64 内嵌，保证报告可离线打印。"""
    if LOGO_PATH.exists():
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
    return ""


def _report_head() -> str:
    logo = _logo_data_uri()
    img = f'<img class="logo" src="{logo}" alt="logo">' if logo else ""
    en = f'<div class="sub">{COMPANY_NAME_EN}</div>' if COMPANY_NAME_EN else ""
    return (
        f'<div class="report-head">{img}'
        f'<div class="company">{COMPANY_NAME}</div>{en}</div>'
    )


def _fmt(v):
    return v if v not in (None, "") else ""


def _dt_short(v):
    if not v:
        return ""
    return v.strftime("%Y-%m-%d")


def _dt_full(v):
    if not v:
        return ""
    return v.strftime("%Y-%m-%d %H:%M")


def render_entrust_html(o: EntrustOrder) -> str:
    sample_nos = ";".join(s.sample_no for s in o.samples)
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>试验委托记录单 {o.order_no}</title><style>{_BASE_CSS}</style></head><body>
<div class="report">
  {_report_head()}
  <div class="form-no">表-TC05-01A</div>
  <h2 style="text-align:center;font-size:16px;margin:6px 0">试验委托记录单</h2>
  <table>
    <tr><td class="lbl">委托单位</td><td colspan="4">{_fmt(o.entrust_org)}</td><td class="lbl">委托人</td><td colspan="3">{_fmt(o.entruster)}</td></tr>
    <tr><td class="lbl">样品型号</td><td colspan="4">{_fmt(o.sample_model)}</td><td class="lbl">样品数量</td><td colspan="3">{o.sample_count} {_fmt(o.sample_unit)}</td></tr>
    <tr><td class="lbl">样品名称</td><td colspan="4">{_fmt(o.sample_name)}</td><td class="lbl">客户型号</td><td colspan="3">{_fmt(o.customer_model)}</td></tr>
    <tr><td class="lbl">检测项目</td><td colspan="4">{_fmt(o.test_item)}</td><td class="lbl">项目名称</td><td colspan="3">{_fmt(o.test_item_en)}</td></tr>
    <tr><td class="lbl">检验依据</td><td colspan="9">{_fmt(o.test_basis) or '客户自定义条件'}</td></tr>
    <tr><td class="lbl">试验原因</td><td colspan="2">{_fmt(o.test_reason)}</td><td class="lbl">报告要求</td><td colspan="2">{_fmt(o.report_lang)}</td><td class="lbl">试验成本</td><td colspan="2">{o.total_cost} 元</td></tr>
    <tr><td class="lbl">样品状态</td><td colspan="2">{_fmt(o.sample_status)}</td><td class="lbl">存放要求</td><td colspan="2">{_fmt(o.storage_require)}</td><td class="lbl">样品处理</td><td colspan="2">{_fmt(o.sample_dispose)}</td></tr>
    <tr><td class="lbl">试验条件</td><td colspan="9">{_fmt(o.test_condition)}</td></tr>
    <tr><td class="lbl">备注</td><td colspan="9">{_fmt(o.remark)}</td></tr>
    <tr><td class="lbl">委托方签名</td><td colspan="2" class="sig"></td><td class="lbl">实验室签名</td><td colspan="3" class="sig"></td><td class="lbl">接收人</td><td colspan="2">{_fmt(o.entruster)}</td></tr>
    <tr><td class="lbl">接收日期</td><td colspan="2">{_dt_short(o.created_at)}</td><td class="lbl">试验编号</td><td colspan="3">{_fmt(o.experiment_no)}</td><td class="lbl">试验员</td><td colspan="2">{_fmt(o.reviewer.name if o.reviewer else '')}</td></tr>
    <tr><td class="lbl">样品编号</td><td colspan="9">{sample_nos}</td></tr>
    <tr><td class="lbl">试验时间</td><td colspan="9">{_dt_full(o.created_at)} ~ {_dt_full(o.finish_at)}</td></tr>
  </table>
  <div class="footer">说明：1、每个"检测项目"单独填写一份委托记录表；2、委托单审核接收后，双方负责人签名确认后安排试验。</div>
</div>
<script>window.print()</script></body></html>"""


def render_test_html(o: EntrustOrder, version: str = "常规") -> str:
    results_html = ""
    for s in o.samples:
        cls = "result-ok" if s.result == "OK" else ("result-ng" if s.result == "NG" else "")
        results_html += f'<td class="{cls}">{s.result or "-"}</td>'
    passed = "合格" if all(s.result == "OK" for s in o.samples) else "不合格"
    passed_en = "Passed" if passed == "合格" else "Failed"
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>检测报告 {o.experiment_no or o.order_no}</title><style>{_BASE_CSS}</style></head><body>
<div class="report">
  {_report_head()}
  <div class="form-no">表-TC11-02A</div>
  <h2 style="text-align:center;font-size:16px;margin:6px 0">检测报告 Test Report</h2>
  <table>
    <tr><td class="lbl" rowspan="3">预检查<br>Pre-check</td><td class="lbl">委托单编号</td><td colspan="4">{_fmt(o.order_no)}</td><td class="lbl">接收时间</td><td colspan="3">{_dt_short(o.created_at)}</td></tr>
    <tr><td class="lbl">样品检查</td><td colspan="8">{_fmt(o.sample_status)}</td></tr>
    <tr><td class="lbl">样品状态</td><td colspan="8">{_fmt(o.sample_status)}</td></tr>
    <tr><td class="lbl" rowspan="2">检验结果<br>Test Result</td>
      {''.join(f'<td style="text-align:center;font-weight:600">{i+1}#</td>' for i in range(len(o.samples))) or '<td></td>'}
    </tr>
    <tr>{results_html or '<td></td>'}</tr>
    <tr><td class="lbl">测试结果</td><td colspan="9" style="font-size:15px"><b>试验后样品外观正常。测试结果：{passed} Test Result: {passed_en}</b>（检验单位公章）</td></tr>
    <tr><td class="lbl">备注<br>Remark</td><td colspan="9">{_fmt(o.remark)}</td></tr>
    <tr><td class="lbl">拟制人</td><td colspan="2" class="sig"></td><td class="lbl">授权签字人</td><td colspan="3" class="sig">{_fmt(o.reviewer.name if o.reviewer else '')}</td><td class="lbl">签字人职务</td><td colspan="2">□中心主任 □技术负责人</td></tr>
    <tr><td class="lbl">审核人</td><td colspan="2">{_fmt(o.entruster)}</td><td class="lbl">签发日期</td><td colspan="5">{_dt_short(o.finish_at or o.review_at)}</td></tr>
  </table>
  <div class="footer">注：1、检测报告只对试验样品负责，实验室只对结果与标准的符合性进行判定，不对结果数据进行分析。2、每项检测只提供一份检测报告，复印或修改视为无效。</div>
</div>
<script>window.print()</script></body></html>"""


@router.get("/entrust/{order_id}", response_class=Response)
def entrust_report(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    o = db.get(EntrustOrder, order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    return Response(render_entrust_html(o), media_type="text/html")


@router.get("/test/{order_id}", response_class=Response)
def test_report(
    order_id: int,
    version: str = Query("常规", description="常规 / 检测"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    o = db.get(EntrustOrder, order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    return Response(render_test_html(o, version), media_type="text/html")


# ---------------------------------------------------------------------------
# 报告签发与归档
# ---------------------------------------------------------------------------
@router.post("/{order_id}/issue")
def issue_report(
    order_id: int,
    data: ReportIssueRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    o = db.get(EntrustOrder, order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    version = "" if data.report_type == "委托记录单" else data.version
    existing = (
        db.query(Report)
        .filter(
            Report.order_id == order_id,
            Report.report_type == data.report_type,
            Report.version == version,
            Report.status != "已作废",
        )
        .first()
    )
    if existing:
        return report_to_dict(existing)
    r = Report(
        order_id=order_id, report_no=next_report_no(db),
        report_type=data.report_type, version=version, status="已签发", issuer_id=user.id,
    )
    db.add(r)
    log(db, user, "签发报告", "report", None, f"{o.experiment_no or o.order_no} {data.report_type}")
    notify_entruster(db, o, "报告已签发", f"{o.experiment_no or o.order_no} {o.sample_name} 的{data.report_type}已签发")
    db.commit()
    db.refresh(r)
    return report_to_dict(r)


@router.get("/archive")
def archive(
    type: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = db.query(Report).join(EntrustOrder, Report.order_id == EntrustOrder.id)
    if type:
        q = q.filter(Report.report_type == type)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(
            Report.report_no.like(like),
            EntrustOrder.order_no.like(like),
            EntrustOrder.experiment_no.like(like),
            EntrustOrder.sample_name.like(like),
            EntrustOrder.entrust_org.like(like),
        ))
    rows = q.order_by(Report.id.desc()).all()
    return [report_to_dict(r) for r in rows]


@router.get("/archive/{report_id}/view", response_class=Response)
def archive_view(report_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    o = db.get(EntrustOrder, r.order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    html = render_entrust_html(o) if r.report_type == "委托记录单" else render_test_html(o, r.version or "常规")
    return Response(html, media_type="text/html")


@router.delete("/archive/{report_id}")
def archive_delete(report_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    log(db, user, "作废报告", "report", r.id, r.report_no)
    db.delete(r)
    db.commit()
    return {"message": "已作废"}
