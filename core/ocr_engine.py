# -*- coding: utf-8 -*-
"""
ocr_engine.py —— PC 端 Tesseract 真识别（仅桌面，不联网、不上传图片）

职责边界（务必如实）：
  * 本模块只做「本机图片 -> 文字」的识别，字段整理继续交给 core/ocrkit.py 规则层。
  * 引擎找不到、缺中文包、识别失败时一律明确降级，绝不返回假结果。
  * 核心逻辑本地执行；本模块不做任何下载，引擎与语言包由用户本机准备。

引擎查找顺序（命中即用，不改动系统设置）：
  1. 环境变量 TESSERACT_CMD
  2. 项目便携版 tools/tesseract/tesseract.exe（Windows）/ tesseract（其他）
  3. 系统 PATH
  4. Windows 常见安装目录 Program Files\\Tesseract-OCR
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
DEFAULT_LANG = "chi_sim+eng"


# ---------------------------------------------------------------------------
# 引擎检测
# ---------------------------------------------------------------------------

@dataclass
class EngineInfo:
    """Tesseract 引擎状态。usable 要求既找到程序、又有中文语言包。"""
    found: bool = False
    exe: str = ""
    version: str = ""
    langs: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def chinese(self) -> bool:
        return "chi_sim" in self.langs

    @property
    def usable(self) -> bool:
        return self.found and self.chinese


def _candidates() -> list[tuple[str, str]]:
    """列出可能的 tesseract 可执行文件位置（按优先级）。"""
    out: list[tuple[str, str]] = []
    env = (os.environ.get("TESSERACT_CMD") or "").strip()
    if env:
        out.append((env, "环境变量 TESSERACT_CMD"))

    exe_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    out.append((str(ROOT / "tools" / "tesseract" / exe_name), "项目便携版 tools/tesseract"))

    which = shutil.which("tesseract")
    if which:
        out.append((which, "系统 PATH"))

    if os.name == "nt":
        for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            out.append((p, "常见安装目录"))
    return out


def _run_cli(exe: str, args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    """统一执行 tesseract 命令，输出按 UTF-8 解码（tesseract 输出为 UTF-8）。"""
    return subprocess.run(
        [exe] + args,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def detect() -> EngineInfo:
    """检测本机可用引擎；不抛异常，失败返回 found=False。"""
    for exe, source in _candidates():
        if not exe or not Path(exe).is_file():
            continue
        try:
            v = _run_cli(exe, ["--version"], timeout=8)
        except Exception:
            continue
        banner = (v.stdout or "") + (v.stderr or "")
        if v.returncode != 0 or "tesseract" not in banner.lower():
            continue

        langs: list[str] = []
        try:
            lg = _run_cli(exe, ["--list-langs"], timeout=8)
            for line in (lg.stdout or "").splitlines() + (lg.stderr or "").splitlines():
                item = line.strip()
                # --list-langs 的表头是 "List of available languages ..."
                if item and not item.lower().startswith("list of"):
                    langs.append(item)
        except Exception:
            pass

        version = (v.stdout or "").strip().splitlines()[0] if (v.stdout or "").strip() else ""
        return EngineInfo(True, exe, version, langs, source)
    return EngineInfo()


# ---------------------------------------------------------------------------
# 真识别
# ---------------------------------------------------------------------------

@dataclass
class OcrResult:
    """识别结果。ok=False 时 error 是人话原因，text 为空。"""
    ok: bool = False
    text: str = ""
    lang: str = DEFAULT_LANG
    version: str = ""
    error: str = ""


def build_command(exe: str, image_path: str, lang: str = DEFAULT_LANG) -> list[str]:
    """构造识别命令，单独成函数便于自测断言。"""
    return [exe, image_path, "stdout", "-l", lang, "--psm", "6"]


def recognize(image_path: str, lang: str = DEFAULT_LANG,
              info: EngineInfo | None = None) -> OcrResult:
    """识别一张本机图片。失败全部转成 OcrResult(error=...)，不抛异常。"""
    info = info if info is not None else detect()
    if not info.found:
        return OcrResult(error="未检测到 Tesseract 引擎，当前为降级模式。")
    if "chi_sim" in lang and not info.chinese:
        return OcrResult(error="已找到 Tesseract，但缺少中文语言包 chi_sim，无法识别中文。")

    p = Path(image_path)
    if not p.is_file():
        return OcrResult(error="图片文件不存在，请重新选择。")
    if p.suffix.lower() not in IMAGE_EXTS:
        return OcrResult(error="仅支持 png / jpg / jpeg / bmp / tif / tiff 图片。")

    try:
        r = _run_cli(info.exe, build_command(info.exe, str(p), lang)[1:], timeout=90)
    except subprocess.TimeoutExpired:
        return OcrResult(error="识别超时，请换一张更小的清晰图片重试。")
    except Exception as e:
        return OcrResult(error=f"识别调用失败：{e}")

    if r.returncode != 0:
        msg = (r.stderr or "").strip()[:200] or f"退出码 {r.returncode}"
        return OcrResult(error=f"Tesseract 报错：{msg}")
    text = (r.stdout or "").strip()
    if not text:
        return OcrResult(error="图片里没识别出文字，请换清晰、正立的原图重试。")
    return OcrResult(True, text, lang, info.version)


# ---------------------------------------------------------------------------
# OCR 文本 -> 字段（喂给 ocrkit 规则层，不猜不补）
# ---------------------------------------------------------------------------

# 常见票面标签 -> 标准字段名；只做同义归一，不凭空补字段
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "户名": ("户名", "账户名称", "客户名称", "姓名"),
    "对方户名": ("对方户名", "收款方", "付款方", "对方账户名称"),
    "账号尾号": ("账号尾号", "卡尾号", "尾号"),
    "交易日期": ("交易日期", "记账日期", "日期"),
    "开票日期": ("开票日期", "日期"),
    "签订日期": ("签订日期", "日期"),
    "答复期限": ("答复期限", "回复期限"),
    "金额": ("金额", "交易金额", "发生额", "价税合计", "小写金额"),
    "余额": ("余额",),
    "文号": ("文号", "字号", "文件编号"),
    "作出机关": ("作出机关", "机关", "执法机关"),
    "收件人": ("收件人", "收件人姓名"),
    "地址": ("地址", "收件地址"),
    "单号": ("单号", "运单号", "快递单号", "EMS单号"),
    "发票代码": ("发票代码",),
    "发票号码": ("发票号码",),
    "销售方": ("销售方", "销方"),
    "购买方": ("购买方", "购方"),
    "发言人": ("发言人", "发送人"),
    "内件品名": ("内件品名", "内件"),
}

# 关键实体：只在票面明确写有时才提取，不做推断（C2 红线）
MONEY_RE = re.compile(r"(?:[¥￥]\s*(\d[\d,]*(?:\.\d{1,2})?)\s*元?|(\d[\d,]*(?:\.\d{1,2})?)\s*元)")
DATE_RE = re.compile(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})\s*日?")
DOCNO_RE = re.compile(r"[\u4e00-\u9fa5]{0,10}[〔\[（(]\s*(20\d{2})\s*[〕\]）)]\s*第?\s*(\d{1,5})\s*号")
WAYBILL_RE = re.compile(r"(?:EMS\s*[:：]?\s*|运单号\s*[:：]?\s*|单号\s*[:：]?\s*)(\d{10,20})")


def normalize_text(text: str) -> str:
    """全角数字/冒号转半角，压缩多余空格，方便后续正则。"""
    out = []
    for ch in text or "":
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:          # 全角数字
            out.append(chr(code - 0xFEE0))
        elif ch in "：":                       # 全角冒号
            out.append(":")
        elif ch in "，":                       # 全角逗号（金额千分位）
            out.append(",")
        elif ch in "\u3000":                   # 全角空格
            out.append(" ")
        else:
            out.append(ch)
    return re.sub(r"[ \t]+", " ", "".join(out))


def _standard_field(label: str) -> str:
    """把票面标签归一到标准字段名；没有对应清单就返回原标签。"""
    key = label.strip()
    for standard, aliases in FIELD_ALIASES.items():
        if key in aliases:
            return standard
    return key


MONEY_FIELDS = {"金额", "余额"}
DATE_FIELDS = {"交易日期", "开票日期", "签订日期", "日期", "答复期限"}


def _clean_value(key: str, val: str) -> str:
    """清洗标签值：金额去货币符号/千分位，日期统一成 YYYY-MM-DD。"""
    if key in MONEY_FIELDS:
        m = MONEY_RE.search(val)
        if m:
            return (m.group(1) or m.group(2)).replace(",", "")
        if re.fullmatch(r"[\d,]+(?:\.\d+)?", val):
            return val.replace(",", "")
    if key in DATE_FIELDS:
        m = DATE_RE.search(val)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return val


def _labeled_fields(text: str) -> dict[str, str]:
    """逐行解析「标签: 值」，兼容冒号与等号。"""
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"[:=]\s*", line, maxsplit=1)
        if len(parts) != 2:
            continue
        key = _standard_field(parts[0])
        val = parts[1].strip()
        if key and val and len(key) <= 12:
            out.setdefault(key, _clean_value(key, val))
    return out


def _entity_fields(text: str, fields: dict[str, str]) -> None:
    """从自由文本补关键实体；只在标准字段为空时填，不覆盖明确标签值。"""
    if not fields.get("金额"):
        m = MONEY_RE.search(text)
        if m:
            fields["金额"] = (m.group(1) or m.group(2)).replace(",", "")
    if not fields.get("交易日期") and not fields.get("开票日期") and not fields.get("日期"):
        m = DATE_RE.search(text)
        if m:
            fields["交易日期"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if not fields.get("文号"):
        m = DOCNO_RE.search(text)
        if m:
            fields["文号"] = f"〔{m.group(1)}〕第{m.group(2)}号"
    if not fields.get("单号"):
        m = WAYBILL_RE.search(text)
        if m:
            fields["单号"] = m.group(1)


def extract_fields(doc_type: str, text: str) -> dict[str, str]:
    """
    从 OCR 文本提取字段。doc_type 参数目前保留（供后续按类型细化），
    本版统一走「标签 + 关键实体」两条稳妥规则，宁缺勿猜。
    """
    clean = normalize_text(text)
    fields = _labeled_fields(clean)
    _entity_fields(clean, fields)
    return fields


def to_entry_text(fields: dict[str, str]) -> str:
    """转成「字段名：值」每行一条，直接填进识图弹窗的录入框。"""
    return "\n".join(f"{k}：{v}" for k, v in fields.items() if v)


# ---------------------------------------------------------------------------
# 选图 + 安装引导
# ---------------------------------------------------------------------------

def pick_image() -> str | None:
    """PC 文件选择器，返回图片绝对路径；不可用时返回 None（不假装成功）。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="选择要识别的证据图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("所有文件", "*.*")],
        )
        root.destroy()
        return path or None
    except Exception:
        return None


