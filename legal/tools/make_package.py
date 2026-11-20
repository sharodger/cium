# -*- coding: utf-8 -*-
"""
make_package.py —— 法规库更新包生成工具（维护端使用，非 App 运行时）

用法：
    # 从 laws.json 生成全量包
    python tools/make_package.py --src laws.json --out dist/laws_2026.11.0.zip \
        --version 2026.11.0 --mode full --changelog "2026年11月法规更新"

    # 用内置样例条文生成一个演示包
    python tools/make_package.py --sample --out dist/laws_2026.11.0.zip --version 2026.11.0

laws.json 格式：JSON 数组，每项为条文对象，字段见 database.Law。
生成后可用 --serve 在本机起一个简易 HTTP 服务，供 App 的「检查更新」测试下载。
"""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
from pathlib import Path

# 让脚本能 import 上级目录的模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import Law                      # noqa: E402
from package import build_package, sha256_file  # noqa: E402


SAMPLE_LAWS = [
    Law("mfd-238", "中华人民共和国民法典", "物权编", "第二百三十八条", "C",
        "侵害物权，造成权利人损害的，权利人可以依法请求损害赔偿，也可以依法请求承担其他民事责任。",
        "物权 损害赔偿 侵权", "全国人民代表大会", "2021-01-01"),
    Law("mfd-271", "中华人民共和国民法典", "物权编", "第二百七十一条", "A",
        "业主对建筑物内的住宅、经营性用房等专有部分享有所有权，对专有部分以外的共有部分享有共有和共同管理的权利。",
        "业主 共有部分 公共收益", "全国人民代表大会", "2021-01-01"),
    Law("mfd-278", "中华人民共和国民法典", "物权编", "第二百七十八条", "B",
        "下列事项由业主共同决定：制定和修改业主大会议事规则；选举业主委员会或者更换业主委员会成员；选聘和解聘物业服务企业或者其他管理人；使用建筑物及其附属设施的维修资金；改建、重建建筑物及其附属设施。",
        "业主共同决定 双过半 业主大会", "全国人民代表大会", "2021-01-01"),
    Law("wygl-11", "物业管理条例", "", "第十一条", "B",
        "下列事项由业主共同决定：制定和修改业主大会议事规则；制定和修改管理规约；选举业主委员会或者更换业主委员会成员；选聘和解聘物业服务企业。",
        "业主共同决定 业委会 物业", "国务院", "2018-03-19"),
    Law("wygl-40", "物业管理条例", "", "第四十条", "A",
        "物业服务收费应当遵循合理、公开以及费用与服务水平相适应的原则，区别不同物业的性质和特点，由业主和物业服务企业按照国务院价格主管部门会同国务院建设行政主管部门制定的物业服务收费办法，在物业服务合同中约定。",
        "物业费 收费 服务等级", "国务院", "2018-03-19"),
    Law("sffw-8", "物业服务收费管理办法", "", "第八条", "A",
        "物业管理企业应当按照政府价格主管部门的规定实行明码标价，在物业管理区域内的显著位置，将服务内容、服务标准以及收费项目、收费标准等有关情况进行公示。",
        "物业费 明码标价 公示", "国家发改委、建设部", "2004-01-01"),
]


def load_laws_from_json(src: Path) -> list[Law]:
    data = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "laws" in data:
        data = data["laws"]
    return [Law.from_dict(d) for d in data]


def serve_directory(directory: Path, port: int) -> None:
    """简易静态文件服务，供 App 更新检查下载测试。"""
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(directory), **kw
    )
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"服务已启动: http://127.0.0.1:{port}/  按 Ctrl+C 停止")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务已停止")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成法规库更新包")
    ap.add_argument("--src", type=Path, help="条文 JSON 文件")
    ap.add_argument("--sample", action="store_true", help="使用内置样例条文")
    ap.add_argument("--out", type=Path, required=True, help="输出 zip 路径")
    ap.add_argument("--version", required=True, help="版本号，如 2026.11.0")
    ap.add_argument("--mode", choices=["full", "incremental"], default="full")
    ap.add_argument("--changelog", default="", help="变更说明")
    ap.add_argument("--max-age-days", type=int, default=30, help="包有效天数")
    ap.add_argument("--min-app-version", default="1.0.0", help="最低 App 版本")
    ap.add_argument("--serve", action="store_true", help="生成后启动本地 HTTP 服务")
    ap.add_argument("--port", type=int, default=8765, help="本地服务端口")
    args = ap.parse_args()

    if args.sample:
        laws = SAMPLE_LAWS
    elif args.src:
        laws = load_laws_from_json(args.src)
    else:
        ap.error("需指定 --src 或 --sample")

    pkg = build_package(
        args.out, laws, args.version, mode=args.mode,
        max_age_days=args.max_age_days, changelog=args.changelog,
        min_app_version=args.min_app_version,
    )
    print(f"已生成更新包: {pkg}")
    print(f"条文数: {len(laws)} | 版本: {args.version} | 模式: {args.mode}")
    print(f"包 SHA-256: {sha256_file(pkg)}")

    # 同时写出一个 version.json 供「检查更新」轻量探测（无需下载整包）
    version_info = {
        "version": args.version,
        "package": pkg.name,
        "sha256": sha256_file(pkg),
        "law_count": len(laws),
        "released_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "min_app_version": args.min_app_version,
    }
    version_json = pkg.parent / "version.json"
    version_json.write_text(
        json.dumps(version_info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已生成版本清单: {version_json}")

    if args.serve:
        serve_directory(pkg.parent, args.port)


if __name__ == "__main__":
    main()
