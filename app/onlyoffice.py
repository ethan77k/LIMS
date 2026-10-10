"""OnlyOffice 在线编辑集成。

职责：
- 真 .docx / .xlsx 生成（python-docx / openpyxl，替代 altChunk，OnlyOffice 可正确渲染）；
- .docx 模板占位符填充（跨 run 替换，兼容 Word 拆分的 run）；
- 与 OnlyOffice Document Server 的 JWT 互信、文档 key 签名、编辑器配置。

所有第三方库均「懒加载」：未安装 docx/openpyxl 时本模块仍可导入，
应用照常启动，OnlyOffice 相关接口返回明确错误。
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

import jwt

from .config import (
    ONLYOFFICE_CALLBACK_BASE,
    ONLYOFFICE_JWT_SECRET,
    ONLYOFFICE_URL,
    ONLYOFFICE_WORK_DIR,
    STATIC_DIR,
)


def is_enabled() -> bool:
    """OnlyOffice 集成是否启用（需配置地址 + JWT 密钥）。"""
    return bool(ONLYOFFICE_URL and ONLYOFFICE_JWT_SECRET)


# ---------------------------------------------------------------------------
# JWT 互信（OnlyOffice Document Server 与 LIMS 后端共用 JWT_SECRET）
# ---------------------------------------------------------------------------
def sign_token(payload: dict) -> str:
    return jwt.encode(payload, ONLYOFFICE_JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    return jwt.decode(token, ONLYOFFICE_JWT_SECRET, algorithms=["HS256"])


# ---------------------------------------------------------------------------
# 文档 key：短随机 ID + HMAC 签名，载荷落盘到工作区
#
# OnlyOffice 对 document.key 有 128 字符上限。此前把中文载荷 base64 后直接塞进
# key，报告类会超长（131+），导致编辑器无法加载。改为：完整载荷 JSON 落盘，
# key 只携带 16 位随机 ID + 12 位签名（共 28 字符），且不再受载荷长度影响。
# ---------------------------------------------------------------------------
_KEY_ID_LEN = 16
_KEY_SIG_LEN = 12


def _key_payload_file(sid: str) -> Path:
    """文档 key 载荷的落盘位置（key 本身是短 ID，完整载荷存这里）。"""
    ONLYOFFICE_WORK_DIR.mkdir(parents=True, exist_ok=True)
    return ONLYOFFICE_WORK_DIR / f"key_{sid}.json"


def make_key(payload: dict) -> str:
    """生成 28 字符的文档 key（16 位随机 ID + 12 位 HMAC 签名）。"""
    sid = uuid.uuid4().hex[:_KEY_ID_LEN]
    sig = hmac.new(ONLYOFFICE_JWT_SECRET.encode(), sid.encode(), hashlib.sha256).hexdigest()[:_KEY_SIG_LEN]
    _key_payload_file(sid).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return sid + sig


def parse_key(key: str) -> dict:
    """校验 key 签名并取回落盘的载荷。"""
    if len(key) != _KEY_ID_LEN + _KEY_SIG_LEN:
        raise ValueError("非法文档 key")
    sid = key[:_KEY_ID_LEN]
    sig = key[_KEY_ID_LEN:]
    expect = hmac.new(ONLYOFFICE_JWT_SECRET.encode(), sid.encode(), hashlib.sha256).hexdigest()[:_KEY_SIG_LEN]
    if not hmac.compare_digest(expect, sig):
        raise ValueError("文档 key 签名校验失败")
    fp = _key_payload_file(sid)
    if not fp.exists():
        raise ValueError("文档 key 已失效或不存在")
    return json.loads(fp.read_text(encoding="utf-8"))


def work_file(key: str, suffix: str) -> Path:
    """工作文件路径（D:/temp 明文区）。文件名用 key 的 hex，避免特殊字符。"""
    ONLYOFFICE_WORK_DIR.mkdir(parents=True, exist_ok=True)
    return ONLYOFFICE_WORK_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.{suffix}"


# ---------------------------------------------------------------------------
# 编辑器配置
# ---------------------------------------------------------------------------
def editor_config(
    *,
    key: str,
    title: str,
    file_type: str,          # docx / xlsx
    document_type: str,      # word / cell
    user_id: int,
    user_name: str,
    mode: str = "edit",      # edit / view
    download_path: str,
    callback_path: str,
) -> dict:
    config = {
        "document": {
            "fileType": file_type,
            "key": key,
            "title": title,
            "url": ONLYOFFICE_CALLBACK_BASE + download_path,
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": ONLYOFFICE_CALLBACK_BASE + callback_path,
            "lang": "zh-CN",
            "mode": mode,
            "user": {"id": str(user_id), "name": user_name},
            "customization": {"autosave": True, "forcesave": True},
        },
    }
    config["token"] = sign_token(config)
    return config


# ---------------------------------------------------------------------------
# .xlsx 生成（openpyxl）
# ---------------------------------------------------------------------------
def xlsx_bytes(headers: list[str], rows: list[list], sheet_name: str = "Sheet1") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
        cell.alignment = Alignment(horizontal="center")
    # 按内容自适应列宽（粗估，中文按 2 字节计）
    for i, col in enumerate(ws.columns, 1):
        width = 0
        for cell in col:
            v = "" if cell.value is None else str(cell.value)
            w = sum(2 if ord(c) > 127 else 1 for c in v)
            width = max(width, w)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# .xlsx 表格式报告 / .xlsx 模板占位符填充（cell 版）
# ---------------------------------------------------------------------------
def form_xlsx(rows: list, title: str = "", head: str = "") -> bytes:
    """把「表格式报告」行渲染成 .xlsx。rows 每行 [(文本, 跨列, 样式), ...]；样式 label/value/sec/ok/ng/blank。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    ncols = max((sum(c[1] for c in row) for row in rows), default=1)
    wb = Workbook()
    ws = wb.active
    ws.title = "报告"

    thin = Side(style="thin", color="B0B0B0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    fill_lbl = PatternFill("solid", fgColor="F2F2F2")
    fill_sec = PatternFill("solid", fgColor="DDEBF7")
    fill_ok = PatternFill("solid", fgColor="C6EFCE")
    fill_ng = PatternFill("solid", fgColor="FFC7CE")

    for i in range(ncols):
        ws.column_dimensions[get_column_letter(i + 1)].width = 12

    r = 0
    if title:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        cc = ws.cell(1, 1, title)
        cc.font = Font(bold=True, size=14)
        cc.alignment = center
        r = 1
    if head:
        r += 1
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        cc = ws.cell(r, 1, head)
        cc.font = Font(size=10, color="6B7A90")
        cc.alignment = Alignment(horizontal="right", vertical="center")
    r += 1

    for row in rows:
        col = 1
        for text, span, kind in row:
            cc = ws.cell(r, col, text)
            if span > 1:
                ws.merge_cells(start_row=r, start_column=col, end_row=r, end_column=col + span - 1)
            cc.border = border
            if kind == "label":
                cc.fill = fill_lbl
                cc.font = Font(bold=True)
                cc.alignment = center
            elif kind == "sec":
                cc.fill = fill_sec
                cc.font = Font(bold=True)
                cc.alignment = center
            elif kind == "ok":
                cc.fill = fill_ok
                cc.font = Font(bold=True)
                cc.alignment = center
            elif kind == "ng":
                cc.fill = fill_ng
                cc.font = Font(bold=True)
                cc.alignment = center
            else:
                cc.alignment = left if span > 1 else center
            col += span
        r += 1

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def fill_xlsx_template(template_bytes: bytes, mapping: dict[str, str]) -> bytes:
    """把 .xlsx 模板单元格里的 {{占位符}} 替换为实际值（cell 版自定义报告）。"""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(template_bytes))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    v = cell.value
                    for k, val in mapping.items():
                        v = v.replace("{{" + k + "}}", "" if val is None else str(val))
                    if v != cell.value:
                        cell.value = v
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# .docx 模板占位符填充（跨 run 替换，兼容 Word 把 {{占位符}} 拆到多个 run 的情况）

