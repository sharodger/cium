# -*- coding: utf-8 -*-
"""
ocr_android.py —— Android 端 Tesseract 真识别桥接（pyjnius 调 Tesseract4Android）

为什么单独一个模块：
  * PC 端用 core/ocr_engine.py 直接跑 tesseract 命令行；Android 没有可执行文件，
    只能调 JitPack 上的 Tesseract4Android（AAR 里的 TessBaseAPI Java 类）。
  * 两条路径共用同一套结果类型与字段提取（从 ocr_engine 复用），界面只做一次分流。

硬约束（务必如实）：
  * 本模块在 PC 上被导入也必须安全（jnius / Android 类只在函数内部导入），
    这样 selftest 与 PC 界面不会受影响。
  * 任何一步失败（类找不到、语言包缺失、选图取消、识别报错）都返回带原因的
    OcrResult(ok=False)，由界面明确告知降级，绝不抛异常崩掉 App、绝不假装识别成功。
  * 全程本地处理，不上传图片。

依赖（由 android/buildozer.spec + GitHub Actions 提供，缺任一项即降级）：
  * gradle 依赖：cz.adaptech.tesseract4android:tesseract4android:4.9.0（JitPack）
  * requirements 含 pyjnius、plyer（plyer 用于选图）
  * assets/tessdata/chi_sim.traineddata（中文语言包，随 APK 打包）
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

IS_ANDROID = sys.platform == "android" or "android" in sys.platform

# 语言包在 apk assets 中的路径，以及复制到私有目录后的目录名
LANG = "chi_sim"
TESSDATA_ASSET = "tessdata/chi_sim.traineddata"
# Java 类的真实包名沿袭 tess-two：com.googlecode.tesseract.android.TessBaseAPI
# 注意：gradle 坐标 cz.adaptech.tesseract4android 是 Maven artifact，不是 Java package，
#       两者不同——autoclass 必须用下面的 Java 包名，否则真机上类找不到而降级。
TESS_CLASS = "com.googlecode.tesseract.android.TessBaseAPI"

# 结果类型与字段提取直接复用 PC 端，保证两端输出一致（C2/C8 规则不重复写）
try:
    from core.ocr_engine import (OcrResult, DEFAULT_LANG, extract_fields,
                                 to_entry_text, normalize_text)
except ModuleNotFoundError:  # pragma: no cover - 单文件自检时
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.ocr_engine import (OcrResult, DEFAULT_LANG, extract_fields,
                                 to_entry_text, normalize_text)


@dataclass
class AndroidEngineInfo:
    """引擎状态：available=True 才允许走真识别，否则界面走降级。"""
    available: bool = False
    reason: str = ""


def _activity():
    """获取 Kivy 的 Android Activity；非 Android / jnius 缺失返回 None。"""
    if not IS_ANDROID:
        return None
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        return PythonActivity.mActivity
    except Exception:
        return None


def check_engine() -> AndroidEngineInfo:
    """
    检测 Tesseract4Android 类与中文语言包是否就绪。
    只做只读检查，不复制文件；真识别时再按需复制语言包。
    """
    act = _activity()
    if act is None:
        return AndroidEngineInfo(False, "当前不是 Android 环境或 pyjnius 不可用")
    try:
        from jnius import autoclass
        autoclass(TESS_CLASS)
    except Exception:
        return AndroidEngineInfo(False, "APK 未包含 Tesseract4Android 库")
    try:
        data = _asset_bytes()
        if len(data) < 1000:
            raise IOError("语言包为空")
    except Exception:
        return AndroidEngineInfo(False, "APK 未包含中文语言包 chi_sim.traineddata")
    return AndroidEngineInfo(True, "Tesseract4Android 与中文包就绪")


def _asset_bytes() -> bytes:
    """
    读取随 APK 打包的中文语言包。两套机制任一可用即可（与已验证可用的中文字体同机制）：
      1) p4a 会把 assets 解包到文件系统，Python 直接 open（字体就是这么读的，最稳）；
      2) 兜底用 Android AssetManager。
    """
    # 机制1：文件系统路径（HERE/assets/tessdata/...），与 app.py 的字体读取一致
    try:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fs_path = os.path.join(here, "assets", "tessdata", "chi_sim.traineddata")
        if os.path.isfile(fs_path):
            with open(fs_path, "rb") as f:
                return f.read()
    except Exception:
        pass
    # 机制2：Android AssetManager 兜底
    act = _activity()
    if act is None:
        raise IOError("中文语言包不可读（文件系统与 AssetManager 均不可用）")
    inp = act.getAssets().open(TESSDATA_ASSET)
    try:
        chunks = []
        while True:
            buf = inp.read(8192)
            if buf is None or len(buf) == 0:
                break
            chunks.append(bytes(buf))
        return b"".join(chunks)
    finally:
        inp.close()


def _ensure_tessdata(act) -> str:
    """
    把 apk 里的 chi_sim.traineddata 复制到 app 私有目录，
    返回 Tesseract init 需要的 dataPath（其下必须有 tessdata/ 子目录）。
    API>=29 不允许直接读 assets，必须先落到私有目录。
    """
    files_dir = act.getFilesDir().getAbsolutePath()
    tess_dir = os.path.join(files_dir, TESS_ROOT_NAME, "tessdata")
    target = os.path.join(tess_dir, "chi_sim.traineddata")
    # 已复制过且大小合理则直接用，避免每次识别都拷贝几 MB
    if os.path.isfile(target) and os.path.getsize(target) > 1000:
        return os.path.join(files_dir, TESS_ROOT_NAME)
    os.makedirs(tess_dir, exist_ok=True)
    data = _asset_bytes()
    if len(data) < 1000:
        raise IOError("中文语言包内容为空或过小")
    with open(target, "wb") as f:
        f.write(data)
    return os.path.join(files_dir, TESS_ROOT_NAME)


def recognize(image_uri: str, lang: str = LANG) -> OcrResult:
    """
    识别一张本机图片。image 通常是 plyer 选图回调给出的文件路径；
    也兼容 content:// / file:// URI（少数 plyer 版本或选图来源）。
    任何失败都返回 OcrResult(error=人话原因)，不抛异常。
    """
    if not IS_ANDROID:
        return OcrResult(error="Android 识别只能在手机 APK 中使用，当前为电脑端。")
    act = _activity()
    if act is None:
        return OcrResult(error="未取得 Android 运行环境，当前为降级模式。")

    try:
        from jnius import autoclass
        data_path = _ensure_tessdata(act)

        # content:// URI -> Bitmap（兼容 plyer 返回文件绝对路径的情况）
        str_uri = str(image_uri)
        if str_uri.startswith("content://") or str_uri.startswith("file://"):
            Uri = autoclass("android.net.Uri")
            uri = Uri.parse(str_uri)
            stream = act.getContentResolver().openInputStream(uri)
        else:
            FileInputStream = autoclass("java.io.FileInputStream")
            stream = FileInputStream(str_uri)
        BitmapFactory = autoclass("android.graphics.BitmapFactory")
        bitmap = BitmapFactory.decodeStream(stream)
        try:
            stream.close()
        except Exception:
            pass
        if bitmap is None:
            return OcrResult(error="无法读取这张图片，请换一张 JPG/PNG 原图重试。")

        TessBaseAPI = autoclass(TESS_CLASS)
        tess = TessBaseAPI()
        try:
            if not tess.init(data_path, lang):
                return OcrResult(error="Tesseract 初始化失败：中文语言包不可用。")
            tess.setImage(bitmap)       # TessBaseAPI 有 setImage(Bitmap) 重载
            text = tess.getUTF8Text()
        finally:
            tess.recycle()

        text = (text or "").strip()
        if not text:
            return OcrResult(error="图片里没识别出文字，请换清晰、正立的原图重试。")
        return OcrResult(True, text, lang, "Tesseract4Android 4.9.0")
    except Exception as e:
        return OcrResult(error=f"识别失败：{e}（当前为降级模式，可用手动录入）")


def pick_image_uri(on_result) -> bool:
    """
    调起系统图库，选中后回调 on_result(uri字符串)；取消则回 on_result(None)。
    返回 True 表示已成功发起；False 表示选择器不可用（已降级）。
    """
    try:
        from plyer import filechooser

        def _handle(selection):
            if not selection:
                on_result(None)
                return
            first = selection[0] if isinstance(selection, (list, tuple)) else selection
            on_result(str(first))

        filechooser.open_file(on_selection=_handle, filters=["image"])
        return True
    except Exception:
        return False


def engine_status_text() -> str:
    """识图弹窗顶部状态行：Android 上按真引擎状态显示，其它平台说明用途。"""
    if not IS_ANDROID:
        return "电脑端请使用「选图识别」；本模块仅在 Android APK 内启用 Tesseract。"
    info = check_engine()
    if info.available:
        return ("Tesseract 已就绪（Tesseract4Android + 中文包）。"
                "点「选图识别」自动提取字段，可修改后再整理成表。")
    return (f"【降级模式】{info.reason}。请改用下方手动录入，"
            "本工具不虚构识别结果。")


if __name__ == "__main__":
    assert isinstance(check_engine(), AndroidEngineInfo)
    if not IS_ANDROID:
        assert not recognize("x.png").ok
        assert "电脑" in engine_status_text()
    f = extract_fields("银行流水/对账单", normalize_text("金额：￥1，200元"))
    assert f.get("金额") == "1200", f
    print("OCR_ANDROID_OK", IS_ANDROID)
