# -*- coding: utf-8 -*-
"""
database.py —— SQLite 本地法规库数据层

表结构：
  * laws           法规条文（正文、分类、关键词、内容哈希）
  * laws_fts       FTS5 全文检索虚拟表（不可用时自动降级为 LIKE 查询）
  * meta           键值对元数据（当前法规库版本、schema 版本、最后更新时间等）
  * update_history 更新历史（版本、时间、包哈希、条文数、状态）

线程安全：
  Kivy 场景后台线程写入、主线程读取。SQLite 连接默认 check_same_thread=True，
  因此这里每次操作新建连接（WAL 模式支持并发读、单写），并用写锁串行化写事务。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

_WRITE_LOCK = threading.RLock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Law:
    """一条法规条文。"""
    law_id: str            # 全局唯一，如 "minfadian-物权-238"
    law_name: str          # 法规名，如 "中华人民共和国民法典"
    part: str = ""         # 编/章，如 "物权编"
    article: str = ""      # 条号，如 "第二百三十八条"
    category: str = ""     # 业务分类 A-G（对应系统提示词资料分类），可空
    content: str = ""      # 条文正文
    keywords: str = ""     # 检索关键词，空格分隔
    source: str = ""       # 来源/出处
    effective_date: str = ""  # 生效日期 YYYY-MM-DD
    content_hash: str = ""    # 正文哈希，用于增量比对

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Law":
        allowed = set(Law.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        return Law(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class UpdateRecord:
    version: str
    applied_at: str
    package_sha256: str
    law_count: int
    status: str = "success"
    detail: str = ""


class LegalDatabase:
    """法规库门面类，封装所有 SQLite 操作。"""

    SCHEMA_VERSION = "1"

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available: Optional[bool] = None
        self.init_schema()

    # ---------------- 连接与 schema ----------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # 并发读写更稳
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """读上下文：注意 with conn 不会关闭连接，必须显式 close，否则 WAL 文件被长期占用。"""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """写事务上下文：串行化 + 异常自动回滚 + 关闭连接。"""
        with _WRITE_LOCK:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init_schema(self) -> None:
        with self._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS laws (
                    law_id         TEXT PRIMARY KEY,
                    law_name       TEXT NOT NULL,
                    part           TEXT NOT NULL DEFAULT '',
                    article        TEXT NOT NULL DEFAULT '',
                    category       TEXT NOT NULL DEFAULT '',
                    content        TEXT NOT NULL DEFAULT '',
                    keywords       TEXT NOT NULL DEFAULT '',
                    source         TEXT NOT NULL DEFAULT '',
                    effective_date TEXT NOT NULL DEFAULT '',
                    content_hash   TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_laws_name ON laws(law_name);
                CREATE INDEX IF NOT EXISTS idx_laws_category ON laws(category);

                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS update_history (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    version        TEXT NOT NULL,
                    applied_at     TEXT NOT NULL,
                    package_sha256 TEXT NOT NULL DEFAULT '',
                    law_count      INTEGER NOT NULL DEFAULT 0,
                    status         TEXT NOT NULL DEFAULT 'success',
                    detail         TEXT NOT NULL DEFAULT ''
                );
                """
            )
            # 初始化 meta 默认值
            defaults = {
                "schema_version": self.SCHEMA_VERSION,
                "law_version": "0.0.0",
                "last_update_at": "",
                "law_count": "0",
            }
            for k, v in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (k, v)
                )

        # 尝试建立 FTS5 虚拟表（失败则降级，不影响主流程）
        self._ensure_fts()

    def _ensure_fts(self) -> None:
        try:
            with self._write() as conn:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS laws_fts USING fts5(
                        law_id UNINDEXED, law_name, content, keywords,
                        content='laws', content_rowid='rowid'
                    )
                    """
                )
                # 用触发器保持 FTS 与主表同步
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS laws_ai AFTER INSERT ON laws BEGIN
                        INSERT INTO laws_fts(rowid, law_id, law_name, content, keywords)
                        VALUES (new.rowid, new.law_id, new.law_name, new.content, new.keywords);
                    END
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS laws_ad AFTER DELETE ON laws BEGIN
                        INSERT INTO laws_fts(laws_fts, rowid, law_id, law_name, content, keywords)
                        VALUES ('delete', old.rowid, old.law_id, old.law_name, old.content, old.keywords);
                    END
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS laws_au AFTER UPDATE ON laws BEGIN
                        INSERT INTO laws_fts(laws_fts, rowid, law_id, law_name, content, keywords)
                        VALUES ('delete', old.rowid, old.law_id, old.law_name, old.content, old.keywords);
                        INSERT INTO laws_fts(rowid, law_id, law_name, content, keywords)
                        VALUES (new.rowid, new.law_id, new.law_name, new.content, new.keywords);
                    END
                    """
                )
            self._fts_available = True
        except Exception:
            self._fts_available = False

    @property
    def fts_available(self) -> bool:
        if self._fts_available is None:
            self._ensure_fts()
        return bool(self._fts_available)

    # ---------------- meta 操作 ----------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self._read() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    @property
    def law_version(self) -> str:
        return self.get_meta("law_version", "0.0.0")

    @property
    def law_count(self) -> int:
        try:
            return int(self.get_meta("law_count", "0"))
        except ValueError:
            return 0

    # ---------------- 条文 CRUD ----------------
    def _row_to_law(self, row: sqlite3.Row) -> Law:
        return Law(**{k: row[k] for k in Law.__dataclass_fields__.keys()})  # type: ignore[attr-defined]

    def get_law(self, law_id: str) -> Optional[Law]:
        with self._read() as conn:
            row = conn.execute("SELECT * FROM laws WHERE law_id=?", (law_id,)).fetchone()
            return self._row_to_law(row) if row else None

    def list_laws(self, law_name: Optional[str] = None,
                  category: Optional[str] = None, limit: int = 50,
                  offset: int = 0) -> list[Law]:
        sql = "SELECT * FROM laws WHERE 1=1"
        args: list = []
        if law_name:
            sql += " AND (law_name LIKE ? OR part LIKE ?)"
            args += [f"%{law_name}%", f"%{law_name}%"]
        if category:
            sql += " AND category=?"
            args.append(category)
        sql += " ORDER BY law_id LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._read() as conn:
            return [self._row_to_law(r) for r in conn.execute(sql, args).fetchall()]

    def upsert_law(self, law: Law) -> None:
        with self._write() as conn:
            self._upsert_law_conn(conn, law)

    @staticmethod
    def _upsert_law_conn(conn: sqlite3.Connection, law: Law) -> None:
        conn.execute(
            """
            INSERT INTO laws(law_id, law_name, part, article, category, content,
                             keywords, source, effective_date, content_hash)
            VALUES (:law_id,:law_name,:part,:article,:category,:content,
                    :keywords,:source,:effective_date,:content_hash)
            ON CONFLICT(law_id) DO UPDATE SET
                law_name=excluded.law_name, part=excluded.part, article=excluded.article,
                category=excluded.category, content=excluded.content,
                keywords=excluded.keywords, source=excluded.source,
                effective_date=excluded.effective_date, content_hash=excluded.content_hash
            """,
            law.to_dict(),
        )

    def delete_law(self, law_id: str) -> bool:
        with self._write() as conn:
            cur = conn.execute("DELETE FROM laws WHERE law_id=?", (law_id,))
            return cur.rowcount > 0

    def search(self, query: str, limit: int = 20) -> list[Law]:
        """全文检索；FTS5 不可用或查询含特殊字符时降级为 LIKE。"""
        if not query or not query.strip():
            return []
        if self.fts_available:
            try:
                # 用双引号包裹以规避 FTS5 保留字符导致的语法错误
                safe = '"' + query.strip().replace('"', '""') + '"'
                with self._read() as conn:
                    rows = conn.execute(
                        """
                        SELECT l.* FROM laws_fts f
                        JOIN laws l ON l.rowid = f.rowid
                        WHERE laws_fts MATCH ?
                        ORDER BY rank LIMIT ?
                        """,
                        (safe, limit),
                    ).fetchall()
                    return [self._row_to_law(r) for r in rows]
            except Exception:
                pass  # 降级
        # LIKE 降级
        like = f"%{query.strip()}%"
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT * FROM laws
                WHERE content LIKE ? OR law_name LIKE ? OR keywords LIKE ?
                ORDER BY law_id LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
            return [self._row_to_law(r) for r in rows]

    # ---------------- 事务化整库替换（更新核心） ----------------
    def replace_all(self, laws: Iterable[Law], new_version: str,
                    package_sha256: str, mode: str = "full") -> int:
        """
        原子化更新：整库替换（full）或增量合并（incremental）。
        - full：清空 laws 后批量写入；任一异常 -> 整体回滚到旧库。
        - incremental：按 law_id upsert，不删除既有条目。
        成功后更新 meta 版本并写一条 update_history。
        """
        laws = list(laws)
        with self._write() as conn:
            if mode == "full":
                conn.execute("DELETE FROM laws")
            for law in laws:
                self._upsert_law_conn(conn, law)

            total = conn.execute("SELECT COUNT(*) AS c FROM laws").fetchone()["c"]
            now = utcnow()
            conn.execute(
                "INSERT INTO meta(key,value) VALUES ('law_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (new_version,),
            )
            conn.execute(
                "INSERT INTO meta(key,value) VALUES ('law_count',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(total),),
            )
            conn.execute(
                "INSERT INTO meta(key,value) VALUES ('last_update_at',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )
            conn.execute(
                """
                INSERT INTO update_history(version, applied_at, package_sha256,
                                           law_count, status, detail)
                VALUES (?,?,?,?, 'success', ?)
                """,
                (new_version, now, package_sha256, len(laws), f"mode={mode}"),
            )
        return len(laws)

    def record_failed_update(self, version: str, package_sha256: str,
                             detail: str) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO update_history(version, applied_at, package_sha256,
                                           law_count, status, detail)
                VALUES (?,?,?,0,'failed',?)
                """,
                (version, utcnow(), package_sha256, detail),
            )

    def update_history(self, limit: int = 10) -> list[UpdateRecord]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM update_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            UpdateRecord(
                version=r["version"], applied_at=r["applied_at"],
                package_sha256=r["package_sha256"], law_count=r["law_count"],
                status=r["status"], detail=r["detail"],
            )
            for r in rows
        ]

    # ---------------- 备份 / 回滚（配合 shutil 文件管理） ----------------
    def backup_to(self, target_path) -> None:
        """一致性备份：用 SQLite 官方 backup API，避免直接 copy 文件造成半页。"""
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        src = self._connect()
        dst = sqlite3.connect(str(target_path))
        try:
            src.backup(dst)
        finally:
            # with conn 不会关闭连接，必须显式 close，否则 WAL 被占用导致回滚删不掉
            src.close()
            dst.close()

    def stats(self) -> dict:
        with self._read() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM laws").fetchone()["c"]
            by_name = conn.execute(
                "SELECT law_name, COUNT(*) AS c FROM laws GROUP BY law_name ORDER BY c DESC"
            ).fetchall()
        return {
            "law_version": self.law_version,
            "law_count": total,
            "last_update_at": self.get_meta("last_update_at"),
            "fts_available": self.fts_available,
            "by_law": [{"law_name": r["law_name"], "count": r["c"]} for r in by_name],
        }


if __name__ == "__main__":
    import tempfile
    db = LegalDatabase(Path(tempfile.gettempdir()) / "legal_selftest.db")
    laws = [
        Law("mfd-238", "中华人民共和国民法典", "物权编", "第二百三十八条", "C",
            "侵害物权，造成权利人损害的，权利人可以依法请求损害赔偿。", "物权 损害赔偿", "全国人大", "2021-01-01"),
        Law("wygl-11", "物业管理条例", "", "第十一条", "B",
            "下列事项由业主共同决定：制定和修改业主大会议事规则。", "业主共同决定", "国务院", "2018-03-19"),
    ]
    n = db.replace_all(laws, "2026.11.0", "abc123", mode="full")
    print("写入条文:", n, "| 当前版本:", db.law_version)
    print("统计:", json.dumps(db.stats(), ensure_ascii=False))
    print("检索 '物权':", [x.law_id for x in db.search("物权")])
    print("更新历史:", [r.version for r in db.update_history()])
    # 增量替换测试
    db.replace_all([Law("mfd-239", "中华人民共和国民法典", "物权编", "第二百三十九条", "C",
                        "本章规定的物权保护方式，可以单独适用。")], "2026.11.1", "def456", mode="incremental")
    print("增量后条文数:", db.law_count, "| 版本:", db.law_version)
