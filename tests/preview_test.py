# -*- coding: utf-8 -*-
"""预览功能自测：文件夹列内部文件、Office 文档解析出内容、二进制不再当文本。

用法：py -3.14 tests/preview_test.py
产物：tests/output/preview_report.json

测试用的 xlsx / docx / pptx 由本脚本现场拼装（zip + 最小 XML），
不依赖任何 Office 组件，也不碰真实文档。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fmp import fs, office  # noqa: E402

report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
      'package/2006/content-types"/>')
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def make_xlsx(path):
    sst = ('<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/'
           'spreadsheetml/2006/main" count="4" uniqueCount="4">'
           '<si><t>姓名</t></si><si><t>金额</t></si><si><t>张三</t></si><si><t>李四</t></si></sst>')
    wb = ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/'
          'spreadsheetml/2006/main" xmlns:r="%s"><sheets>'
          '<sheet name="明细" sheetId="1" r:id="rId1"/></sheets></workbook>' % NS_R)
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats'
            '.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>' % NS_R)
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>1234.5</v></c></row>'
             '<row r="3"><c r="A3" t="s"><v>3</v></c><c r="C3" t="inlineStr"><is><t>备注</t></is></c></row>'
             '</sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)


def make_docx(path):
    body = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats'
            '.org/wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>第一段标题</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>第二段</w:t></w:r><w:r><w:t>（续）</w:t></w:r></w:p>'
            '<w:p/>'
            '</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("word/document.xml", body)


def make_pptx(path):
    slide = ('<?xml version="1.0" encoding="UTF-8"?><sld xmlns="http://schemas.openxmlformats.org/'
             'presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/'
             'drawingml/2006/main"><a:t>封面标题</a:t><a:t>副标题</a:t></sld>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("ppt/slides/slide1.xml", slide)


def main():
    tmp = tempfile.mkdtemp(prefix="fmp_preview_")

    # 1) 文件夹：列出内部所有条目，目录在前
    folder = os.path.join(tmp, "工程目录")
    os.makedirs(os.path.join(folder, "子文件夹"), exist_ok=True)
    for name in ("a.txt", "b.xlsx"):
        open(os.path.join(folder, name), "wb").write(b"x")
    r = fs.preview_info(folder)
    check("dir.type", r["preview"] == "dir", r["preview"])
    check("dir.total", r.get("total") == 3, r.get("total"))
    names = [x["name"] for x in r.get("items", [])]
    check("dir.first_is_folder", bool(names) and names[0] == "子文件夹", names)
    check("dir.has_files", set(names) == {"子文件夹", "a.txt", "b.xlsx"}, names)
    check("dir.item_path", all(x.get("path") and os.path.isabs(x["path"])
                               for x in r.get("items", [])), "缺少绝对路径")

    # 2) xlsx：解析出表名与单元格，不是乱码
    xlsx = os.path.join(tmp, "报表.xlsx")
    make_xlsx(xlsx)
    r = fs.preview_info(xlsx)
    check("xlsx.type", r["preview"] == "sheet", r.get("error") or r["preview"])
    if r["preview"] == "sheet":
        sh = r["sheets"][0]
        check("xlsx.sheet_name", sh["name"] == "明细", sh["name"])
        check("xlsx.header", sh["rows"][0] == ["姓名", "金额"], sh["rows"][:1])
        check("xlsx.value", sh["rows"][1] == ["张三", 1234.5], sh["rows"][1:2])
        check("xlsx.inline", sh["rows"][2] == ["李四", "", "备注"], sh["rows"][2:3])

    # 3) docx：段落文本
    docx = os.path.join(tmp, "说明.docx")
    make_docx(docx)
    r = fs.preview_info(docx)
    check("docx.type", r["preview"] == "doc", r.get("error") or r["preview"])
    if r["preview"] == "doc":
        check("docx.paras", r["paragraphs"] == ["第一段标题", "第二段（续）"], r["paragraphs"])

    # 4) pptx：每页文字
    pptx = os.path.join(tmp, "课件.pptx")
    make_pptx(pptx)
    r = fs.preview_info(pptx)
    check("pptx.type", r["preview"] == "slides", r.get("error") or r["preview"])
    if r["preview"] == "slides":
        check("pptx.text", r["slides"][0]["texts"] == ["封面标题", "副标题"], r["slides"][0])

    # 5) 二进制文件不能当文本念（关键回归：以前 exe/dll 会显示乱码）
    binp = os.path.join(tmp, "程序.exe")
    open(binp, "wb").write(b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 600)
    r = fs.preview_info(binp)
    check("binary.type", r["preview"] == "binary", r["preview"])
    check("binary.has_hint", bool(r.get("error")), r.get("error"))

    # 6) 旧版 .xls 给明确提示，不是乱码
    xls = os.path.join(tmp, "旧表.xls")
    open(xls, "wb").write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512)
    r = fs.preview_info(xls)
    check("legacy_office.hint", r["preview"] == "none" and "旧版" in (r.get("error") or ""),
          r.get("error"))

    # 7) 纯文本仍然正常
    txt = os.path.join(tmp, "说明.txt")
    open(txt, "w", encoding="utf-8").write("中文文本预览\n第二行")
    r = fs.preview_info(txt)
    check("text.ok", r["preview"] == "text" and "中文文本预览" in r.get("text", ""), r["preview"])

    # 8) 空文件夹不报错
    empty = os.path.join(tmp, "空目录")
    os.makedirs(empty, exist_ok=True)
    r = fs.preview_info(empty)
    check("empty_dir", r["preview"] == "dir" and r["total"] == 0, r.get("total"))

    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    json.dump(report, open(os.path.join(out, "preview_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    total = len(report["checks"])
    ok = sum(1 for c in report["checks"] if c["ok"])
    print("预览自测：%d/%d 通过" % (ok, total))
    for c in report["checks"]:
        if not c["ok"]:
            print("  FAIL %s — %s" % (c["name"], c["detail"]))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
