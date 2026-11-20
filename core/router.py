# -*- coding: utf-8 -*-
"""
router.py —— 智能路由引擎（系统提示词第五节）

作用：把用户的一句话按触发词给六大模块 A-F 打分，选 1~3 个主模块，
     生成形如 [路由: A→E→D] 的标签。全部本地规则，不依赖大模型。

做法（保持简单）：
  * 每个模块配一组触发词，命中一个词加一分。
  * 证据模块 E 几乎总是伴随（维权必留痕），作为兜底加分。
  * 所有模块得分都为 0 -> 综合类 [路由: 综合]。
  * 排序：按得分降序；同分按固定优先级，保证输出稳定可预期。

这是"主系统骨架"版本：只做路由判定，不做实体抽取与复杂编排，
后续功能（如本地大模型意图识别）可在不改变接口的前提下替换本模块。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouteResult:
    """一次路由的结果。"""
    codes: list[str]          # 模块代号，如 ['A', 'E', 'D']；综合类为 ['综合']
    scores: dict[str, int]    # 各模块得分，便于调试与 UI 展示
    label: str                # 路由标签一行文本，如 '[路由: A→E→D]'

    def to_dict(self) -> dict:
        return {"codes": self.codes, "scores": self.scores, "label": self.label}


# 六大模块触发词（摘自系统提示词第三节）
MODULE_KEYWORDS: dict[str, list[str]] = {
    "A": ["公共收益", "维修资金", "物业费", "重复收费", "账目", "银行流水",
          "对账", "收益去向", "分摊", "押金", "收费", "票据", "发票"],
    "B": ["合同续签", "服务标准", "物业服务等级", "招投标", "解聘", "业委会",
          "履约", "涨价", "物业服务合同", "业主大会", "表决"],
    "C": ["违建", "岗亭", "改建", "用途变更", "规划许可", "拆除", "迁移",
          "商铺", "侵占绿地", "消防", "加建"],
    "D": ["住建", "城管", "街道", "纪委", "投诉", "举报", "复议", "诉讼",
          "政府信息公开", "找谁", "哪个部门", "信访", "答复期限"],
    "E": ["证据", "聊天记录", "录音", "录像", "拒签", "见证", "水印", "公证",
          "时间戳", "保全", "邮件", "送达", "留痕", "拍照"],
    "F": ["对方说", "集体请辞", "道德绑架", "威胁", "谈判", "沟通", "话术",
          "拖着不办", "催办", "质询", "怎么处理", "怎么谈"],
}

# 模块名称（供输出模板与 UI 显示）
MODULE_NAMES: dict[str, str] = {
    "A": "财务核查", "B": "物业合规", "C": "规划违建",
    "D": "行政程序", "E": "证据固定", "F": "沟通博弈",
    "综合": "综合类",
}

# 同分时的稳定排序优先级：证据前置、行政对外、沟通收尾
_PRIORITY = {"E": 0, "A": 1, "B": 2, "C": 3, "D": 4, "F": 5}


def score_modules(text: str) -> dict[str, int]:
    """对每个模块按触发词命中次数打分。"""
    scores: dict[str, int] = {}
    for code, words in MODULE_KEYWORDS.items():
        scores[code] = sum(1 for w in words if w in text)
    return scores


def route(text: str, max_modules: int = 3) -> RouteResult:
    """
    主路由入口：输入用户文本，返回路由结果。
    max_modules 控制最多选几个主模块（系统提示词选 1~3 个）。
    """
    scores = score_modules(text)

    # 证据模块 E 是维权通用伴随项：只要用户提到具体维权事项，就轻推一把，
    # 但不要因为单独一句"要留证据"就淹没其他主模块。
    if any(v > 0 for k, v in scores.items() if k != "E"):
        scores["E"] += 1

    # 选出得分 > 0 的模块
    positive = [(code, sc) for code, sc in scores.items() if sc > 0]
    if not positive:
        return RouteResult(codes=["综合"], scores=scores, label="[路由: 综合]")

    # 按 得分降序 -> 优先级升序 排序，保证同分稳定
    positive.sort(key=lambda item: (-item[1], _PRIORITY.get(item[0], 99)))
    codes = [code for code, _ in positive[:max_modules]]

    return RouteResult(codes=codes, scores=scores,
                       label="[路由: " + "→".join(codes) + "]")


if __name__ == "__main__":
    tests = [
        "物业提供的银行流水，公共收益去向不对，想对账",
        "城管第三份整改书要求拆除，业委会改成迁移",
        "物业拒签，现场没人见证，怎么送达",
        "今天天气不错",
    ]
    for t in tests:
        r = route(t)
        names = "、".join(MODULE_NAMES[c] for c in r.codes)
        print(f"{r.label}  {names}  <- {t}")
        print(f"    得分: {r.scores}")
