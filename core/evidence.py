# -*- coding: utf-8 -*-
"""
evidence.py —— 语音/OCR/文档的行为规则层（纯逻辑，不依赖大模型与原生库）

对应《语音OCR文档处理-功能增强块》中的规则：
  * B2 关键实体复述确认：金额/日期/文号等，先复述再计算（红线 G6）
  * C2 结构化字段 + 置信度：低置信度标"待核实"，不猜不补
  * C8/G 敏感信息脱敏：手机号/身份证/银行卡号
  * D2 成文前置检查：缺字段先问，一次只问一个
  * G 红线：不虚构、不猜数字

本模块只做文本处理，不识别图片、不生成文件（那是 docgen / 后续 OCR 模块的事）。
规则引擎可直接调用，无需大模型。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 中文数字片段：语音转写常把金额识别成"三万五千元"
_CN_NUM = r"[零一二三四五六七八九十百千万两]+"

# B2 关键实体正则。顺序：日期 / 文号 / 金额（避免"2026"被当成金额）
_ENTITY_PATTERNS = {
    "日期": re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{1,2}-\d{1,2}"),
    "文号": re.compile(r"[\[〔（(]?\d{4}[\]〕）)]?\s*第?\s*\d+\s*号"),
    "金额": re.compile(r"(?:\d+(?:\.\d+)?|" + _CN_NUM + r")\s*(?:万元|元)"),
}

# B2 需要用口语读出的数字（这里保留原文，读法转换属展示层）
_CONFIDENCE = ("高", "中", "低")


# ---------------------------------------------------------------------------
# B2 关键实体复述确认
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    kind: str    # 日期 / 文号 / 金额
    value: str


def detect_entities(text: str) -> list[Entity]:
    """检测文本里的关键实体（日期/文号/金额）。去重、保持出现顺序。"""
    found: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    # 按在文本中的位置排序，保证"先听到什么先确认什么"
    raw: list[tuple[int, Entity]] = []
    for kind, pattern in _ENTITY_PATTERNS.items():
        for m in pattern.finditer(text):
            value = m.group().strip()
            if (kind, value) not in seen:
                seen.add((kind, value))
                raw.append((m.start(), Entity(kind, value)))
    raw.sort(key=lambda x: x[0])
    return [e for _, e in raw]


def recap_question(entities: list[Entity]) -> str:
    """
    B2：给出复述确认问句，一次确认一个实体（红线 G6：未确认不进结论）。
    没有关键实体时返回空串（无需复述）。
    """
    if not entities:
        return ""
    first = entities[0]
    return f"我听{first.kind}是{first.value}，对不对？"


# ---------------------------------------------------------------------------
# C8 / G 敏感信息脱敏
# ---------------------------------------------------------------------------

def mask_sensitive(text: str) -> str:
    """
    脱敏手机号、身份证号、银行卡号（C8/G5）。
    顺序：身份证(18位) -> 银行卡(16-19位) -> 手机号(11位)，避免长号被短规则先切。
    """
    if not text:
        return text
    # 身份证：前6后4，中间8位
    text = re.sub(
        r"(?<!\d)\d{17}[\dXx](?!\d)",
        lambda m: m.group()[:6] + "********" + m.group()[-4:],
        text,
    )
    # 银行卡：前4后4
    text = re.sub(
        r"(?<!\d)\d{16,19}(?!\d)",
        lambda m: m.group()[:4] + "****" + m.group()[-4:],
        text,
    )
    # 手机号：前3后4
    text = re.sub(
        r"(?<!\d)1[3-9]\d{9}(?!\d)",
        lambda m: m.group()[:3] + "****" + m.group()[-4:],
        text,
    )
    return text


# ---------------------------------------------------------------------------
# C2 结构化字段 + 置信度
# ---------------------------------------------------------------------------

@dataclass
class Field:
    name: str         # 字段名
    value: str        # 识别值；空串表示未识别
    confidence: str   # 高 / 中 / 低
    note: str = ""    # 备注

    def display_value(self) -> str:
        """低置信度或空白字段标"待核实"（C2：不猜、不补）。"""
        if not self.value.strip():
            return "待核实"
        if self.confidence == "低":
            return f"{self.value}（待核实）"
        return self.value

    def validate(self) -> None:
        if self.confidence not in _CONFIDENCE:
            raise ValueError(f"置信度必须是 高/中/低，收到 {self.confidence!r}")


def render_fields_table(fields: list[Field]) -> str:
    """把字段渲染成 C2 要求的表格：字段名 / 识别值 / 置信度 / 备注。"""
    lines = ["| 字段名 | 识别值 | 置信度 | 备注 |",
             "|---|---|---|---|"]
    for f in fields:
        f.validate()
        lines.append(f"| {f.name} | {f.display_value()} | {f.confidence} | {f.note} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# D2 成文前置检查（缺项先问，一次只问一个）
# ---------------------------------------------------------------------------

REQUIRED_DOC_FIELDS = ("收件方全称", "事由", "落款人")


def missing_doc_fields(provided: dict[str, str]) -> list[str]:
    """返回缺失的必填字段名；字段齐了才成文（D2）。"""
    return [k for k in REQUIRED_DOC_FIELDS if not str(provided.get(k, "")).strip()]


def next_missing_question(provided: dict[str, str]) -> str:
    """只问一个缺失项（B4/D2：一次一个问题，问完停住）。"""
    missing = missing_doc_fields(provided)
    if not missing:
        return ""
    return f"请告诉我{missing[0]}，我再把文书补全。"


if __name__ == "__main__":
    e = detect_entities("业委会2026年3月5日说要收三万五千元，文号〔2026〕第12号")
    assert {x.kind for x in e} == {"日期", "金额", "文号"}
    assert "对不对" in recap_question(e)
    assert mask_sensitive("13812345678") == "138****5678"
    table = render_fields_table([
        Field("金额", "35000元", "低", "图片模糊"),
        Field("日期", "", "低", "未识别"),
    ])
    assert "待核实" in table
    assert next_missing_question({"收件方全称": "XX物业"}) .startswith("请告诉我")
    print("EVIDENCE_OK")
