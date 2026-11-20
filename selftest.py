# -*- coding: utf-8 -*-
"""
selftest.py —— 主系统自测（不依赖窗口）

覆盖：
  1. 子系统复用（法规库可导入、可写入、可检索）
  2. 路由引擎（示例场景标签、综合类）
  3. 输出模板（八段式齐全、免责声明）
  4. 内核 answer（路由+检索+模板串联），含空库与有库两种
  5. Kivy 主界面构建（mock GL）、语音/旁听占位按钮

运行：python selftest.py
（脚本自动设 KIVY_GL_BACKEND=mock，无显示器环境也能跑）
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

# 无 GPU 环境自动用 mock GL，避免 Kivy 导入时 OpenGL 检查退出
if os.environ.get("KIVY_GL_BACKEND") is None:
    os.environ["KIVY_GL_BACKEND"] = "mock"
os.environ.setdefault("KIVY_NO_ARGS", "1")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "legal"))

from core.router import route, MODULE_NAMES        # noqa: E402
from core.templates import AnswerSections, render, DISCLAIMER  # noqa: E402
from database import LegalDatabase, Law            # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"{'[PASS]' if cond else '[FAIL]'} {name}" + (f" — {detail}" if detail else ""))


def fresh_db() -> LegalDatabase:
    p = Path(tempfile.gettempdir()) / f"main_{uuid.uuid4().hex[:8]}.db"
    return LegalDatabase(p)


def main() -> int:
    print("=" * 58)
    print("业主维权AI助手 · 主系统自测")
    print("=" * 58)

    # ---------- 1. 子系统复用 ----------
    db = fresh_db()
    db.replace_all([
        Law("mfd-271", "中华人民共和国民法典", "物权编", "第二百七十一条", "A",
            "业主对共有部分享有共有和共同管理的权利。", "共有部分 公共收益"),
        Law("wygl-11", "物业管理条例", "", "第十一条", "B",
            "下列事项由业主共同决定。", "业主大会 业委会"),
    ], "2026.11.0", "h", mode="full")
    check("子系统可写入", db.law_version == "2026.11.0" and db.law_count == 2)

    # ---------- 2. 路由引擎 ----------
    r1 = route("物业提供的银行流水，公共收益去向不对，想对账")
    check("财务场景路由", r1.label == "[路由: A→E]", r1.label)
    r2 = route("城管要求拆除，业委会改成迁移")
    check("规划场景路由", r2.codes[0] in ("C", "B"), r2.label)
    r3 = route("今天天气不错")
    check("综合类路由", r3.label == "[路由: 综合]", r3.label)
    check("模块名称齐全", len(MODULE_NAMES) == 7)

    # ---------- 3. 输出模板 ----------
    out = render(AnswerSections(
        route_label="[路由: A→E]", intent="测试意图", conclusion="测试结论",
        basis="测试依据", actions=["步骤一", "步骤二"],
        evidence_docs="证据提示", risks="风险提示",
        next_question="下一步？", include_disclaimer=True,
    ))
    needed = ["① 意图确认", "② 分析结论", "③ 依据", "④ 行动清单",
              "⑤ 证据与文书", "⑥ 风险与提醒", "⑦ 下一步问题", DISCLAIMER]
    check("八段式齐全", all(n in out for n in needed))
    empty_out = render(AnswerSections(route_label="[路由: 综合]"))
    check("空段不输出", "① " not in empty_out and "[路由: 综合]" in empty_out)

    # ---------- 4. 内核 answer ----------
    import app as app_mod
    a = app_mod.OwnerRightsApp()
    a.db = db  # 注入带数据的库
    answer = a.answer("物业的公共收益去向不对，想对账")
    check("内核输出路由标签", answer.startswith("[路由:"), answer.split("\n")[0])
    check("内核带出法规依据", "民法典" in answer or "物业管理条例" in answer,
          "含条文")
    check("内核附免责声明", DISCLAIMER in answer)

    # 空库降级
    a.db = fresh_db()
    empty_answer = a.answer("公共收益怎么用")
    check("空库降级提示", "待核实" in empty_answer)

    # ---------- 5. UI 构建 + 占位 ----------
    root = a.build()
    check("主界面构建", sorted(root.ids) == ["entry", "transcript", "transcript_view"],
          str(sorted(root.ids)))
    before = len(root._history)
    root.on_voice()
    check("语音入口占位", len(root._history) == before + 1 and "后续功能" in root._history[-1][1])
    root.on_monitor()
    check("旁听入口占位", "后续功能" in root._history[-1][1])

    # ---------- 汇总 ----------
    print("\n" + "=" * 58)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"结果: {passed}/{total} 通过")
    for name, ok, detail in results:
        if not ok:
            print(f"  未通过: {name} {detail}")
    print("=" * 58)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