# ---------------------------------------------------------------------------
def fill_docx_template(template_bytes: bytes, mapping: dict[str, str]) -> bytes:
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(io.BytesIO(template_bytes))
    body = doc.element.body
    for p in body.iter(qn("w:p")):
        texts = list(p.iter(qn("w:t")))
        full = "".join(t.text or "" for t in texts)
        new = full
        for k, v in mapping.items():
            new = new.replace("{{" + k + "}}", "" if v is None else str(v))
        if new == full:
            continue
        runs = p.findall(qn("w:r"))
        if not runs:
            r = p.makeelement(qn("w:r"), {})
            p.append(r)
            runs = [r]
        t = runs[0].find(qn("w:t"))
        if t is None:
            t = runs[0].makeelement(qn("w:t"), {})
            runs[0].append(t)
        t.text = new
        t.set(qn("xml:space"), "preserve")
        for r in runs[1:]:
            p.remove(r)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def docx_to_html(docx_bytes: bytes) -> str:
    """把 .docx 读回为简易 HTML（段落 + 表格，保留加粗）。

    用于「自定义报告」模板填充在无 Word（Linux）环境下的兜底：先用
    fill_docx_template 生成 .docx，再读回为 HTML 供预览/下载。
    """
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(docx_bytes))

    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _inline(p) -> str:
        parts = []
        for r in p.runs:
            t = _esc(r.text or "")
            if not t:
                continue
            parts.append(f"<b>{t}</b>" if r.bold else t)
        return "".join(parts)

    def _para(p) -> str:
        txt = _inline(p)
        if not txt.strip():
            return "<p>&nbsp;</p>"
        align = ""
        try:
            if p.alignment is not None and p.alignment.name == "CENTER":
                align = ' style="text-align:center"'
        except Exception:
            pass
        return f"<p{align}>{txt}</p>"

    def _table(tbl) -> str:
        rows = []
        for row in tbl.rows:
            cells = []
            for cell in row.cells:
                cell_txt = " ".join(_inline(p) for p in cell.paragraphs).strip()
                cells.append(f"<td>{cell_txt or '&nbsp;'}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return "<table>" + "".join(rows) + "</table>"

    out = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            out.append(_para(Paragraph(child, doc)))
        elif child.tag == qn("w:tbl"):
            out.append(_table(Table(child, doc)))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML → 真 .docx（python-docx，供内置报告无模板时兜底生成）
# ---------------------------------------------------------------------------
_VOID = {"br", "img", "hr"}
_BLOCK = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "li", "tr", "td", "th", "thead", "tbody", "tfoot"}


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = attrs
        self.children = []

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), dict(attrs))
        self.stack[-1].children.append(node)
        if tag.lower() not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.lower(), dict(attrs)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)


