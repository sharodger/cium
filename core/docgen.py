# -*- coding: utf-8 -*-
"""
docgen.py —— 文书生成（对应功能增强块 D 节）

D3 正式函件排版：标题居中、收件方顶格、正文"事实/依据/请求/时限"四段、
    落款日期附件齐全、依据标"待核实"、无侮辱威胁表达。
D5 命名存储：日期_文书类型_对方主体.docx，存"业主维权AI助手"文件夹，
    同名不覆盖、追加序号。
D6 生成后告知：报出文件名与完整路径，列出需人工确认的字段。
D7 降级：无 python-docx（移动端）→ 纯文本模板，明确说"未生成 docx 文件"。

平台边界：python-docx 纯 Python，PC 可生成标准 docx；移动端构建通常不带它，
导入失败即自动走纯文本模板。全程本地，不上传任何内容。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# 兼容两种运行方式：app 里从项目根导入；单文件自检时把上一级加入 path
try:
    from core.evidence import mask_sensitive
except ModuleNotFoundError:  # pragma: no cover - 仅单文件自检触发
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.evidence import mask_sensitive

FOLDER_NAME = "业主维权AI助手"


@dataclass
class DocRequest:
    """成文请求：字段齐备后由界面层构造。"""
    doc_type: str                          # 文书类型，如 财务质询函
    party: str                             # 收件方全称
    title: str = ""                        # 标题，默认=文书类型
    sections: list[tuple[str, str]] = field(default_factory=list)  # (小标题, 正文)
    attachments: list[str] = field(default_factory=list)          # 附件清单
    drafter: str = "业主（签名）"           # 落款，D8：不替用户签名，仅占位
    output_dir: Path | None = None         # 指定目录；None 用默认文件夹

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.doc_type
        # D8：输出脱敏，不生成含敏感明文/侮辱威胁的文书
        self.party = mask_sensitive(self.party)
        self.sections = [(h, mask_sensitive(b)) for h, b in self.sections]


@dataclass
class DocResult:
    """生成结果。generated=True 表示真的落盘了 docx。"""
    generated: bool
    path: Path | None          # generated 时为文件路径；降级时 None
    filename: str              # 文件名（docx 或 .txt 模板）
    text: str                  # 纯文本模板内容（降级时供复制）
    needs_confirm: list[str] = field(default_factory=list)  # 需人工确认字段


def _safe_name(part: str, limit: int = 20) -> str:
    """文件名安全化：去掉非法字符，限制长度（D5）。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]', "", str(part)).strip()
    return cleaned[:limit] or "对方主体"


def docx_filename(req: DocRequest, today: date | None = None) -> str:
    """D5：日期_文书类型_对方主体.docx"""
    d = (today or date.today()).strftime("%Y%m%d")
    return f"{d}_{_safe_name(req.doc_type, 16)}_{_safe_name(req.party)}.docx"


def _unique_path(folder: Path, filename: str) -> Path:
    """同名不覆盖，追加 (2)(3)…（D5）。"""
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = folder / filename
    i = 2
    while candidate.exists():
        candidate = folder / f"{stem}({i}){suffix}"
        i += 1
    return candidate


def _needs_confirm(req: DocRequest) -> list[str]:
    """D6：列出需人工确认的字段。"""
    need = ["金额", "日期", "文号", "落款人"]
    text = " ".join(b for _, b in req.sections) + " ".join(req.attachments)
    return [k for k in need if k in text or k == "落款人"]


def text_template(req: DocRequest) -> str:
    """D7：纯文本模板，明确标注未生成 docx 文件。"""
    lines: list[str] = [req.title, "", f"收件方：{req.party}", ""]
    for heading, body in req.sections:
        lines += [f"{heading}：", body, ""]
    lines.append("落款：" + req.drafter)
    lines.append("日期：" + date.today().strftime("%Y年%m月%d日"))
    if req.attachments:
        lines.append("附件：" + "、".join(req.attachments))
    lines += [
        "",
        "【当前环境未生成 docx 文件，这是一份可复制的模板，",
        " 请复制到 Word / WPS 后核对金额、日期、文号、落款并手写签名。】",
    ]
    return "\n".join(lines)


def generate(req: DocRequest) -> DocResult:
    """
    生成文书：优先 python-docx 生成标准 docx；不可用则降级纯文本模板。
    任何情况下都不谎称已生成文件（D7/G2）。
    """
    needs_confirm = _needs_confirm(req)
    template = text_template(req)

    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return DocResult(
            generated=False,
            path=None,
            filename=docx_filename(req).replace(".docx", ".txt"),
            text=template,
            needs_confirm=needs_confirm,
        )

    doc = Document()
    head = doc.add_heading(req.title, level=1)
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.add_run(f"收件方：{req.party}").bold = True

    for heading, body in req.sections:
        doc.add_heading(heading, level=2)
        doc.add_paragraph(body)

    doc.add_paragraph("落款：" + req.drafter)
    doc.add_paragraph("日期：" + date.today().strftime("%Y年%m月%d日"))
    if req.attachments:
        doc.add_paragraph("附件：" + "、".join(req.attachments))

    folder = Path(req.output_dir) if req.output_dir else (Path.home() / FOLDER_NAME)
    folder.mkdir(parents=True, exist_ok=True)
    path = _unique_path(folder, docx_filename(req))
    doc.save(str(path))

    return DocResult(
        generated=True,
        path=path,
        filename=path.name,
        text=template,
        needs_confirm=needs_confirm,
    )


def describe_result(result: DocResult) -> str:
    """D6：生成后告知——文件名、完整路径、需人工确认字段。"""
    if result.generated and result.path:
        head = (f"已生成文书：{result.filename}\n"
                f"路径：{result.path}\n"
                "已生成，可直接点开核对。")
    else:
        head = (f"当前为降级模式：未生成 docx 文件（文件名为 {result.filename}）。\n"
                "下面是可复制的模板，请复制到 Word / WPS 使用。")
    if result.needs_confirm:
        head += "\n需人工确认：" + "、".join(result.needs_confirm) + "；请手写签名并补充附件。"
    return head


if __name__ == "__main__":
    req = DocRequest(
        doc_type="财务质询函",
        party="XX物业",
        sections=[
            ("事实", "多年未公示公共收益，业主多次口头询问无果。"),
            ("依据", "相关规定（具体条款待核实）。"),
            ("请求", "书面公开公共收益台账与银行流水。"),
            ("时限", "收到本函七日内书面答复。"),
        ],
        attachments=["现场照片"],
    )
    result = generate(req)
    assert result.generated and result.path and result.path.exists()
    assert result.filename.startswith("20") and result.filename.endswith(".docx")
    print("docgen:", result.filename)
    print(describe_result(result))
    assert "未生成" in describe_result(DocResult(False, None, "x.txt", "模板"))
    print("DOCGEN_OK")
