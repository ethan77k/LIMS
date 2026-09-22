"""报告生成：实验委托记录单 + 检测报告（HTML，浏览器打印即可导出 PDF / 导出 Word）。"""
import base64
import html as _html
import io
import os
import re
import uuid
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from ..audit import log
from ..config import COMPANY_NAME, COMPANY_NAME_EN, LOGO_PATH, UPLOAD_DIR
from .. import onlyoffice
from ..database import get_db
from ..deps import require_roles
from ..models import EntrustOrder, Report, ReportDraft, ReportTemplate, Schedule, User
from ..notify import notify, notify_entruster
from ..numbering import next_report_no, retry_on_number_conflict
from ..schemas import ReportDraftRequest, ReportIssueRequest, ReportRejectRequest
from ..serializers import report_to_dict

router = APIRouter(prefix="/api/reports", tags=["reports"])

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Word 编辑的临时文件目录：唯一明文区（桌面/C盘根落盘会被 TSD 加密）
_WORD_TMP_DIR = Path("D:/temp")


def _report_image_dir():
    d = UPLOAD_DIR / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d

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
.qm-head{border:none;margin-bottom:8px}
.qm-head td{border:none;padding:2px 6px;vertical-align:middle}
.qm-logo{width:120px;text-align:center}
.qm-title{font-size:20px;font-weight:700;letter-spacing:1px;text-align:center}
.qm-sec{background:#eef1f5;font-weight:700;text-align:center}
.qm-verdict{font-size:18px;font-weight:700;text-align:center;vertical-align:middle}
.qm-img{height:110px;vertical-align:top}
.qm-tall{height:44px}
.edit-toolbar{position:sticky;top:0;z-index:50;background:#fff;border-bottom:1px solid #e2e8f0;padding:8px 12px;margin:-30px -30px 16px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;font-family:'Microsoft YaHei',Arial,sans-serif}
.edit-toolbar button{font-size:12px;padding:4px 9px;border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc;cursor:pointer;color:#26334d}
.edit-toolbar button:hover{background:#e8eef6}
.edit-toolbar .tb-label{font-size:12px;color:#6b7a90;margin:0 6px 0 2px}
.photo-grid{width:100%;border-collapse:collapse;margin-top:6px}
.photo-grid td{border:1px solid #000;padding:4px}
.photo-cell{width:33.3%;vertical-align:top}
.photo-box{height:120px;background:#fafafa;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;cursor:pointer}
.photo-box img{max-width:100%;max-height:100%;object-fit:contain}
.photo-empty .photo-box::after{content:'＋ 点击上传';color:#9aa8bd;font-size:12px}
.photo-note{min-height:26px;margin-top:3px;font-size:12px;color:#333;border-top:1px dashed #cbd5e1;padding:2px 4px}
.photo-note:empty::before{content:'备注';color:#c0c8d4}
.photo-upload-btn{font-size:12px;padding:2px 8px;border:1px solid #1e5aa8;border-radius:4px;background:#e8f0fb;color:#1e5aa8;cursor:pointer}
.photo-remove{position:absolute;top:2px;right:2px;width:18px;height:18px;line-height:16px;font-size:13px;border:none;border-radius:50%;background:rgba(198,40,40,.85);color:#fff;cursor:pointer;padding:0}
@media print{.edit-toolbar,.photo-upload-btn,.photo-remove{display:none!important}}
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


def _report_head_qm46() -> str:
    """QM-F-46 可靠性测试报告英文头部（照搬 Word 模板）。"""
    logo = _logo_data_uri()
    img = f'<img class="logo" src="{logo}" alt="logo">' if logo else ""
    return (
        f'<table class="qm-head">'
        f'<tr><td class="qm-logo" rowspan="4">{img}</td>'
        f'<td class="qm-title" rowspan="4">Reliability Test Report</td>'
        f'<td style="width:80px">文件编号</td><td>【QM-F-46】【2.0】</td></tr>'
        f'<tr><td>版本</td><td></td></tr>'
        f'<tr><td>页数</td><td>1 / 1</td></tr>'
        f'<tr><td>报告编号</td><td></td></tr>'
        f'</table>'
    )


def _fmt(v):
    """None/空串统一为 ""，并对 HTML 特殊字符转义（防存储型 XSS）。"""
    return _html.escape(str(v)) if v not in (None, "") else ""


def _dt_short(v):
    if not v:
        return ""
    return v.strftime("%Y-%m-%d")


def _dt_full(v):
    if not v:
        return ""
    return v.strftime("%Y-%m-%d %H:%M")


def _range(a, b):
    """起止日期合并为 `a ~ b`，单侧为空则只显示有值的一侧，两侧皆空返回空串。"""
    a, b = _dt_short(a), _dt_short(b)
    if a and b:
        return f"{a} ~ {b}"
    return a or b


# ---------------------------------------------------------------------------
# 报告正文 HTML 清洗（防 XSS：白名单标签/属性，剔除脚本、事件、危险 URL）
# ---------------------------------------------------------------------------
_VOID_TAGS = {"br", "img", "hr"}
_BLOCK_TAGS = {"script", "style", "iframe", "object", "embed", "link", "meta", "base",
               "form", "input", "textarea", "select", "button", "svg", "math", "noscript", "template"}
# 无闭合标签的块级危险标签：单独丢弃，不能进入块级跳过计数（否则 _block_depth 永不自减，
# 会把其后的全部正文吞掉）。
_BLOCK_VOID_TAGS = {"meta", "link", "base", "input", "embed"}
_ALLOW_TAGS = {"div", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption",
               "h1", "h2", "h3", "h4", "h5", "h6", "p", "b", "strong", "i", "em", "u", "s",
               "span", "br", "img", "a", "ul", "ol", "li", "hr", "sub", "sup", "small"}
_ALLOW_ATTRS = {"class", "colspan", "rowspan", "style", "src", "alt", "title", "width", "height", "href"}


class _HTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out = []
        self._block_depth = 0

    def _attrs(self, attrs):
        parts = []
        for k, v in attrs:
            k = k.lower()
            if k not in _ALLOW_ATTRS:
                continue
            if k in ("href", "src") and v and v.strip().lower().startswith(("javascript:", "data:text/html", "vbscript:")):
                continue
            if k == "style" and ("expression" in v.lower() or "javascript:" in v.lower()):
                continue
            parts.append(f' {k}="{_html.escape(v, quote=True)}"')
        return "".join(parts)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _BLOCK_VOID_TAGS:
            return
        if tag in _BLOCK_TAGS:
            self._block_depth += 1
            return
        if self._block_depth:
            return
        if tag in _VOID_TAGS:
            if tag in _ALLOW_TAGS:
                self._out.append(f"<{tag}{self._attrs(attrs)}>")
            return
        if tag in _ALLOW_TAGS:
            self._out.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            if self._block_depth:
                self._block_depth -= 1
            return
        if self._block_depth:
            return
        if tag in _ALLOW_TAGS and tag not in _VOID_TAGS:
            self._out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._block_depth:
            self._out.append(_html.escape(data))


def _sanitize_html(value: str) -> str:
    p = _HTMLSanitizer()
    try:
        p.feed(value or "")
        p.close()
    except Exception:
        return ""
    return "".join(p._out)


_EDIT_TOOLBAR = """<div class="edit-toolbar" contenteditable="false">
  <span class="tb-label">表格</span>
  <button type="button" data-op="row-above">上方插行</button>
  <button type="button" data-op="row-below">下方插行</button>
  <button type="button" data-op="row-del">删除行</button>
  <button type="button" data-op="col-left">左侧插列</button>
  <button type="button" data-op="col-right">右侧插列</button>
  <button type="button" data-op="col-del">删除列</button>
  <button type="button" data-op="merge">合并单元格</button>
  <button type="button" data-op="split">拆分单元格</button>
  <button type="button" data-op="table-add">插入表格</button>
  <button type="button" data-op="table-del">删除表格</button>
  <span class="tb-label">图片</span>
  <button type="button" data-op="img-insert">插入图片</button>
  <span class="tb-label" style="margin-left:auto;color:#b7791f">照片区：点「＋上传」添加，拖动照片排序，图下写备注</span>
</div>"""


_EDITOR_SCRIPT = """<script>
(function(){
  function token(){ return localStorage.getItem('lims_token') || ''; }
  function upload(file){
    var fd = new FormData(); fd.append('file', file);
    return fetch('/api/reports/upload', {method:'POST', headers:{'Authorization':'Bearer '+token()}, body:fd})
      .then(function(r){ return r.json().then(function(d){ if(!r.ok) throw new Error(d.detail || '上传失败'); return d.url; }); });
  }
  function pickFile(cb, multiple){
    var inp = document.createElement('input'); inp.type='file'; inp.accept='image/*'; inp.multiple=!!multiple; inp.style.display='none';
    document.body.appendChild(inp);
    inp.addEventListener('change', function(){
      var files = Array.from(inp.files || []); inp.remove();
      if(!files.length) return;
      var chain = Promise.resolve();
      files.forEach(function(f){ chain = chain.then(function(){ return upload(f).then(function(url){ cb(url); }); }); });
      chain.catch(function(e){ alert(e.message || '上传失败'); });
    });
    inp.click();
  }
  function selCell(){
    var sel = document.getSelection(); if(!sel || !sel.rangeCount) return null;
    var n = sel.anchorNode;
    var el = n && n.nodeType === 3 ? n.parentElement : (n && n.nodeType === 1 ? n : null);
    return el ? el.closest('td,th') : null;
  }
  function insertRow(above){
    var c = selCell(); if(!c) return alert('请先把光标放到要操作的表格单元格内');
    var tr = c.closest('tr'); if(!tr) return;
    var clone = tr.cloneNode(true);
    clone.querySelectorAll('td,th').forEach(function(td){ td.innerHTML=''; if((td.getAttribute('rowspan')|0)>1) td.setAttribute('rowspan','1'); });
    clone.querySelectorAll('td,th').forEach(function(td){ if(!td.innerHTML.trim()) td.innerHTML='&nbsp;'; });
    if(above) tr.parentElement.insertBefore(clone, tr); else tr.parentElement.insertBefore(clone, tr.nextSibling);
  }
  function deleteRow(){
    var c = selCell(); if(!c) return alert('请先把光标放到要删除的行内');
    var tr = c.closest('tr'); if(!tr) return;
    var tbody = tr.parentElement, table = tr.closest('table');
    if(tbody.querySelectorAll('tr').length <= 1){ if(table) table.remove(); return; }
    tr.remove();
  }
  function insertCol(right){
    var c = selCell(); if(!c) return alert('请先把光标放到要插入列的单元格内');
    var tr = c.closest('tr'); if(!tr) return;
    var idx = Array.from(tr.children).indexOf(c) + (right ? 1 : 0);
    tr.closest('table').querySelectorAll('tr').forEach(function(r){
      var cs = Array.from(r.children);
      var td = document.createElement('td'); td.innerHTML='&nbsp;';
      if(idx >= cs.length) r.appendChild(td); else r.insertBefore(td, cs[idx]);
    });
  }
  function deleteCol(){
    var c = selCell(); if(!c) return alert('请先把光标放到要删除的列内');
    var tr = c.closest('tr'); if(!tr) return;
    var idx = Array.from(tr.children).indexOf(c);
    tr.closest('table').querySelectorAll('tr').forEach(function(r){
      var cs = Array.from(r.children);
      if(cs[idx]) cs[idx].remove();
    });
  }
  function mergeCell(){
    var c = selCell(); if(!c) return alert('请先把光标放到要合并的单元格内');
    var next = c.nextElementSibling;
    if(next && (next.tagName==='TD' || next.tagName==='TH')){
      var span = ((c.getAttribute('colspan')|0)||1) + ((next.getAttribute('colspan')|0)||1);
      c.setAttribute('colspan', String(span));
      var nh = next.innerHTML;
      if(nh && nh !== '&nbsp;') c.innerHTML = c.innerHTML + nh;
      next.remove();
    } else { alert('右侧没有可合并的单元格'); }
  }
  function splitCell(){
    var c = selCell(); if(!c) return alert('请先把光标放到要拆分的单元格内');
    var n = (c.getAttribute('colspan')|0)||1;
    if(n <= 1) return alert('该单元格未合并');
    c.setAttribute('colspan','1');
    for(var i=1;i<n;i++){ var td=document.createElement('td'); td.innerHTML='&nbsp;'; c.after(td); }
  }
  function insertTable(){
    var sel = document.getSelection();
    var t = document.createElement('table');
    var inner='';
    for(var i=0;i<3;i++){ inner+='<tr>'; for(var j=0;j<3;j++) inner+='<td>&nbsp;</td>'; inner+='</tr>'; }
    t.innerHTML = inner;
    var report = document.querySelector('.report');
    if(sel.rangeCount){ var rng = sel.getRangeAt(0); rng.deleteContents(); rng.insertNode(t); }
    else if(report){ report.appendChild(t); }
  }
  function deleteTable(){
    var c = selCell(); if(!c) return alert('请先把光标放到要删除的表格内');
    var t = c.closest('table'); if(!t) return;
    if(t.classList.contains('photo-grid')) return alert('照片区请用「删除行」或移除照片');
    t.remove();
  }
  function insertImage(){
    pickFile(function(url){
      var sel = document.getSelection();
      var img = document.createElement('img'); img.src = url; img.style.maxWidth='100%';
      var report = document.querySelector('.report');
      if(sel.rangeCount){ var rng = sel.getRangeAt(0); rng.deleteContents(); rng.insertNode(img); }
      else if(report){ report.appendChild(img); }
    }, true);
  }
  function makeEmptyCell(){
    var td = document.createElement('td'); td.className = 'photo-cell photo-empty';
    td.innerHTML = '<div class="photo-box" contenteditable="false"></div><div class="photo-note" contenteditable="true"></div>';
    return td;
  }
  function fillCell(cell, url){
    cell.classList.remove('photo-empty');
    var box = cell.querySelector('.photo-box'); box.innerHTML='';
    box.setAttribute('contenteditable','false'); box.setAttribute('draggable','true');
    var img = document.createElement('img'); img.src = url; img.setAttribute('draggable','false'); box.appendChild(img);
    var rm = document.createElement('button'); rm.type='button'; rm.className='photo-remove';
    rm.setAttribute('contenteditable','false'); rm.setAttribute('data-edit-only','1'); rm.textContent='×';
    rm.addEventListener('click', function(ev){ ev.preventDefault(); ev.stopPropagation(); clearCell(cell); });
    box.appendChild(rm);
  }
  function clearCell(cell){
    cell.querySelector('.photo-box').innerHTML='';
    var note = cell.querySelector('.photo-note'); if(note) note.innerHTML='';
    cell.classList.add('photo-empty');
  }
  function normalizeCell(cell){
    var box = cell.querySelector('.photo-box'); if(!box) return;
    box.setAttribute('contenteditable','false');
    var hasImg = !!box.querySelector('img');
    if(hasImg){
      cell.classList.remove('photo-empty');
      box.setAttribute('draggable','true');
      box.querySelectorAll('img').forEach(function(im){ im.setAttribute('draggable','false'); });
      if(!box.querySelector('.photo-remove')){
        var rm = document.createElement('button'); rm.type='button'; rm.className='photo-remove';
        rm.setAttribute('contenteditable','false'); rm.setAttribute('data-edit-only','1'); rm.textContent='×';
        rm.addEventListener('click', function(ev){ ev.preventDefault(); ev.stopPropagation(); clearCell(cell); });
        box.appendChild(rm);
      }
    } else {
      box.removeAttribute('draggable'); box.innerHTML='';
      cell.classList.add('photo-empty');
    }
  }
  function addPhoto(grid, url){
    var empty = grid.querySelector('.photo-cell.photo-empty');
    if(!empty){
      var tr = document.createElement('tr'); tr.className='photo-row';
      for(var i=0;i<3;i++) tr.appendChild(makeEmptyCell());
      (grid.tBodies[0] || grid).appendChild(tr);
      empty = tr.querySelector('.photo-cell.photo-empty');
    }
    fillCell(empty, url);
  }
  var dragSrc = null;
  function bindPhotoGrid(grid){
    grid.querySelectorAll('.photo-cell').forEach(normalizeCell);
    grid.addEventListener('click', function(ev){
      var empty = ev.target.closest('.photo-cell.photo-empty');
      if(empty && empty.closest('.photo-grid') === grid){
        pickFile(function(url){ fillCell(empty, url); }, false);
      }
    });
    grid.addEventListener('dragstart', function(ev){
      var cell = ev.target.closest('.photo-cell');
      if(cell && !cell.classList.contains('photo-empty')){ dragSrc = cell; ev.dataTransfer.effectAllowed='move'; }
    });
    grid.addEventListener('dragover', function(ev){ ev.preventDefault(); ev.dataTransfer.dropEffect='move'; });
    grid.addEventListener('drop', function(ev){
      ev.preventDefault();
      var target = ev.target.closest('.photo-cell');
      if(!target || !dragSrc || target === dragSrc) return;
      var sHtml = dragSrc.innerHTML, tHtml = target.innerHTML;
      var sEmpty = dragSrc.classList.contains('photo-empty'), tEmpty = target.classList.contains('photo-empty');
      dragSrc.innerHTML = tHtml; target.innerHTML = sHtml;
      dragSrc.classList.toggle('photo-empty', tEmpty);
      target.classList.toggle('photo-empty', sEmpty);
      dragSrc = null;
    });
    var headTd = grid.querySelector('tr:first-child td');
    if(headTd && !headTd.querySelector('.photo-upload-btn')){
      var btn = document.createElement('button'); btn.type='button'; btn.className='photo-upload-btn';
      btn.setAttribute('contenteditable','false'); btn.setAttribute('data-edit-only','1'); btn.textContent='＋ 上传照片';
      btn.addEventListener('click', function(ev){ ev.preventDefault(); ev.stopPropagation(); pickFile(function(url){ addPhoto(grid, url); }, true); });
      headTd.appendChild(document.createTextNode(' ')); headTd.appendChild(btn);
    }
  }
  var ops = {
    'row-above': function(){ insertRow(true); }, 'row-below': function(){ insertRow(false); }, 'row-del': deleteRow,
    'col-left': function(){ insertCol(false); }, 'col-right': function(){ insertCol(true); }, 'col-del': deleteCol,
    'merge': mergeCell, 'split': splitCell, 'table-add': insertTable, 'table-del': deleteTable, 'img-insert': insertImage
  };
  document.querySelectorAll('[data-op]').forEach(function(btn){
    btn.addEventListener('mousedown', function(ev){ ev.preventDefault(); });
    btn.addEventListener('click', function(ev){ ev.preventDefault(); var f = ops[btn.getAttribute('data-op')]; if(f) f(); });
  });
  document.querySelectorAll('.photo-grid').forEach(bindPhotoGrid);
})();
</script>"""


def _wrap_report(body: str, title: str, *, editable: bool = False, auto_print: bool = True) -> str:
    """把报告正文包成独立 HTML 文档（可打印 / 可编辑）。"""
    editable_attr = ' contenteditable="true"' if editable else ""
    toolbar = _EDIT_TOOLBAR if editable else ""
    editor_js = _EDITOR_SCRIPT if editable else ""
    script = "<script>window.print()</script>" if auto_print else ""
    return (
        f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
        f'<title>{title}</title><style>{_BASE_CSS}</style></head><body>'
        f'{toolbar}<div class="report"{editable_attr}>{body}</div>{editor_js}{script}</body></html>'
    )


def _inline_uploads(html: str) -> str:
    """把 `/uploads/...` 图片引用替换为 base64 data URI，使导出的 Word 可离线打开。"""

    def _sub(m):
        rel = m.group(1).lstrip("/")  # e.g. "uploads/reports/xxx.jpg"
        fp = UPLOAD_DIR.parent / rel
        if not fp.exists():
            return m.group(0)
        ext = os.path.splitext(fp.name)[1].lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp", "bmp": "bmp"}.get(ext, "png")
        return f'src="data:image/{mime};base64,' + base64.b64encode(fp.read_bytes()).decode() + '"'

    return re.sub(r'src="(/uploads/[^"]+)"', _sub, html)


def _wordify(html: str) -> str:
    """把正文调整成 Word HTML 导入能正确显示的样子：正文表格加边框，图片约束宽度。"""

    def _tbl(m):
        attrs = m.group(1) or ""
        if "qm-head" in attrs:  # 英文表头表格保持无边框
            return m.group(0)
        return '<table border="1" cellspacing="0" cellpadding="4"' + attrs

    html = re.sub(r'<table(\s[^>]*)?>', _tbl, html)

    def _img(m):
        if "style=" in m.group(1):
            return m.group(0)
        return "<img" + m.group(1) + ' style="max-width:100%;height:auto"'

    html = re.sub(r'<img(\s[^>]*?)/?>', _img, html)
    return html


_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="html" ContentType="text/html"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOCX_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<w:body><w:altChunk r:id="rId1"/>
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
</w:body></w:document>"""

_DOCX_DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk" Target="afchunk.html"/>
</Relationships>"""


def _docx_html(body: str) -> str:
    """报告正文 → Word altChunk 需要的 XHTML 文档。"""
    body = _wordify(_inline_uploads(body))
    style = (
        "body{font-family:'Microsoft YaHei',Arial,sans-serif;font-size:13px;color:#222}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{padding:6px 8px;vertical-align:top}"
        "img{max-width:100%;height:auto}"
        ".report{max-width:820px;margin:0 auto}"
        ".report-head,.company,.sub,.form-no,.qm-title{text-align:center}"
        ".company{font-size:19px;font-weight:700}"
        ".qm-sec{font-weight:700;text-align:center;background:#eef1f5}"
        ".lbl{font-weight:600;background:#f2f2f2}"
        ".qm-verdict{font-size:18px;font-weight:700;text-align:center}"
        ".photo-box{height:110px}"
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8"/>'
        f'<style>{style}</style></head>'
        f'<body><div class="report">{body}</div></body></html>'
    )


def _build_docx(xhtml: str) -> bytes:
    """把 XHTML 正文打包成可通过 Word 打开的 .docx（altChunk 机制，无第三方依赖）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("word/document.xml", _DOCX_DOCUMENT)
        z.writestr("word/_rels/document.xml.rels", _DOCX_DOCUMENT_RELS)
        z.writestr("word/afchunk.html", xhtml.encode("utf-8"))
    return buf.getvalue()


def _normalize_type_version(report_type: str, version: str) -> tuple[str, str]:
    """委托记录单 version 统一为空；检测报告 version 默认「常规」；自定义报告 version = 模板名。"""
    if report_type == "委托记录单":
        return report_type, ""
    if report_type == "自定义报告":
        return report_type, version
    return "检测报告", version or "常规"


def _entrust_body(o: EntrustOrder) -> str:
    # 样品编号取排期涉及的实物样机编号（去重，保持排期顺序）
    _seen: set[str] = set()
    _nos: list[str] = []
    for s in o.schedules:
        no = s.sample.sample_no if s.sample else ""
        if no and no not in _seen:
            _seen.add(no)
            _nos.append(no)
    sample_nos = ";".join(_nos)
    return f"""{_report_head()}
  <div class="form-no">表-TC05-01A</div>
  <h2 style="text-align:center;font-size:16px;margin:6px 0">试验委托记录单</h2>
  <table>
    <tr><td class="lbl">委托单位</td><td colspan="4">{_fmt(o.entrust_org)}</td><td class="lbl">委托人</td><td colspan="3">{_fmt(o.entruster)}</td></tr>
    <tr><td class="lbl">样品型号</td><td colspan="4">{_fmt(o.sample_model)}</td><td class="lbl">样品数量</td><td colspan="3">{o.sample_count} {_fmt(o.sample_unit)}</td></tr>
    <tr><td class="lbl">客户型号</td><td colspan="8">{_fmt(o.customer_model)}</td></tr>
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
  <div class="footer">说明：1、每个“检测项目”单独填写一份委托记录表；2、委托单审核接收后，双方负责人签名确认后安排试验。</div>"""


def render_entrust_html(o: EntrustOrder) -> str:
    return _wrap_report(_entrust_body(o), f"试验委托记录单 {o.order_no}")


def _reliability_body(o: EntrustOrder, schedules, _res) -> str:
    """QM-F-46 可靠性测试报告正文（检测报告·常规版）。"""

    # 结果判定：全部判定为 OK → 合格；出现 NG → 不合格；尚未录入结果 → 留空（手填）
    res_vals = [_res(s) for s in schedules]
    ok = res_vals.count("OK")
    ng = res_vals.count("NG")
    if not schedules or (ok == 0 and ng == 0):
        verdict = ""
    elif ng == 0 and ok == len(schedules):
        verdict = "合格"
    else:
        verdict = "不合格"

    # 测试日期：优先取各测试位实际开始~结束时间，无实际时间则回退委托单创建~完成时间
    starts = [s.actual_start for s in schedules if s.actual_start]
    ends = [s.actual_end for s in schedules if s.actual_end]
    date_text = _range(min(starts) if starts else None, max(ends) if ends else None) or _range(o.created_at, o.finish_at)

    # 设备信息（去重，按排期顺序）
    eqs: list = []
    seen: set[int] = set()
    for s in schedules:
        eq = s.equipment
        if eq and eq.id not in seen:
            seen.add(eq.id)
            eqs.append(eq)
    eq_rows = ''.join(
        f'<tr><td colspan="2">{_fmt(e.name)}</td><td colspan="2">{_fmt(e.model)}</td>'
        f'<td colspan="2">{_fmt(e.code)}</td>'
        f'<td colspan="2">{_range(e.valid_from, e.valid_to)}</td></tr>'
        for e in eqs
    ) or '<tr><td colspan="2"></td><td colspan="2"></td><td colspan="2"></td><td colspan="2"></td></tr>'

    # 检查清单：固定 4 行（检查项/测试前/测试后/备注留空手填）
    checklist = ''.join(
        f'<tr><td>{i}</td><td colspan="5"></td><td></td><td></td><td></td></tr>'
        for i in range(1, 5)
    )

    # 测试结果：每个测试位一行（样品编号 + 结果），测试数据/判定标准/备注留空
    def _cls(r):
        return "result-ok" if r == "OK" else ("result-ng" if r == "NG" else "")

    test_rows = ''.join(
        f'<tr><td colspan="2">{_fmt(s.sample.sample_no if s.sample else "")}</td>'
        f'<td colspan="3"></td><td colspan="2"></td>'
        f'<td class="{_cls(_res(s))}">{_res(s) or ""}</td><td></td></tr>'
        for s in schedules
    ) or '<tr><td colspan="2"></td><td colspan="3"></td><td colspan="2"></td><td></td><td></td></tr>'

    return f"""{_report_head_qm46()}
  <table>
    <tr><td class="lbl">测试项目</td><td colspan="2">{_fmt(o.test_item)}</td><td class="lbl" colspan="2">样品数量</td><td colspan="2">{o.sample_count} {_fmt(o.sample_unit)}</td><td class="lbl">结果判定</td></tr>
    <tr><td class="lbl">样品型号</td><td colspan="2">{_fmt(o.sample_model)}</td><td class="lbl" colspan="2">样品阶段</td><td colspan="2">{_fmt(o.test_stage)}</td><td class="qm-verdict" rowspan="3">{verdict}</td></tr>
    <tr><td class="lbl">测试日期</td><td colspan="2">{date_text}</td><td class="lbl" colspan="2">测试环境</td><td colspan="2"></td></tr>
    <tr><td class="lbl">硬件版本</td><td colspan="2"></td><td class="lbl" colspan="2">软件版本</td><td colspan="2"></td></tr>
    <tr><td class="lbl">测试标准</td><td colspan="7">{_fmt(o.test_basis)}</td></tr>
    <tr><td class="lbl">测试目的</td><td colspan="7">{_fmt(o.test_reason)}</td></tr>
    <tr><td colspan="8" class="qm-sec">设备信息</td></tr>
    <tr><td colspan="2" class="lbl">设备名称</td><td colspan="2" class="lbl">设备型号</td><td colspan="2" class="lbl">资产编号</td><td colspan="2" class="lbl">校准有效期</td></tr>
    {eq_rows}
    <tr><td class="lbl">测试条件</td><td colspan="7">{_fmt(o.test_condition)}</td></tr>
    <tr><td class="lbl">测试方法</td><td colspan="7" class="qm-tall"></td></tr>
    <tr><td class="lbl">判定标准</td><td colspan="7" class="qm-tall">{_fmt(o.criteria)}</td></tr>
  </table>

  <table>
    <tr><td colspan="9" class="qm-sec">检查清单</td></tr>
    <tr><td rowspan="2" class="lbl">NO</td><td colspan="5" rowspan="2" class="lbl">检查项</td><td colspan="2" class="lbl">检查结果</td><td rowspan="2" class="lbl">备注</td></tr>
    <tr><td class="lbl">测试前</td><td class="lbl">测试后</td></tr>
    {checklist}
    <tr><td colspan="9" class="qm-sec">测试结果</td></tr>
    <tr><td colspan="2" class="lbl">样品编号</td><td colspan="3" class="lbl">测试数据</td><td colspan="2" class="lbl">判定标准</td><td class="lbl">测试结果</td><td class="lbl">备注</td></tr>
    {test_rows}
    <tr><td colspan="9" class="qm-tall"></td></tr>
    <tr><td colspan="9" class="qm-sec">结果描述</td></tr>
    <tr><td colspan="9" class="qm-tall"></td></tr>
  </table>

  <table class="photo-grid" data-sec="before">
    <tr><td colspan="3" class="qm-sec">实验图片 · 测试前检查图片</td></tr>
    <tr class="photo-row">
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
    </tr>
  </table>
  <table class="photo-grid" data-sec="during">
    <tr><td colspan="3" class="qm-sec">测试中设置与检查图片</td></tr>
    <tr class="photo-row">
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
    </tr>
  </table>
  <table class="photo-grid" data-sec="after">
    <tr><td colspan="3" class="qm-sec">测试后检查图片</td></tr>
    <tr class="photo-row">
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
      <td class="photo-cell photo-empty"><div class="photo-box" contenteditable="false"></div><div class="photo-note"></div></td>
    </tr>
  </table>

  <table>
    <tr><td colspan="4" class="qm-tall">改善对策（R&amp;D）：</td></tr>
    <tr><td colspan="4">备注: {_fmt(o.remark)}</td></tr>
    <tr><td>实验员：{_fmt(o.reviewer.name if o.reviewer else '')}</td><td>审核：</td><td colspan="2">批准：</td></tr>
  </table>"""


def _test_body(o: EntrustOrder, version: str = "常规") -> str:
    schedules = list(o.schedules)

    def _res(s):
        # 新流程结果存于排期；历史数据结果存于样品，这里兜底兼容
        return s.result or (s.sample.result if s.sample else "")

    ok_count = sum(1 for s in schedules if _res(s) == "OK")
    ng_count = sum(1 for s in schedules if _res(s) == "NG")
    passed = "合格" if schedules and ng_count == 0 and ok_count == len(schedules) else "不合格"
    passed_en = "Passed" if passed == "合格" else "Failed"

    if version == "常规":
        return _reliability_body(o, schedules, _res)

    # 检测版：逐测试位编号 + 结果，附样品编号、试验条件与实物图占位
    header_cells = ''.join(
        f'<td style="text-align:center;font-weight:600">{i+1}#</td>' for i in range(len(schedules))
    ) or '<td></td>'
    result_cells = ''
    for s in schedules:
        cls = "result-ok" if _res(s) == "OK" else ("result-ng" if _res(s) == "NG" else "")
        result_cells += f'<td class="{cls}">{_res(s) or "-"}</td>'
    sample_nos = "；".join((s.sample.sample_no if s.sample else "") for s in schedules)
    result_rows = (
        '<tr><td class="lbl" rowspan="2">检验结果<br>Test Result</td>' + header_cells + '</tr>'
        '<tr>' + (result_cells or '<td></td>') + '</tr>'
        f'<tr><td class="lbl">样品编号</td><td colspan="9">{sample_nos or "-"}</td></tr>'
        f'<tr><td class="lbl">试验条件</td><td colspan="9">{_fmt(o.test_condition) or "-"}</td></tr>'
    )
    extra = (
        '<div style="margin-top:10px"><b>试验前样品图片 (Samples Before Test)：</b>'
        '<div style="border:1px dashed #999;padding:24px;text-align:center;color:#999">'
        '（样品实物图待上传后显示）</div></div>'
    )

    return f"""{_report_head()}
  <div class="form-no">表-TC11-02A</div>
  <h2 style="text-align:center;font-size:16px;margin:6px 0">检测报告 Test Report（检测版）</h2>
  <table>
    <tr><td class="lbl" rowspan="3">预检查<br>Pre-check</td><td class="lbl">委托单编号</td><td colspan="4">{_fmt(o.order_no)}</td><td class="lbl">接收时间</td><td colspan="3">{_dt_short(o.created_at)}</td></tr>
    <tr><td class="lbl">样品检查</td><td colspan="8">{_fmt(o.sample_status)}</td></tr>
    <tr><td class="lbl">样品状态</td><td colspan="8">{_fmt(o.sample_status)}</td></tr>
    {result_rows}
    <tr><td class="lbl">测试结果</td><td colspan="9" style="font-size:15px"><b>试验后样品外观正常。测试结果：{passed} Test Result: {passed_en}</b>（检验单位公章）</td></tr>
    <tr><td class="lbl">备注<br>Remark</td><td colspan="9">{_fmt(o.remark)}</td></tr>
    <tr><td class="lbl">拟制人</td><td colspan="2" class="sig"></td><td class="lbl">授权签字人</td><td colspan="3" class="sig">{_fmt(o.reviewer.name if o.reviewer else '')}</td><td class="lbl">签字人职务</td><td colspan="2">□中心主任 □技术负责人</td></tr>
    <tr><td class="lbl">审核人</td><td colspan="2">{_fmt(o.entruster)}</td><td class="lbl">签发日期</td><td colspan="5">{_dt_short(o.finish_at or o.review_at)}</td></tr>
  </table>
  {extra}
  <div class="footer">注：1、检测报告只对试验样品负责，实验室只对结果与标准的符合性进行判定，不对结果数据进行分析。2、每项检测只提供一份检测报告，复印或修改视为无效。</div>"""


def render_test_html(o: EntrustOrder, version: str = "常规") -> str:
    return _wrap_report(_test_body(o, version), f"检测报告 {o.experiment_no or o.order_no}")


def _custom_mapping(o: EntrustOrder) -> dict[str, str]:
    """自定义报告占位符（不含 {{}}）→ 委托单已有信息（纯文本，不做 HTML 转义，交由 Word 处理）。"""
    # 样品编号取排期涉及的实物样机编号（去重，保持排期顺序）
    _seen: set[str] = set()
    _nos: list[str] = []
    for s in o.schedules:
        no = s.sample.sample_no if s.sample else ""
        if no and no not in _seen:
            _seen.add(no)
            _nos.append(no)
    sample_nos = ";".join(_nos)

    # 结果判定：全部 OK → 合格；出现 NG → 不合格；尚未录入结果 → 留空
    res_vals = [(s.result or (s.sample.result if s.sample else "")) for s in o.schedules]
    ok = res_vals.count("OK")
    ng = res_vals.count("NG")
    if not o.schedules or (ok == 0 and ng == 0):
        verdict = ""
    elif ng == 0 and ok == len(o.schedules):
        verdict = "合格"
    else:
        verdict = "不合格"

    def _p(v):
        return "" if v in (None, "") else str(v)

    return {
        "委托单编号": _p(o.order_no),
        "实验编号": _p(o.experiment_no),
        "委托单位": _p(o.entrust_org),
        "委托人": _p(o.entruster),
        "样品名称": _p(o.sample_name),
        "样品型号": _p(o.sample_model),
        "客户型号": _p(o.customer_model),
        "样品数量": _p(f"{o.sample_count} {o.sample_unit}"),
        "检测项目": _p(o.test_item),
        "检测依据": _p(o.test_basis),
        "试验原因": _p(o.test_reason),
        "测试阶段": _p(o.test_stage),
        "试验条件": _p(o.test_condition),
        "判定标准": _p(o.criteria),
        "样品状态": _p(o.sample_status),
        "样品处理": _p(o.sample_dispose),
        "委托时间": _dt_short(o.created_at),
        "完成时间": _dt_short(o.finish_at),
        "实验员": _p(o.reviewer.name if o.reviewer else ""),
        "样品编号": sample_nos,
        "结果判定": verdict,
        "备注": _p(o.remark),
    }


def _load_draft(db: Session, order_id: int, report_type: str, version: str) -> ReportDraft | None:
    """按 (委托单, 类型, 版本) 取唯一草稿。"""
    report_type, version = _normalize_type_version(report_type, version)
    return (
        db.query(ReportDraft)
        .filter(
            ReportDraft.order_id == order_id,
            ReportDraft.report_type == report_type,
            ReportDraft.version == version,
        )
        .first()
    )


def _body_for(db: Session, o: EntrustOrder, report_type: str, version: str) -> str:
    """报告正文：优先用已保存草稿快照，否则实时生成。"""
    report_type, version = _normalize_type_version(report_type, version)
    draft = _load_draft(db, o.id, report_type, version)
    if draft and draft.content:
        return draft.content
    if report_type == "委托记录单":
        return _entrust_body(o)
    if report_type == "自定义报告":
        tpl = db.query(ReportTemplate).filter(ReportTemplate.name == version).first()
        if tpl is None:
            raise HTTPException(404, f"报告模板「{version}」不存在或已被删除")
        return _fill_docx_template(tpl.content, _custom_mapping(o))
    return _test_body(o, version)


# ---------------------------------------------------------------------------
# OnlyOffice 在线编辑：真 .docx 构建 / 保存（打印与归档以 .docx 为准）
# ---------------------------------------------------------------------------
def _load_order_full(db: Session, order_id: int) -> EntrustOrder:
    o = db.get(EntrustOrder, order_id, options=[
        selectinload(EntrustOrder.schedules).selectinload(Schedule.sample),
        selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment),
        selectinload(EntrustOrder.reviewer),
    ])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    return o


def build_report_docx(db: Session, order_id: int, report_type: str, version: str) -> tuple[bytes, str]:
    """构建报告的真 .docx：优先草稿 .docx，否则生成（自定义用模板填充 / 内置用 HTML 转换）并落草稿。"""
    o = _load_order_full(db, order_id)
    report_type, version = _normalize_type_version(report_type, version)
    if report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能编辑该报告")
    draft = _load_draft(db, order_id, report_type, version)
    if draft and draft.docx_content:
        data = draft.docx_content
    else:
        if report_type == "自定义报告":
            tpl = db.query(ReportTemplate).filter(ReportTemplate.name == version).first()
            if tpl is None:
                raise HTTPException(404, f"报告模板「{version}」不存在或已被删除")
            data = onlyoffice.fill_docx_template(tpl.content, _custom_mapping(o))
        else:
            data = onlyoffice.html_to_docx(_body_for(db, o, report_type, version))
        if draft:
            draft.docx_content = data
        else:
            db.add(ReportDraft(order_id=order_id, report_type=report_type, version=version, content="", docx_content=data))
        db.commit()
    name = f"{o.experiment_no or o.order_no}_{report_type}{'_' + version if version else ''}.docx"
    return data, name


def save_report_docx(db: Session, order_id: int, report_type: str, version: str, docx_bytes: bytes, user: User | None = None) -> None:
    """把 OnlyOffice 回调回传的 .docx 存入草稿（.docx 为准）。"""
    report_type, version = _normalize_type_version(report_type, version)
    draft = _load_draft(db, order_id, report_type, version)
    if draft:
        draft.docx_content = docx_bytes
        draft.updated_at = datetime.now()
    else:
        draft = ReportDraft(order_id=order_id, report_type=report_type, version=version, content="", docx_content=docx_bytes)
        db.add(draft)
    if user is not None:
        o = db.get(EntrustOrder, order_id)
        log(db, user, "在线编辑保存报告", "report", order_id, f"{o.experiment_no or o.order_no if o else ''} {report_type}{version}")
    db.commit()


@router.post("/{order_id}/online-open")
def online_open(
    order_id: int,
    type: str = Query("检测报告"),
    version: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """生成报告 .docx 并返回 OnlyOffice 编辑器配置（前端 iframe 加载用）。"""
    if not onlyoffice.is_enabled():
        raise HTTPException(503, "未配置 OnlyOffice，请设置 LIMS_ONLYOFFICE_URL / LIMS_ONLYOFFICE_JWT_SECRET 后启用")
    data, name = build_report_docx(db, order_id, type, version)
    o = db.get(EntrustOrder, order_id)
    report_type, version = _normalize_type_version(type, version)
    key = onlyoffice.make_key({"kind": "report", "order_id": order_id, "report_type": report_type, "version": version})
    onlyoffice.work_file(key, "docx").write_bytes(data)
    config = onlyoffice.editor_config(
        key=key,
        title=name,
        file_type="docx",
        document_type="word",
        user_id=user.id,
        user_name=user.name,
        download_path=f"/api/oo/download?key={key}",
        callback_path="/api/oo/callback",
    )
    log(db, user, "启动在线编辑", "report", order_id, f"{o.experiment_no or o.order_no if o else ''} {report_type}{version}")
    return config


# ---------------------------------------------------------------------------
# Word 编辑：启动本机 Word 打开 .docx，编辑后回传导入
# ---------------------------------------------------------------------------
def _word_paths(order_id: int, report_type: str, version: str) -> tuple[Path, Path, Path]:
    """返回 (docx 路径, 回传 html 路径, 图片目录)。文件名用 ASCII，避免 Word/COM 编码问题。"""
    report_type, version = _normalize_type_version(report_type, version)
    if report_type == "委托记录单":
        tag = "entrust"
    elif report_type == "自定义报告":
        tag = "custom"
    elif version == "检测":
        tag = "test_jc"
    else:
        tag = "test_cg"
    _WORD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    stem = _WORD_TMP_DIR / f"lims_word_{order_id}_{tag}"
    return stem.with_suffix(".docx"), stem.with_suffix(".html"), Path(str(stem) + ".files")


def _word_html(body: str) -> str:
    """把报告正文包成 Word 可直接打开转换的完整 HTML（含样式，UTF-8）。"""
    return ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
            '<style>' + _BASE_CSS + '</style></head>'
            '<body><div class="report">' + body + '</div></body></html>')


def _word_open(body: str, docx_path: Path) -> None:
    """把报告 HTML 交给 Word 转成真正的 .docx（Word 自身转换比 altChunk 可靠），再用本机 Word 打开。"""
    import pythoncom
    import win32com.client

    src_html = docx_path.with_suffix(".src.html")
    src_html.write_text(_word_html(body), encoding="utf-8-sig")

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src_html))
        doc.SaveAs2(str(docx_path), FileFormat=16)  # 16 = .docx
        doc.Close(False)
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    os.startfile(str(docx_path))


def _word_export_html(docx_path: Path, html_path: Path) -> None:
    """把 Word 中当前文档状态另存为「筛选后的 HTML」(wdFormatFilteredHTML=10)，含未保存的修改。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    started = False
    try:
        try:
            word = win32com.client.GetActiveObject("Word.Application")
        except Exception:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = True
            started = True
        norm = os.path.normcase(str(docx_path))
        doc = None
        for d in word.Documents:
            try:
                if os.path.normcase(str(d.FullName)) == norm:
                    doc = d
                    break
            except Exception:
                continue
        if doc is None:
            doc = word.Documents.Open(str(docx_path))
        doc.SaveAs2(str(html_path), FileFormat=10, Encoding=65001)  # 10 = 筛选后的 HTML；65001 = UTF-8
    finally:
        if started:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _import_word_html(html_path: Path, files_dir: Path) -> str:
    """读取 Word 导出的 HTML，图片落库到 /uploads/reports/，返回清洗后的报告正文。"""
    raw = html_path.read_bytes()
    # Word 导出 HTML 的编码不定：可能是 UTF-8、UTF-16LE、UTF-16BE、GBK，按 BOM/内容探测
    if raw.startswith(b"\xff\xfe"):
        text = raw.decode("utf-16-le", errors="ignore")
    elif raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16-be", errors="ignore")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", errors="ignore")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="ignore")
    m = re.search(r"<body[^>]*>(.*)</body>", text, re.S | re.I)
    content = m.group(1) if m else text

    def _sub(mm):
        rel = mm.group(1)
        name = rel.replace("\\", "/").split("/")[-1]
        src_file = files_dir / name
        if src_file.exists():
            ext = os.path.splitext(name)[1].lower()
            if ext not in _ALLOWED_EXT:
                ext = ".png"
            stored = f"{uuid.uuid4().hex}{ext}"
            (_report_image_dir() / stored).write_bytes(src_file.read_bytes())
            return f'src="/uploads/reports/{stored}"'
        return mm.group(0)

    content = re.sub(r'src="([^"]+\.(?:png|jpe?g|gif|bmp|webp))"', _sub, content, flags=re.I)
    return _sanitize_html(content)


def _fill_docx_template(template_bytes: bytes, mapping: dict[str, str]) -> str:
    """把 .docx 模板写到明文区 → Word Find&Replace 占位符 → 导出筛选 HTML → 清洗返回正文。"""
    import pythoncom
    import win32com.client

    stem = _WORD_TMP_DIR / f"lims_tpl_{uuid.uuid4().hex}"
    docx_path = stem.with_suffix(".docx")
    html_path = stem.with_suffix(".html")
    files_dir = Path(str(stem) + ".files")
    docx_path.write_bytes(template_bytes)

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx_path))
        for key, value in mapping.items():
            # 必须一次性传全位置参数；属性赋值 + Execute(Replace=2) 在 Word COM 下不生效
            doc.Content.Find.Execute(
                "{{" + key + "}}",                 # FindText
                False, False, False, False, False,  # MatchCase/WholeWord/Wildcards/SoundsLike/AllWordForms
                True,    # Forward
                1,       # Wrap = wdFindContinue
                False,   # Format
                value,   # ReplaceWith
                2,       # Replace = wdReplaceAll
            )
        doc.SaveAs2(str(html_path), FileFormat=10, Encoding=65001)  # 10 = 筛选后的 HTML；65001 = UTF-8
        doc.Close(False)
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    return _import_word_html(html_path, files_dir)


@router.get("/entrust/{order_id}", response_class=Response)
def entrust_report(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    o = db.get(EntrustOrder, order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    return Response(_wrap_report(_body_for(db, o, "委托记录单", ""), f"试验委托记录单 {o.order_no}"), media_type="text/html")


@router.get("/test/{order_id}", response_class=Response)
def test_report(
    order_id: int,
    version: str = Query("常规", description="常规 / 检测"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    o = db.get(EntrustOrder, order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    if o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能生成检测报告")
    return Response(_wrap_report(_body_for(db, o, "检测报告", version), f"检测报告 {o.experiment_no or o.order_no}"), media_type="text/html")


@router.get("/custom/{order_id}", response_class=Response)
def custom_report(
    order_id: int,
    version: str = Query("", description="模板名称"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    o = db.get(EntrustOrder, order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    if o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能生成自定义报告")
    return Response(_wrap_report(_body_for(db, o, "自定义报告", version), f"自定义报告 {o.experiment_no or o.order_no}"), media_type="text/html")


# ---------------------------------------------------------------------------
# 报告签发与归档
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 报告编辑与草稿
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_report_image(
    file: UploadFile = File(...),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    """上传报告内嵌图片（测试前/中/后照片等），返回可直接访问的 /uploads/reports/ URL。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, "仅支持图片格式：jpg / png / gif / webp / bmp")
    content = await file.read()
    if not content:
        raise HTTPException(400, "图片内容为空")
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(400, "图片大小不能超过 5MB")
    stored_name = f"{uuid.uuid4().hex}{ext}"
    (_report_image_dir() / stored_name).write_bytes(content)
    return {"url": f"/uploads/reports/{stored_name}"}


@router.get("/edit/{order_id}", response_class=Response)
def edit_report(
    order_id: int,
    type: str = Query("检测报告", description="委托记录单 / 检测报告"),
    version: str = Query("", description="常规 / 检测（检测报告用）"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    o = db.get(EntrustOrder, order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    report_type, version = _normalize_type_version(type, version)
    if report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能编辑检测报告")
    body = _body_for(db, o, report_type, version)
    title = f"编辑报告 {o.experiment_no or o.order_no}"
    return Response(_wrap_report(body, title, editable=True, auto_print=False), media_type="text/html")


@router.get("/{order_id}/docx")
def export_docx(
    order_id: int,
    type: str = Query("检测报告"),
    version: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    """把报告（含已编辑草稿）导出为 .docx，可在 Word 中二次编辑。"""
    from urllib.parse import quote

    o = db.get(EntrustOrder, order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    report_type, version = _normalize_type_version(type, version)
    if report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能导出检测报告")
    body = _body_for(db, o, report_type, version)
    docx = _build_docx(_docx_html(body))
    filename = f"{o.experiment_no or o.order_no}_{report_type}{'_' + version if version else ''}.docx"
    disp = f"attachment; filename=\"report.docx\"; filename*=UTF-8''{quote(filename)}"
    return Response(docx, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": disp})


@router.post("/{order_id}/word-open")
def word_open(
    order_id: int,
    type: str = Query("检测报告"),
    version: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """把当前报告（含草稿）生成 .docx，并用本机 Word 打开。"""
    o = db.get(EntrustOrder, order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    report_type, version = _normalize_type_version(type, version)
    if report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能编辑检测报告")
    body = _body_for(db, o, report_type, version)
    docx_path, _, _ = _word_paths(order_id, report_type, version)
    _word_open(body, docx_path)
    log(db, user, "启动Word编辑", "report", o.id, f"{o.experiment_no or o.order_no} {report_type}{version}")
    return {"message": "已在 Word 中打开，编辑保存后点「从Word同步」回填"}


@router.post("/{order_id}/word-sync")
def word_sync(
    order_id: int,
    type: str = Query("检测报告"),
    version: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """把 Word 中当前编辑内容回传导入为报告草稿。"""
    o = db.get(EntrustOrder, order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    report_type, version = _normalize_type_version(type, version)
    if report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能编辑检测报告")
    docx_path, html_path, files_dir = _word_paths(order_id, report_type, version)
    if not docx_path.exists():
        raise HTTPException(400, "尚未启动 Word 编辑，请先点「启动Word编辑」")
    try:
        _word_export_html(docx_path, html_path)
    except Exception as e:
        raise HTTPException(500, f"读取 Word 失败（请确认 Word 已打开该文档）：{e}")
    content = _import_word_html(html_path, files_dir)
    if not content.strip():
        raise HTTPException(400, "未取到 Word 内容，请确认 Word 中已有内容")
    draft = _load_draft(db, order_id, report_type, version)
    if draft:
        draft.content = content
        draft.updated_at = datetime.now()
    else:
        draft = ReportDraft(order_id=order_id, report_type=report_type, version=version, content=content)
        db.add(draft)
    log(db, user, "从Word同步报告", "report", o.id, f"{o.experiment_no or o.order_no} {report_type}{version}")
    db.commit()
    return {"message": "已从 Word 同步到报告", "order_id": order_id, "report_type": report_type, "version": version}


@router.get("/drafts")
def list_drafts(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    """列出所有草稿（供前端「生成报告」按钮门控使用，含 updated_at 用于驳回后重新点亮判定）。"""
    rows = db.query(ReportDraft).order_by(ReportDraft.id.desc()).all()
    return [{
        "order_id": d.order_id, "report_type": d.report_type, "version": d.version,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    } for d in rows]


@router.get("/states")
def report_states(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    """列出各报告的审批状态（供前端「生成报告」点亮/置灰判定）。"""
    rows = db.query(Report).filter(Report.status.in_(["待审批", "已驳回", "已签发"])).all()
    return [{
        "order_id": r.order_id, "report_type": r.report_type, "version": r.version,
        "status": r.status,
        "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
    } for r in rows]


@router.post("/draft")
def save_draft(
    data: ReportDraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    o = db.get(EntrustOrder, data.order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    report_type, version = _normalize_type_version(data.report_type, data.version)
    if report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能编辑检测报告")
    content = _sanitize_html(data.content)
    draft = _load_draft(db, data.order_id, report_type, version)
    if draft:
        draft.content = content
        # 显式刷新 updated_at：SQLAlchemy 的 onupdate 在 content 未变化时不会触发 UPDATE，
        # 而「否决后重新保存」需要 updated_at > rejected_at 才能重新点亮提交按钮。
        draft.updated_at = datetime.now()
    else:
        draft = ReportDraft(order_id=data.order_id, report_type=report_type, version=version, content=content)
        db.add(draft)
    log(db, user, "保存报告草稿", "report", o.id, f"{o.experiment_no or o.order_no} {report_type}")
    db.commit()
    return {"message": "草稿已保存", "order_id": data.order_id, "report_type": report_type, "version": version}


# ---------------------------------------------------------------------------
# 报告签发与归档
# ---------------------------------------------------------------------------
def _inject_approver_name(content: str, name: str) -> str:
    """把审批人姓名写入报告正文「审核」位置：常规版「审核：」、检测版「审核人」单元格；
    其余类型（委托记录单/自定义）无该位置，仅在归档信息里记录审批人。"""
    if not name:
        return content or ""
    content = content or ""
    escaped = _html.escape(name)
    if "审核：" in content:
        return content.replace("审核：", f"审核：{escaped}", 1)
    m = re.search(r"(<td[^>]*>\s*审核人\s*</td>\s*<td[^>]*>)[^<]*(</td>)", content)
    if m:
        return content[: m.start()] + m.group(1) + escaped + m.group(2) + content[m.end():]
    return content


@router.post("/{order_id}/issue")
def issue_report(
    order_id: int,
    data: ReportIssueRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "experimenter")),
):
    """提交报告审批：把草稿快照生成 Report（状态「待审批」），等待管理员审批通过后归档。"""
    o = db.get(EntrustOrder, order_id)
    if o is None:
        raise HTTPException(404, "委托单不存在")
    if data.report_type in ("检测报告", "自定义报告") and o.status != "已完成":
        raise HTTPException(400, "实验未完成，暂不能提交检测报告")
    # version 与草稿保持一致（检测报告默认「常规」，委托记录单固定空），避免草稿与 Report 版本错位
    _, version = _normalize_type_version(data.report_type, data.version)
    draft = _load_draft(db, order_id, data.report_type, data.version)
    if not draft or not (draft.content or draft.docx_content):
        raise HTTPException(400, "请先编辑并保存该类型报告草稿")
    content = draft.content or ""
    docx_content = draft.docx_content or None

    existing = (
        db.query(Report)
        .filter(
            Report.order_id == order_id,
            Report.report_type == data.report_type,
            Report.version == version,
        )
        .first()
    )
    if existing:
        if existing.status == "待审批":
            raise HTTPException(400, "该报告已在审批中，请勿重复提交")
        if existing.status == "已签发":
            raise HTTPException(400, "该报告已签发归档，不能重复提交")
        # 已驳回：需在否决后重新保存过草稿才可重提（前端已门控，后端兜底校验）
        if existing.status == "已驳回" and draft.updated_at and existing.rejected_at and draft.updated_at <= existing.rejected_at:
            raise HTTPException(400, "请重新编辑并保存草稿后再提交")
        existing.status = "待审批"
        existing.content = content
        existing.docx_content = docx_content
        existing.issuer_id = user.id
        existing.reject_reason = ""
        existing.rejected_at = None
        existing.approver_id = None
        existing.approved_at = None
        log(db, user, "重新提交报告审批", "report", existing.id, f"{o.experiment_no or o.order_no} {data.report_type}{version}")
        db.commit()
        return report_to_dict(existing)

    def _do():
        r = Report(
            order_id=order_id, report_no=next_report_no(db),
            report_type=data.report_type, version=version, status="待审批",
            content=content, docx_content=docx_content, issuer_id=user.id,
        )
        db.add(r)
        db.flush()
        log(db, user, "提交报告审批", "report", r.id, f"{o.experiment_no or o.order_no} {data.report_type}{version}")
        notify(db, "新报告待审批", f"{o.experiment_no or o.order_no} {o.sample_name} 的{data.report_type}待审批", role="admin", order_id=o.id)
        return r

    r = retry_on_number_conflict(db, _do)
    db.refresh(r)
    return report_to_dict(r)


# ---------------------------------------------------------------------------
# 报告审批（管理员）
# ---------------------------------------------------------------------------
@router.get("/pending")
def pending_reports(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    """列出待审批报告（仅管理员）。"""
    rows = (
        db.query(Report)
        .options(selectinload(Report.order), selectinload(Report.issuer), selectinload(Report.approver))
        .filter(Report.status == "待审批")
        .order_by(Report.id.desc())
        .all()
    )
    return [report_to_dict(r) for r in rows]


@router.get("/pending/{report_id}/view", response_class=Response)
def pending_view(report_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    """预览待审批报告正文（管理员审批前查看）。"""
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    o = _load_order_full(db, r.order_id)
    if r.content:
        html = _wrap_report(r.content, f"报告 {r.report_no}")
    else:
        html = render_entrust_html(o) if r.report_type == "委托记录单" else render_test_html(o, r.version or "常规")
    return Response(html, media_type="text/html")


@router.post("/{report_id}/approve")
def approve_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """审批通过：写入审批人姓名到「审核」位置，状态→已签发并归档。"""
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    if r.status != "待审批":
        raise HTTPException(400, "该报告不在待审批状态")
    o = _load_order_full(db, r.order_id)
    content = r.content or _body_for(db, o, r.report_type, r.version)
    r.content = _inject_approver_name(content, user.name)
    r.status = "已签发"
    r.approver_id = user.id
    r.approved_at = datetime.now()
    r.issued_at = datetime.now()
    r.reject_reason = ""
    log(db, user, "报告审批通过", "report", r.id, f"{r.report_no} {r.report_type}{r.version}")
    msg = f"{o.experiment_no or o.order_no} {o.sample_name} 的{r.report_type}已通过审批并归档"
    if r.issuer_id:
        notify(db, "报告审批通过", msg, user=r.issuer, order_id=r.order_id)
    else:
        notify(db, "报告审批通过", msg, role="experimenter", order_id=r.order_id)
    db.commit()
    return report_to_dict(r)


@router.post("/{report_id}/reject")
def reject_report(report_id: int, data: ReportRejectRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    """审批否决：必填原因，状态→已驳回（回到「实验报告」，生成报告置灰直至重新编辑保存）。"""
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    if r.status != "待审批":
        raise HTTPException(400, "该报告不在待审批状态")
    reason = (data.reject_reason or "").strip()
    if not reason:
        raise HTTPException(400, "否决时必须填写否决原因")
    r.status = "已驳回"
    r.reject_reason = reason
    r.rejected_at = datetime.now()
    log(db, user, "报告审批否决", "report", r.id, f"{r.report_no} 原因：{reason}")
    o = _load_order_full(db, r.order_id)
    msg = f"{o.experiment_no or o.order_no} {o.sample_name} 的{r.report_type}被否决：{reason}"
    if r.issuer_id:
        notify(db, "报告被否决", msg, user=r.issuer, order_id=r.order_id)
    else:
        notify(db, "报告被否决", msg, role="experimenter", order_id=r.order_id)
    db.commit()
    return {"message": "已否决", "status": "已驳回"}


@router.get("/archive")
def archive(
    type: str | None = Query(None),
    keyword: str | None = Query(None),
    page: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "experimenter")),
):
    q = (
        db.query(Report)
        .options(selectinload(Report.order), selectinload(Report.issuer), selectinload(Report.approver))
        .join(EntrustOrder, Report.order_id == EntrustOrder.id)
        .filter(Report.status == "已签发")
    )
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
    # 未传 page 时保持返回数组（兼容旧前端）；传 page 时返回分页结构
    if page is None:
        rows = q.order_by(Report.id.desc()).all()
        return [report_to_dict(r) for r in rows]
    size = size or 20
    total = q.count()
    rows = q.order_by(Report.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [report_to_dict(r) for r in rows]}


@router.get("/archive/{report_id}/view", response_class=Response)
def archive_view(report_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    o = db.get(EntrustOrder, r.order_id, options=[selectinload(EntrustOrder.schedules).selectinload(Schedule.sample), selectinload(EntrustOrder.schedules).selectinload(Schedule.equipment), selectinload(EntrustOrder.reviewer)])
    if o is None:
        raise HTTPException(404, "委托单不存在")
    # 有正文快照（编辑后签发）优先用快照，否则实时生成
    if r.content:
        html = _wrap_report(r.content, f"报告 {r.report_no}")
    else:
        html = render_entrust_html(o) if r.report_type == "委托记录单" else render_test_html(o, r.version or "常规")
    return Response(html, media_type="text/html")


@router.get("/archive/{report_id}/docx")
def archive_docx(report_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "experimenter"))):
    """下载归档报告的 .docx（OnlyOffice 编辑后签发，打印/归档以它为准）。"""
    from urllib.parse import quote

    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    if not r.docx_content:
        raise HTTPException(404, "该报告没有 .docx 版本（可能是旧数据或未经在线编辑）")
    filename = f"{r.report_no}_{r.report_type}.docx"
    disp = f"attachment; filename=\"report.docx\"; filename*=UTF-8''{quote(filename)}"
    return Response(r.docx_content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": disp})


@router.delete("/archive/{report_id}")
def archive_delete(report_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "报告不存在")
    log(db, user, "作废报告", "report", r.id, r.report_no)
    db.delete(r)
    db.commit()
    return {"message": "已作废"}
