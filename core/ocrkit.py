# -*- coding: utf-8 -*-
"""
ocrkit.py —— OCR 规则层（纯文本辅助，不依赖 Tesseract / 任何引擎）

对应《语音OCR文档处理-功能增强块》C 节中，规则引擎就能落地的部分：
  * C3 分类型识别要点：六类材料的字段清单（流水/发票/合同/整改书/截图/面单）
  * C2 结构化输出：手动录入 -> 字段表（置信度 + "待核实"，不猜不补）
  * C4 交叉比对：两份材料的共同字段比对，差异单列
  * C5 证据效力诊断：原图、连续拍摄、时间水印提示
  * C8 脱敏：复用 evidence.mask_sensitive
  * C7 降级：本版本不读图片内容，明确告知用户手动录入

边界（务必如实）：本模块不识别图片、不读取文档内容，只处理用户手动录入的文字。
真正的图像识别需 Tesseract 引擎（待办功能），届时把识别结果喂进来即可，
本模块的字段表/比对/诊断逻辑可直接复用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 兼容两种运行方式：app 里从项目根导入；单文件自检时把上一级加入 path
import sys
from pathlib import Path
try:
    from core.evidence import Field, render_fields_table, mask_sensitive
except ModuleNotFoundError:  # pragma: no cover - 仅单文件自检触发
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.evidence import Field, render_fields_table, mask_sensitive


# ---------------------------------------------------------------------------
# C3 分类型识别要点：六类材料应提取的字段
# ---------------------------------------------------------------------------

DOC_SPECS: dict[str, list[str]] = {
    "银行流水/对账单": ["户名", "账号尾号", "交易日期", "金额", "收/付方向",
                  "对方户名", "摘要", "余额"],
    "发票/收据": ["发票代码", "发票号码", "开票日期", "金额", "销售方", "购买方", "事由"],
    "物业服务合同": ["签署主体", "签订日期", "服务期限", "收费条款", "服务等级", "签章页"],
    "整改书/决定书": ["文号", "作出机关", "日期", "认定事实", "依据条款",
                  "整改要求", "答复期限", "签章"],
    "聊天记录截图": ["时间", "发言人", "昵称头像可辨", "内容完整", "有无上下文"],
    "EMS面单/送达回执": ["内件品名", "收件人", "地址", "寄件日期", "单号", "签收状态"],
}

# 关键实体（金额/日期/文号/账号等）：手动录入也只给"中"置信度，提示核对（C2 红线）
KEY_FIELDS: set[str] = {
    "金额", "日期", "交易日期", "开票日期", "签订日期", "答复期限",
    "文号", "账号尾号", "发票代码", "发票号码", "单号", "余额",
}

# 常见俗称 -> 标准字段名，方便业主按口语录入
ALIAS: dict[str, str] = {
    "收款方": "对方户名", "对方账户": "对方户名", "钱": "金额",
    "数额": "金额", "签名盖章": "签章页", "日期": "日期",
}


# ---------------------------------------------------------------------------
# C2 手动录入 -> 结构化字段表
# ---------------------------------------------------------------------------

def parse_manual_entry(text: str) -> dict[str, str]:
    """解析"字段：值"，每行一条；支持中文/英文冒号与等号。"""
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"[:：=]\s*", line, maxsplit=1)
        if len(parts) != 2:
            continue
        key, val = parts[0].strip(), parts[1].strip()
        key = ALIAS.get(key, key)
        if key and val:
            out[key] = val
    return out


def build_fields(doc_type: str, provided: dict[str, str]) -> list[Field]:
    """
    按该材料类型的字段清单生成 Field（复用 evidence.Field）：
      * 未提供 -> 低置信度（display_value 自动标"待核实"）
      * 关键实体 -> 中置信度，备注请核对
      * 其余 -> 高置信度
      * 清单外的补充字段也保留
    所有值先经 mask_sensitive 脱敏（C8）。
    """
    specs = DOC_SPECS.get(doc_type, [])
    fields: list[Field] = []
    for name in specs:
        val = str(provided.get(name, "")).strip()
        if not val:
            fields.append(Field(name, "", "低", "未提供，请补充"))
            continue
        shown = mask_sensitive(val)
        if name in KEY_FIELDS:
            fields.append(Field(name, shown, "中", "手动录入，请核对原始凭证"))
        else:
            fields.append(Field(name, shown, "高", "手动录入"))
    for name, val in provided.items():
        if name not in specs:
            fields.append(Field(name, mask_sensitive(str(val)), "中", "补充字段，请核对"))
    return fields


def render_material_table(doc_type: str, provided: dict[str, str]) -> str:
    """C2 入口：给出某类材料的结构化字段表。"""
    return render_fields_table(build_fields(doc_type, provided))


# ---------------------------------------------------------------------------
# C4 交叉比对
# ---------------------------------------------------------------------------

@dataclass
class Diff:
    field: str
    label_a: str
    value_a: str
    label_b: str
    value_b: str


def cross_check(label_a: str, a: dict[str, str],
                label_b: str, b: dict[str, str]) -> list[Diff]:
    """比对两份材料的字段：值不同或一方缺失均记为差异。"""
    diffs: list[Diff] = []
    for key in a:
        if key in b and str(a[key]).strip() != str(b[key]).strip():
            diffs.append(Diff(key, label_a, str(a[key]), label_b, str(b[key])))
        elif key not in b:
            diffs.append(Diff(key, label_a, str(a[key]), label_b, "（未提供）"))
    for key in b:
        if key not in a:
            diffs.append(Diff(key, label_a, "（未提供）", label_b, str(b[key])))
    return diffs


def render_diffs(diffs: list[Diff]) -> str:
    if not diffs:
        return "两份材料共有字段未发现差异（仅比对已录入字段，仍需人工核对原件）。"
    lines = ["发现以下差异（请核对原始凭证）："]
    for i, d in enumerate(diffs, 1):
        lines.append(
            f"  {i}. {d.field}：{d.label_a}记 {d.value_a}，{d.label_b}记 {d.value_b}。"
            "需核对：合同 / 流水 / 台账原件。"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# C5 证据效力诊断 + C7 降级说明
# ---------------------------------------------------------------------------

_EVIDENCE_EXTRA = {
    "整改书/决定书": "重点留存答复期限，建议按期限书面回复并留送达回执。",
    "EMS面单/送达回执": "留存面单原件与签收记录，内件品名要与文书名称一致。",
    "聊天记录截图": "需提供前后文，避免被指截断；重要对话建议同时录屏。",
}


def evidence_tip(doc_type: str) -> str:
    base = ("证据效力：请保留原图、连续拍摄、带时间水印版本；"
            "截图需完整可辨身份，视频保留原始文件。")
    extra = _EVIDENCE_EXTRA.get(doc_type, "")
    return base + (" " + extra if extra else "")


def degrade_notice() -> str:
    """C7：明确当前不读图，不虚构识别结果。"""
    return ("【当前为降级模式】本版本不读取图片内容、不做 OCR 识别。"
            "请按字段清单把票据 / 流水上的信息手动录入，我来帮你整理成表并比对。")


def available_types() -> list[str]:
    """供界面做下拉选择。"""
    return list(DOC_SPECS.keys())


if __name__ == "__main__":
    assert len(available_types()) == 6
    p = parse_manual_entry("户名：张三\n金额：35000元\n账号尾号：6222")
    t = render_material_table("银行流水/对账单", p)
    assert "待核实" in t and "中" in t
    assert "138****5678" in render_material_table(
        "EMS面单/送达回执", parse_manual_entry("收件人：13812345678"))
    d = cross_check("合同", {"金额": "35000"}, "流水", {"金额": "38000"})
    assert "38000" in render_diffs(d) and "未发现差异" in render_diffs([])
    assert "不读取图片" in degrade_notice()
    assert "时间水印" in evidence_tip("银行流水/对账单")
    print("OCRKIT_OK")