def install_hint() -> str:
    """给用户的本地安装说明：说清怎么装，也说明不装仍可手动录入。"""
    return (
        "【当前为降级模式】没检测到可用的 Tesseract 中文识别环境，未对图片做识别。\n"
        "电脑端启用方法（任选一）：\n"
        "  1) 管理员 PowerShell 执行 winget install UB-Mannheim.TesseractOCR，"
        "安装时勾选 Chinese Simplified (chi_sim)；\n"
        "  2) 把 tesseract.exe 与 tessdata 放到项目 tools/tesseract/ 目录；\n"
        "  3) 设环境变量 TESSERACT_CMD 指向 tesseract.exe。\n"
        "不装也能用：下方手动录入与整理成表照常可用。"
    )


def engine_status_text(info: EngineInfo) -> str:
    """识图弹窗顶部状态行：有引擎说就绪，没引擎说清降级与安装方法。"""
    if info.usable:
        ver = info.version.split(",")[0] or "已安装"
        return (f"Tesseract 已就绪（{ver}，中文包可用，来源：{info.source}）。"
                "点下方「选图识别」自动提取字段，可修改后再整理成表。")
    if info.found:
        return ("【降级模式】已找到 Tesseract，但没有中文包 chi_sim，"
                "无法识别中文票据。请安装中文语言包；也可在下方手动录入。")
    return install_hint()


if __name__ == "__main__":
    e = detect()
    assert isinstance(e, EngineInfo)
    assert "tesseract.exe" in " ".join(build_command("tesseract.exe", "a.png"))
    n = normalize_text("金额：￥３，５００元\n日期：２０２６年３月５日")
    f = extract_fields("银行流水/对账单", n)
    assert f["金额"] == "3500" and f["交易日期"] == "2026-03-05", f
    assert to_entry_text({"金额": "3500"}) == "金额：3500"
    print("OCR_ENGINE_OK", e.found, e.chinese)
