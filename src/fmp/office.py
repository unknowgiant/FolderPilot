# -*- coding: utf-8 -*-
"""Office 文档的轻量内容提取（xlsx / docx / pptx）。

不依赖 openpyxl、python-docx：这三个格式本质是 zip + XML，用标准库
zipfile + ElementTree 直接读，不增加任何打包体积。

只做「看得懂内容」这一件事：
  · xlsx → 每个工作表的名字 + 前若干行单元格（含共享字符串、日期还原）
  · docx → 段落文本（表格里的文字也会按段落顺序出现）
  · pptx → 每页的文字
读不出来（文件损坏、旧版 .xls/.doc 二进制格式）时抛 PreviewError，
由调用方转成一句人话提示，而不是把二进制当文本显示成乱码。
"""
from __future__ import annotations

import datetime
import re
import zipfile
import xml.etree.ElementTree as ET

from .model import long_path

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

M = "{%s}" % MAIN_NS
W = "{%s}" % W_NS
A = "{%s}" % A_NS

MAX_SHEETS = 3
MAX_ROWS = 80
MAX_COLS = 18
MAX_PARAS = 500
MAX_SLIDES = 40

# Excel 内建日期格式编号
BUILTIN_DATE_FMT = set(range(14, 23)) | {27, 30, 36, 45, 46, 47, 50, 57}


class PreviewError(Exception):
    pass


# ───────────────────────── xlsx ─────────────────────────

def _text_of(node) -> str:
    """<si> / <is> 下所有 <t> 的拼接（富文本会拆成多个 <r><t>）。"""
    return "".join(t.text or "" for t in node.iter(M + "t"))


def _shared_strings(z: zipfile.ZipFile):
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text_of(si) for si in root.findall(M + "si")]


def _date_style_ids(z: zipfile.ZipFile) -> set:
    """返回「按日期显示」的 cellXfs 索引集合。"""
    try:
        root = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return set()
    custom = {}
    for nf in root.findall(M + "numFmts/" + M + "numFmt"):
        try:
            custom[int(nf.get("numFmtId"))] = nf.get("formatCode") or ""
        except (TypeError, ValueError):
            continue
    out = set()
    xfs = root.find(M + "cellXfs")
    if xfs is None:
        return out
    for idx, xf in enumerate(xfs.findall(M + "xf")):
        try:
            fid = int(xf.get("numFmtId") or -1)
        except ValueError:
            continue
        if fid in BUILTIN_DATE_FMT:
            out.add(idx)
        elif fid in custom:
            code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom[fid])
            if re.search(r"[ymdhs]", code, re.I) and "0.0" not in code:
                out.add(idx)
    return out


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return max(0, n - 1)


def _num(v: str):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if f == int(f) and abs(f) < 1e15:
        return int(f)
    return round(f, 10)


def _cell_value(c, shared, date_styles):
    t = c.get("t")
    if t == "inlineStr":
        node = c.find(M + "is")
        return _text_of(node) if node is not None else ""
    v = c.find(M + "v")
    if v is None or v.text is None:
        return ""
    raw = v.text
    if t == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if t == "b":
        return "TRUE" if raw.strip() == "1" else "FALSE"
    if t in ("str", "e"):
        return raw
    val = _num(raw)
    try:
        if int(c.get("s") or -1) in date_styles and isinstance(val, (int, float)):
            dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(val))
            return dt.strftime("%Y-%m-%d") if dt.hour == 0 and dt.minute == 0 else dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError):
        pass
    return val


def read_xlsx(path: str):
    out = {"sheets": [], "truncated": False, "total_sheets": 0}
    try:
        with zipfile.ZipFile(long_path(path)) as z:
            names = set(z.namelist())
            shared = _shared_strings(z)
            dates = _date_style_ids(z)
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rels = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rr = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                for rel in rr:
                    rels[rel.get("Id")] = rel.get("Target") or ""
            sheets = wb.findall(".//" + M + "sheets/" + M + "sheet")
            out["total_sheets"] = len(sheets)
            for sh in sheets[:MAX_SHEETS]:
                name = sh.get("name") or "Sheet"
                target = rels.get(sh.get("{%s}id" % REL_NS), "")
                target = target.lstrip("/")
                if not target:
                    continue
                if not target.startswith("xl/"):
                    target = "xl/" + target
                if target not in names:
                    continue
                root = ET.fromstring(z.read(target))
                rows = []
                for row in root.iter(M + "row"):
                    cells = {}
                    for c in row.findall(M + "c"):
                        idx = _col_index(c.get("r") or "")
                        if idx >= MAX_COLS:
                            continue
                        cells[idx] = _cell_value(c, shared, dates)
                    if not cells:
                        continue
                    width = max(cells) + 1
                    rows.append([cells.get(i, "") for i in range(width)])
                    if len(rows) >= MAX_ROWS:
                        out["truncated"] = True
                        break
                out["sheets"].append({"name": name, "rows": rows})
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as ex:
        raise PreviewError("这个 Excel 文件解析不了（%s）" % ex)
    return out


# ───────────────────────── docx ─────────────────────────

def read_docx(path: str):
    try:
        with zipfile.ZipFile(long_path(path)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as ex:
        raise PreviewError("这个 Word 文件解析不了（%s）" % ex)
    paras = []
    for p in root.iter(W + "p"):
        buf = []
        for node in p.iter():
            if node.tag == W + "t":
                buf.append(node.text or "")
            elif node.tag == W + "tab":
                buf.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                buf.append("\n")
        text = "".join(buf).strip()
        if text:
            paras.append(text)
        if len(paras) >= MAX_PARAS:
            break
    return {"paragraphs": paras, "truncated": len(paras) >= MAX_PARAS}


# ───────────────────────── pptx ─────────────────────────

def read_pptx(path: str):
    slides = []
    try:
        with zipfile.ZipFile(long_path(path)) as z:
            names = [n for n in z.namelist()
                     if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
            names.sort(key=lambda n: int(re.search(r"(\d+)", n.split("/")[-1]).group(1)))
            truncated = len(names) > MAX_SLIDES
            for i, n in enumerate(names[:MAX_SLIDES], 1):
                root = ET.fromstring(z.read(n))
                texts = [t.text.strip() for t in root.iter(A + "t")
                         if t.text and t.text.strip()]
                slides.append({"index": i, "texts": texts})
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as ex:
        raise PreviewError("这个 PowerPoint 文件解析不了（%s）" % ex)
    return {"slides": slides, "truncated": truncated, "total_slides": len(names)}


def office_preview(path: str, ext: str):
    if ext == "xlsx" or ext == "xlsm":
        return {**read_xlsx(path), "preview": "sheet"}
    if ext == "docx":
        return {**read_docx(path), "preview": "doc"}
    if ext == "pptx":
        return {**read_pptx(path), "preview": "slides"}
    raise PreviewError("旧版 .%s 是二进制格式，无法内嵌预览，可用系统程序打开" % ext)
