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
# 文档 key：自描述 + HMAC 签名，无需持久化映射（无状态、多实例安全）
# ---------------------------------------------------------------------------
def make_key(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    b64 = base64.urlsafe_b64encode(body.encode("utf-8")).decode().rstrip("=")
    sig = hmac.new(ONLYOFFICE_JWT_SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{b64}.{sig}"


def parse_key(key: str) -> dict:
    b64, sig = key.rsplit(".", 1)
    expect = hmac.new(ONLYOFFICE_JWT_SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expect, sig):
        raise ValueError("文档 key 签名校验失败")
    pad = "=" * (-len(b64) % 4)
    return json.loads(base64.urlsafe_b64decode(b64 + pad).decode("utf-8"))


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