def _image_bytes(src: str) -> bytes | None:
    if not src:
        return None
    if src.startswith("data:"):
        m = re.match(r"^data:image/[^;]+;base64,(.+)$", src, re.S)
        if m:
            try:
                return base64.b64decode(m.group(1))
            except Exception:
                return None
        return None
    rel = src.lstrip("/")
    fp = STATIC_DIR / rel
    return fp.read_bytes() if fp.exists() else None


def _set_east_asia(rpr, font_name: str):
    from docx.oxml.ns import qn

    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)


def _add_page_footer(doc):
    """页脚居中页码「第 X 页 / 共 Y 页」，让内置报告 .docx 更像正式 Word 模板。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    p = doc.sections[0].footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _field(code):
        run = p.add_run()
        begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = code
        end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
        run._r.append(begin); run._r.append(instr); run._r.append(end)
        return run

    for run in (p.add_run("第 "), _field("PAGE"), p.add_run(" 页 / 共 "), _field("NUMPAGES"), p.add_run(" 页")):
        run.font.size = Pt(9)
        run.font.name = "Microsoft YaHei"


def _setup_document(doc):
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Cm, Pt

    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.top_margin = s.bottom_margin = Cm(2.0)
    s.left_margin = s.right_margin = Cm(2.0)
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)
    try:
        _set_east_asia(style.element.get_or_add_rPr(), "Microsoft YaHei")
    except Exception:
        pass
    _add_page_footer(doc)

def _cell_shade(cell, hexcolor: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def _int_attr(node: _Node, name: str, default: int) -> int:
    try:
        return int(node.attrs.get(name) or default)
    except (TypeError, ValueError):
        return default


def _classes(node: _Node) -> set:
    return set((node.attrs.get("class") or "").split())


def _add_inline(paragraph, children, bold=False, italic=False, underline=False):
    """把内联节点序列渲染为 run / 图片，追加到 paragraph。"""
    from docx.enum.text import WD_BREAK
    from docx.shared import Cm

    for c in children:
        if isinstance(c, str):
            if c:
                run = paragraph.add_run(c)
                run.bold = bold
                run.italic = italic
                run.underline = underline
            continue
        tag = c.tag
        if tag == "br":
            paragraph.add_run().add_break(WD_BREAK.LINE)
        elif tag == "img":
            data = _image_bytes(c.attrs.get("src"))
            if data:
                cls = _classes(c)
                width = Cm(3.0) if "logo" in cls else Cm(15.0)
                try:
                    paragraph.add_run().add_picture(io.BytesIO(data), width=width)
                except Exception:
                    pass
        elif tag in ("b", "strong"):
            _add_inline(paragraph, c.children, True, italic, underline)
        elif tag in ("i", "em"):
            _add_inline(paragraph, c.children, bold, True, underline)
        elif tag in ("u",):
            _add_inline(paragraph, c.children, bold, italic, True)
        elif tag in ("sub", "sup"):
            for cc in c.children:
                if isinstance(cc, str):
                    run = paragraph.add_run(cc)
                    run.font.subscript = (tag == "sub")
                    run.font.superscript = (tag == "sup")
        else:
            _add_inline(paragraph, c.children, bold, italic, underline)


def _render_block(doc, node: _Node):
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    style = (node.attrs.get("style") or "")
    cls = _classes(node)
    p = doc.add_paragraph()
    if "text-align:center" in style or "qm-title" in cls:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if "text-align:right" in style or "form-no" in cls:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _add_inline(p, node.children, bold=("company" in cls))
    # 空段落（占位用的 class="sig" 等）保留一个空行高度，避免塌陷
    return p


def _grid_cols(trs) -> int:
    n = 1
    for tr in trs:
        cells = [c for c in tr.children if isinstance(c, _Node) and c.tag in ("td", "th")]
        n = max(n, sum(_int_attr(c, "colspan", 1) for c in cells))
    return n


def _fill_cell(cell, node: _Node):
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    cls = _classes(node)
    if "lbl" in cls:
        _cell_shade(cell, "F2F2F2")
    elif "qm-sec" in cls:
        _cell_shade(cell, "EEF1F5")
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = cell.paragraphs[0]
    if "qm-sec" in cls or "qm-verdict" in cls or "result-ok" in cls or "result-ng" in cls:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    bold = "lbl" in cls or "qm-sec" in cls or "qm-verdict" in cls or "company" in cls
    _add_inline(p, node.children, bold=bold)


def _render_table(doc, node: _Node):
    from docx.enum.table import WD_TABLE_ALIGNMENT

    trs = [c for c in node.children if isinstance(c, _Node) and c.tag == "tr"]
    if not trs:
        return
    ncols = _grid_cols(trs)
    nrows = len(trs)
    table = doc.add_table(rows=nrows, cols=ncols)
    try:
        table.style = "Table Grid"
    except Exception:
        pass
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    occ = [[False] * ncols for _ in range(nrows)]
    for ri, tr in enumerate(trs):
        ci = 0
        for cell in [c for c in tr.children if isinstance(c, _Node) and c.tag in ("td", "th")]:
            while ci < ncols and occ[ri][ci]:
                ci += 1
            if ci >= ncols:
                break
            cs = min(_int_attr(cell, "colspan", 1), ncols - ci)
            rs = min(_int_attr(cell, "rowspan", 1), nrows - ri)
            tcell = table.cell(ri, ci)
            if cs > 1 or rs > 1:
                tcell = tcell.merge(table.cell(ri + rs - 1, ci + cs - 1))
            _fill_cell(tcell, cell)
            for r in range(ri, ri + rs):
                for c in range(ci, ci + cs):
                    occ[r][c] = True
            ci += cs


_BLANK_DOCX: bytes | None = None


def _blank_docx_bytes() -> bytes:
    """返回可用的空白 .docx 模板字节（绕过本机 TSD 对落盘 .docx 的加密）。

    桌面/系统盘环境会把落盘的 .docx 等二进制文件加密，导致 python-docx 自带
    default.docx 无法读取；正常服务器无此问题。此处优先直接读 default.docx，
    若损坏则用同目录的 default-docx-template 展开目录在内存中重建（结果缓存）。
    """
    global _BLANK_DOCX
    if _BLANK_DOCX is not None:
        return _BLANK_DOCX
    import zipfile

    import docx

    tpl_dir = Path(docx.__file__).parent / "templates"
    default = tpl_dir / "default.docx"
    if default.exists() and zipfile.is_zipfile(default):
        _BLANK_DOCX = default.read_bytes()
        return _BLANK_DOCX
    parts_dir = tpl_dir / "default-docx-template"
    if parts_dir.exists():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(parts_dir):
                for fn in files:
                    fp = Path(root) / fn
                    arc = str(fp.relative_to(parts_dir)).replace(os.sep, "/")
                    z.writestr(arc, fp.read_bytes())
        _BLANK_DOCX = buf.getvalue()
        return _BLANK_DOCX
    raise RuntimeError("python-docx 默认模板缺失且无法重建，无法生成 .docx")


def _render_nodes(doc, children):
    """递归渲染节点序列：表格/块级各自成段，内联与文本并入当前段落。

    支持任意嵌套（如 <div><table>…</table></div>），避免把表格内容拍平成文本。
    """
    for node in children:
        if isinstance(node, str):
            if node.strip():
                doc.add_paragraph(node)
            continue
        tag = node.tag
        if tag == "table":
            _render_table(doc, node)
        elif tag in ("div", "p", "h1", "h2", "h3", "h4", "h5", "h6"):
            has_sub_block = any(
                isinstance(c, _Node) and c.tag in ("table", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6")
                for c in node.children
            )
            if has_sub_block:
                _render_nodes(doc, node.children)
            else:
                _render_block(doc, node)
        elif tag == "br":
            doc.add_paragraph()
        elif tag == "img":
            p = doc.add_paragraph()
            _add_inline(p, [node])
        elif tag in ("ul", "ol"):
            for li in [c for c in node.children if isinstance(c, _Node) and c.tag == "li"]:
                p = doc.add_paragraph(style="List Bullet")
                _add_inline(p, li.children)
        elif tag in _BLOCK:
            _render_block(doc, node)
        else:
            _render_block(doc, node)


def html_to_docx(html: str) -> bytes:
    """把报告正文 HTML 转成真 .docx（含表格/合并单元格/图片/加粗）。"""
    from docx import Document

    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()

    doc = Document(io.BytesIO(_blank_docx_bytes()))
    _setup_document(doc)
    _render_nodes(doc, builder.root.children)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
