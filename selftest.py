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

    # ---------- 5. 账号页 + UI 构建 + 占位 ----------
    import time as _time
    from kivy.clock import Clock
    from unittest.mock import patch
    # 账号数据隔离到临时目录，避免污染真实目录导致"账号已存在"（测试隔离）
    tmp_data = Path(tempfile.mkdtemp(prefix="auth_"))
    root = None
    with patch.object(type(a), "user_data_dir",
                      new_callable=lambda: property(lambda self: str(tmp_data))):
        root = a.build()
    # 等 >0.1s 再 tick，让 build 里延迟的首屏判定先落地，
    # 避免它在注册后才触发、把界面切回登录页（真机不会发生，此处仅消除测试时序竞争）
    _time.sleep(0.15)
    Clock.tick()
    check("三个页面就绪", root.screen_names == ["auth", "home", "chat"],
          str(root.screen_names))
    check("未注册先到账号页", root.current == "auth", str(root.current))

    # 模拟首次注册：走 AuthScreen.submit
    auth_screen = a.auth_screen
    auth_screen.prepare(register_mode=True)
    auth_screen.ids.user.text = "测试业主"
    auth_screen.ids.pwd.text = "mypassword"
    auth_screen.submit()
    check("注册后进入首页", root.current == "home" and a.auth.is_registered(),
          f"{root.current} / 已注册={a.auth.is_registered()}")
    check("密码不落明文", "mypassword" not in a.auth.path.read_text(encoding="utf-8"))

    # 模拟重新登录：错密码拦截，对密码放行
    a.root_widget.current = "auth"
    auth_screen.prepare(register_mode=False, username="测试业主")
    auth_screen.ids.pwd.text = "wrong"
    auth_screen.submit()
    check("错误密码被拦截", root.current == "auth" and "错误" in auth_screen.message,
          auth_screen.message)
    auth_screen.ids.pwd.text = "mypassword"
    auth_screen.submit()
    check("正确密码进首页", root.current == "home", str(root.current))

    # 让首页卡片构建落地
    Clock.tick()
    home = a.home_screen
    chat = a.chat_screen
    check("模块卡片数量", len(home.ids.module_grid.children) == 7,
          str(len(home.ids.module_grid.children)))

    # 首页点卡片 -> 空白输入框进对话（不再预填示例）
    home._build_cards()
    home._enter("财务核查")
    check("首页卡片进空白对话", root.current == "chat"
          and chat.ids.entry.text == "" and chat.module_title == "财务核查"
          and not chat._history,
          f"{root.current} / 输入框='{chat.ids.entry.text}' / 气泡={len(chat._history)}")

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

    # ---------- 7. 豆包风界面 + 复制粘贴 + 上传降级 ----------
    from kivy.core.clipboard import Clipboard as CB
    from app import ChatBubble

    # 首页卡片：纯白纹理（关键：background_normal='' 否则发灰）
    card = home.ids.module_grid.children[0]
    check("卡片纯白无灰纹理", card.background_normal == ""
          and tuple(round(x, 2) for x in card.background_color[:3]) == (1.0, 1.0, 1.0),
          f"normal={card.background_normal!r} color={card.background_color[:3]}")

    # 首页背景为浅色（canvas.before 会混有 PushMatrix，按类型过滤找 Color）
    from kivy.graphics import Color as KGColor
    home_bg = next(c.rgba for c in home.canvas.before.children if isinstance(c, KGColor))
    check("首页浅色背景", tuple(round(x, 2) for x in home_bg[:3]) == (0.96, 0.97, 0.99),
          str(home_bg[:3]))

    # 状态行是人话，不含设备号/下载后端等技术信息
    a.refresh_status()
    status = home.status_line
    check("状态行人话化", "法规库" in status and "DEV-" not in status
          and "requests" not in status and "可" in status, status)

    # 技术细节进设置-关于
    tech = a.technical_status()
    check("技术细节移到设置", "DEV-" in tech and "v" in tech, tech.replace("\n", " | "))

    # 首页气泡分色 + 白底助手气泡
    chat._history = [("user", "问题"), ("assistant", "回答")]
    chat._render_transcript()
    bs = [c for row in chat.ids.bubbles.children for c in row.children
          if isinstance(c, ChatBubble)]
    asst = [b for b in bs if b.role == "assistant"][0]
    asst_bg = next(c.rgba for c in asst.canvas.before.children if isinstance(c, KGColor))
    check("助手气泡白底", tuple(round(x, 2) for x in asst_bg) == (1.0, 1.0, 1.0, 1.0),
          str(asst_bg))

    # 长按复制：计时触发后剪贴板=整条文本
    CB.copy("清空")
    asst._copy()
    check("长按复制整条回答", CB.paste() == "回答", CB.paste())

    # 粘贴按钮：剪贴板内容进输入框
    CB.copy("粘贴的文字")
    chat.ids.entry.text = ""
    chat.on_paste()
    check("粘贴进输入框", chat.ids.entry.text == "粘贴的文字", chat.ids.entry.text)

    # 上传降级：本机无 plyer 应给降级提示，不崩溃、不假装成功
    before = len(chat._history)
    chat.on_upload()
    check("上传降级不虚构", len(chat._history) == before + 1
          and "不支持" in chat._history[-1][1], chat._history[-1][1][:30])

    # 上传模块文件名提取
    from core.attach import _basename
    check("上传文件名提取", _basename("/sdcard/证据.jpg?x=1") == "证据.jpg")

    # ---------- 8. 行为规则层 + 文书生成（三能力第一步） ----------
    from core.evidence import (
        detect_entities, recap_question, mask_sensitive,
        Field, render_fields_table, next_missing_question,
    )
    # B2 关键实体 + 复述确认（含中文数字金额）
    ents = detect_entities("业委会2026年3月5日要收三万五千元，文号〔2026〕第12号")
    kinds = {e.kind for e in ents}
    check("B2关键实体检测", {"日期", "金额", "文号"} <= kinds, str(kinds))
    check("B2复述确认句", "对不对" in recap_question(ents), recap_question(ents))

    # C8/G 敏感信息脱敏
    masked = mask_sensitive("13812345678 110101199001011234 6222021234567890123")
    check("C8敏感信息脱敏", "13812345678" not in masked and "110101199001011234" not in masked
          and "6222" in masked, masked)

    # C2 置信度表：低置信度标待核实
    ftab = render_fields_table([
        Field("金额", "35000元", "低", "图模糊"),
        Field("日期", "", "低", "未识别"),
    ])
    check("C2置信度表待核实", "待核实" in ftab and "置信度" in ftab)

    # D2 缺项先问，一次一个
    q = next_missing_question({"收件方全称": "", "事由": "有", "落款人": "有"})
    check("D2缺项先问", q.startswith("请告诉我") and "收件方" in q, q)

    # D3/D5/D6 docx 生成 + 命名（用临时目录隔离，csv 不入项目）
    from core.docgen import DocRequest, generate as gen_doc, describe_result
    doc_dir = Path(tempfile.mkdtemp(prefix="docgen_"))
    req = DocRequest(
        doc_type="财务质询函", party="XX物业",
        sections=[("事实", "多年未公示公共收益"), ("依据", "条款待核实"),
                  ("请求", "公开台账"), ("时限", "七日内答复")],
        output_dir=doc_dir,
    )
    dres = gen_doc(req)
    check("D5文书命名", dres.filename.startswith("20") and "财务质询函" in dres.filename
          and dres.filename.endswith(".docx"), dres.filename)
    # 本机有 python-docx -> 应真生成；无论生成与否，describe 不谎称
    if dres.generated:
        from docx import Document as _Doc
        dtxt = "\n".join(p.text for p in _Doc(str(dres.path)).paragraphs)
        check("D3docx正文可读回", "财务质询函" in dtxt and "七日内答复" in dtxt)
        check("D6告知路径", dres.path is not None and str(dres.path) in describe_result(dres))
        # 同名不覆盖
        dres2 = gen_doc(req)
        check("D5同名不覆盖", dres2.filename != dres.filename, f"{dres.filename} / {dres2.filename}")
    else:
        check("D7降级说明", "未生成" in describe_result(dres))

    # 降级路径：屏蔽 docx 导入应返回 generated=False 而非崩溃
    import builtins
    real_import = builtins.__import__
    def _block(name, *a, **k):
        if name == "docx" or name.startswith("docx."):
            raise ImportError("模拟移动端无 python-docx")
        return real_import(name, *a, **k)
    builtins.__import__ = _block
    try:
        dres3 = gen_doc(DocRequest(doc_type="异议核查申请", party="XX城管局",
                                   sections=[("请求", "核查")], output_dir=doc_dir))
        check("D7无docx降级", not dres3.generated and dres3.path is None
              and "未生成" in describe_result(dres3))
    finally:
        builtins.__import__ = real_import

    # 界面接线：底栏有文书按钮、设置含能力状态分区
    from kivy.uix.label import Label as KLabel
    sv2 = app_mod.SettingsView(app_ref=a)
    sv2.build_sections()
    section_texts = " ".join(
        w.text for w in sv2.ids.panel_host.children if isinstance(w, KLabel))
    check("能力状态分区", "降级模式" in section_texts and "全程本地" in section_texts)

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
