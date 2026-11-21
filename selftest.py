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

    # ---------- 5. UI 构建 + 占位（新版：首页/对话页/气泡） ----------
    from kivy.clock import Clock
    root = a.build()
    Clock.tick()  # 让首页卡片的 schedule_once 落地
    check("首页与对话页就绪", root.screen_names == ["home", "chat"] and root.current == "home",
          str(root.screen_names))
    home = a.home_screen
    chat = a.chat_screen
    check("模块卡片数量", len(home.ids.module_grid.children) == 7,
          str(len(home.ids.module_grid.children)))

    # 首页点卡片 -> 带引导问题进对话
    home._build_cards()
    home._enter("测试引导问题", "财务核查")
    check("首页卡片带问题进对话", root.current == "chat"
          and chat.ids.entry.text == "测试引导问题" and chat.module_title == "财务核查",
          f"{root.current} / {chat.ids.entry.text}")

    before = len(chat._history)
    chat.on_voice()
    check("语音入口占位", len(chat._history) == before + 1 and "后续功能" in chat._history[-1][1])
    chat.on_monitor()
    check("旁听入口占位", "后续功能" in chat._history[-1][1])

    # ---------- 6. 五块模板与要点补漏 ----------
    from core.templates import BriefSections, render_brief
    from core.playbook import pick

    brief = render_brief(BriefSections(
        route_label="[路由: A→B]", headline="测试结论",
        judgments=["判断一"], actions=["步骤一"],
        evidence="证据", question="一个问题？", include_disclaimer=True,
    ))
    brief_needed = ["[路由: A→B]", "一句话结论", "关键判断", "现在就做",
                    "要留的证据", "一个问题", DISCLAIMER]
    check("五块模板齐全", all(n in brief for n in brief_needed))

    real_question = "业委会多年没有公布公共开支和收益怎么办"
    codes, books = pick(real_question, route(real_question).codes)
    check("要点补漏财务优先", codes[0] == "A", str(codes))
    check("要点内容非空", bool(books[0].headline and books[0].actions))

    new_answer = a.answer(real_question)
    check("新回答用五块结构", "一句话结论" in new_answer and "现在就做" in new_answer)
    check("新回答无旧套话", "主系统已完成问题分类" not in new_answer)
    check("追问是人话", "这是哪一类第几项资料" not in new_answer and "一个问题" in new_answer)

    from kivy.core.window import Window
    check("软键盘顶起输入框", Window.softinput_mode == "below_target",
          str(Window.softinput_mode))

    # 气泡：用户/助手分色，靠左右两侧
    chat._history = [("user", "我的问题"), ("assistant", "助手回答")]
    chat._render_transcript()
    from kivy.factory import Factory  # noqa: F401  触发 Factory 注册表
    from app import ChatBubble
    bubbles = [c for row in chat.ids.bubbles.children for c in row.children
               if isinstance(c, ChatBubble)]
    check("气泡数量与分色", len(bubbles) == 2
          and {b.role for b in bubbles} == {"user", "assistant"},
          str([b.role for b in bubbles]))
    check("对话区可滚动", chat.ids.transcript_view is not None)

    # 设置分区：账号区提示未启用 + 法规库面板 + 更新时间显示
    sv = app_mod.SettingsView(app_ref=a)
    sv.build_sections()
    from legal.ui.update_panel import UpdatePanel as UP
    check("设置分区含更新面板", any(isinstance(w, UP) for w in sv.ids.panel_host.children))
    a.update_manager.db.set_meta("last_update_at", "2026-11-20T05:39:26+00:00")
    panel = next(w for w in sv.ids.panel_host.children if isinstance(w, UP))
    panel._refresh_version()
    check("版本显示含完整日期", "2026-11-20 05:39" in panel.version_label,
          panel.version_label)

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
