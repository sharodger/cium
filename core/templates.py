# -*- coding: utf-8 -*-
"""
templates.py —— 输出格式模板（系统提示词第七节）

八段式结构，顺序固定：
  ① 路由标签  ② 意图确认  ③ 分析结论  ④ 依据  ⑤ 行动清单
  ⑥ 证据与文书  ⑦ 风险与提醒  ⑧ 下一步问题

这里只做"结构组装"：把内核填好的各部分内容套进模板，保证格式统一。
不做法律推理（那是内核/后续大模型的事），也不编造内容。

首次对话与输出法律性结论时附免责声明，按系统提示词第一条/第九条。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DISCLAIMER = "（仅供参考，重大事项请咨询执业律师或拨打 12348法律援助）"


@dataclass
class AnswerSections:
    """八段式内容的容器。空字符串表示该段留空、不输出。"""
    route_label: str = ""                 # ① 如 [路由: A→E→D]
    intent: str = ""                      # ② 一句话复述理解
    conclusion: str = ""                  # ③ 结论先行，分点
    basis: str = ""                       # ④ 法律/规则/事实依据
    actions: list[str] = field(default_factory=list)  # ⑤ 编号步骤
    evidence_docs: str = ""               # ⑥ 补强证据 + 文书/话术
    risks: str = ""                       # ⑦ 风险点
    next_question: str = ""               # ⑧ 仅一个问题（语音场景）
    include_disclaimer: bool = False      # 是否附免责声明


def render(sections: AnswerSections) -> str:
    """把各段内容组装成规范输出文本。"""
    lines: list[str] = []

    if sections.route_label:
        lines.append(sections.route_label)

    if sections.intent:
        lines.append("① 意图确认：" + sections.intent)

    if sections.conclusion:
        lines.append("② 分析结论：" + sections.conclusion)

    if sections.basis:
        lines.append("③ 依据：" + sections.basis)

    if sections.actions:
        lines.append("④ 行动清单：")
        for i, action in enumerate(sections.actions, 1):
            lines.append(f"   {i}. {action}")

    if sections.evidence_docs:
        lines.append("⑤ 证据与文书：" + sections.evidence_docs)

    risk_text = sections.risks
    if sections.include_disclaimer:
        risk_text = (risk_text + "  " if risk_text else "") + DISCLAIMER
    if risk_text:
        lines.append("⑥ 风险与提醒：" + risk_text)

    if sections.next_question:
        lines.append("⑦ 下一步问题：" + sections.next_question)

    return "\n".join(lines)


@dataclass
class BriefSections:
    """五块结构的容器（手机端精简输出）。空值表示该块不输出。"""
    route_label: str = ""                              # 路由标签
    headline: str = ""                                 # 一句话结论
    judgments: list[str] = field(default_factory=list) # 关键判断
    actions: list[str] = field(default_factory=list)   # 现在就做
    evidence: str = ""                                 # 要留的证据
    question: str = ""                                 # 一个问题
    include_disclaimer: bool = False                   # 免责声明


def render_brief(sections: BriefSections) -> str:
    """把五块内容组装成适合手机阅读的文本（旧的 render 保持不动）。"""
    lines: list[str] = []
    if sections.route_label:
        lines.append(sections.route_label)
    if sections.headline:
        lines.append("一句话结论：" + sections.headline)
    if sections.judgments:
        lines.append("关键判断：")
        for i, item in enumerate(sections.judgments, 1):
            lines.append(f"  {i}. {item}")
    if sections.actions:
        lines.append("现在就做：")
        for i, item in enumerate(sections.actions, 1):
            lines.append(f"  {i}. {item}")
    if sections.evidence:
        lines.append("要留的证据：" + sections.evidence)
    if sections.question:
        lines.append("一个问题：" + sections.question)
    if sections.include_disclaimer:
        lines.append(DISCLAIMER)
    return "\n".join(lines)


if __name__ == "__main__":
    demo = AnswerSections(
        route_label="[路由: A→E]",
        intent="您拍了物业提供的银行流水，想核对公共收益去向。",
        conclusion="仅凭照片不足以认定事实，需结合合同与台账比对。",
        basis="公共收益归业主共有，应单独列账（具体条款请核实现行法规）。",
        actions=[
            "补全流水期间与账户主体。",
            "与物业合同收费项目逐项比对。",
            "标记异常收款方并留存原图。",
        ],
        evidence_docs="照片需补拍带时间水印版本，保留原图与连续拍摄。",
        risks="勿公开传播未经核实的收款方信息。",
        next_question="这是 A 类第几项资料？",
        include_disclaimer=True,
    )
    print(render(demo))
