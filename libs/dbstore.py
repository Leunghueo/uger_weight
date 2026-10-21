"""user.db 初始化与测量记录存取.

表:
    TblUser    - 登录用户（沿用旧结构）
    TblMeasure - 测量记录，结构与报告模板 abc.xlsx 1:1 对应：
        operator 操作者 / measure_time 时间 / model 车型 / car_no 车号 /
        direction 进车方向 / wheels_json 轮数据(18) / axles_json 轴数据(9) /
        total_kg 整车重(kg) / balance_kg 不平衡检测(kg)，另 platforms
        启用台号、tare_json 去皮量为流程数据。轮/轴数据字段名与模板
        一致（轮号/轮重(kg)/偏差(%)/轴号/轴重(kg)），单位 kg。

旧库（serial_no/values_json/results_json 结构）会在 init_db 时
自动迁移：进车方向取原 serial_no，轮/轴数据由旧结果换算（kN->kg）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from measure import KN_TO_KG, report_skeleton, to_report_data

CREATE_USER_SQL = """
CREATE TABLE IF NOT EXISTS TblUser(
  [id] VARCHAR(50) PRIMARY KEY,
  [UserName] CHAR(20),
  [LoginPassword] CHAR(255),
  [UserClass] CHAR(255))
"""

_MEASURE_COLUMNS = """
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operator TEXT DEFAULT '',
  measure_time TEXT NOT NULL,
  model TEXT NOT NULL,
  car_no TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT '',
  wheels_json TEXT NOT NULL DEFAULT '[]',
  axles_json TEXT NOT NULL DEFAULT '[]',
  total_kg REAL,
  balance_kg REAL,
  platforms TEXT NOT NULL DEFAULT '[]',
  tare_json TEXT,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
"""

CREATE_MEASURE_SQL = f"CREATE TABLE IF NOT EXISTS TblMeasure({_MEASURE_COLUMNS})"

CREATE_INDEX_SQLS = [
    "CREATE INDEX IF NOT EXISTS idx_measure_model ON TblMeasure(model)",
    "CREATE INDEX IF NOT EXISTS idx_measure_car ON TblMeasure(car_no)",
    "CREATE INDEX IF NOT EXISTS idx_measure_time ON TblMeasure(measure_time)",
]

# 新装时预置的演示账号（沿用旧库口令）
_SEED_USERS = [
    ("1", "admin", "0", "SUPERUSER"),
    ("2", "测试人", "111", "USER"),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _loads(raw: Any, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _migrate_old_measure_table(conn: sqlite3.Connection) -> None:
    """旧 TblMeasure（results_json 等）-> 新结构，逐行换算。"""
    conn.row_factory = sqlite3.Row
    old_rows = conn.execute("SELECT * FROM TblMeasure ORDER BY id").fetchall()
    conn.execute(f"CREATE TABLE TblMeasure_new({_MEASURE_COLUMNS})")
    for row in old_rows:
        results = _loads(row["results_json"], {})
        if isinstance(results, dict):
            # 旧版结果为 kN，迁移时换算为 kg（新版测量已在测量时换算）
            results = {
                **results,
                "wheels": {k: (None if v is None else float(v) * KN_TO_KG)
                           for k, v in (results.get("wheels") or {}).items()},
                "axles": {k: float(v) * KN_TO_KG
                          for k, v in (results.get("axles") or {}).items()},
                "total": (None if results.get("total") is None
                          else float(results["total"]) * KN_TO_KG),
                "balance": (None if results.get("balance") is None
                            else float(results["balance"]) * KN_TO_KG),
            }
        else:
            results = {}
        data = to_report_data(results)
        conn.execute(
            """
            INSERT INTO TblMeasure_new
              (id, operator, measure_time, model, car_no, direction,
               wheels_json, axles_json, total_kg, balance_kg,
               platforms, tare_json, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["id"], "", row["measure_time"], row["model"], row["car_no"],
                row["serial_no"] or "",
                json.dumps(data["wheels"], ensure_ascii=False),
                json.dumps(data["axles"], ensure_ascii=False),
                data["total_kg"], data["balance_kg"],
                row["platforms"] or "[]", row["tare_json"],
                row["note"] or "", row["created_at"],
            ),
        )
    conn.execute("DROP TABLE TblMeasure")
    conn.execute("ALTER TABLE TblMeasure_new RENAME TO TblMeasure")
    conn.row_factory = None


def init_db(db_path: str | Path) -> Path:
    """确保数据库文件、表结构、演示账号就绪。幂等；旧库自动迁移。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_USER_SQL)
        cols = _table_columns(conn, "TblMeasure")
        if cols and "results_json" in cols and "wheels_json" not in cols:
            _migrate_old_measure_table(conn)
        conn.execute(CREATE_MEASURE_SQL)
        for sql in CREATE_INDEX_SQLS:
            conn.execute(sql)
        row = conn.execute("SELECT COUNT(*) FROM TblUser").fetchone()
        if row and row[0] == 0:
            conn.executemany(
                "INSERT INTO TblUser(id, UserName, LoginPassword, UserClass) VALUES(?,?,?,?)",
                _SEED_USERS,
            )
        conn.commit()
    return db_path


def _now_str() -> str:
    """本地时间，格式 2026-10-21 20:10:21。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def insert_measure(
    db_path: str | Path,
    *,
    model: str,
    car_no: str,
    direction: str,
    operator: str = "",
    measure_time: str = "",
    platforms: list[int] | None = None,
    tare: dict | None = None,
    note: str = "",
) -> int:
    """新建未测量记录：轮/轴数据为空结构，整车重/不平衡为 NULL。"""
    skeleton = report_skeleton()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO TblMeasure
              (operator, measure_time, model, car_no, direction,
               wheels_json, axles_json, total_kg, balance_kg,
               platforms, tare_json, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                operator, measure_time or _now_str(), model, car_no, direction,
                json.dumps(skeleton["wheels"], ensure_ascii=False),
                json.dumps(skeleton["axles"], ensure_ascii=False),
                None, None,
                json.dumps(platforms or [], ensure_ascii=False),
                json.dumps(tare or {}, ensure_ascii=False),
                note, _now_str(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["platforms"] = _loads(d.get("platforms"), [])
    d["tare"] = _loads(d.pop("tare_json", None), {})
    d["wheels"] = _loads(d.pop("wheels_json", None), [])
    d["axles"] = _loads(d.pop("axles_json", None), [])
    return d


def list_measures(
    db_path: str | Path,
    *,
    model: str = "",
    car_no: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        where, params = ["1=1"], []
        if model:
            where.append("model LIKE ?")
            params.append(f"%{model}%")
        if car_no:
            where.append("car_no LIKE ?")
            params.append(f"%{car_no}%")
        if date_from:
            where.append("date(measure_time) >= date(?)")
            params.append(date_from)
        if date_to:
            where.append("date(measure_time) <= date(?)")
            params.append(date_to)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM TblMeasure
            WHERE {' AND '.join(where)}
            ORDER BY measure_time DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_measure(db_path: str | Path, record_id: int) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM TblMeasure WHERE id = ?", (record_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def update_measure_meta(
    db_path: str | Path,
    record_id: int,
    *,
    model: str,
    car_no: str,
    direction: str,
    note: str = "",
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE TblMeasure SET model=?, car_no=?, direction=?, note=? WHERE id=?",
            (model, car_no, direction, note, record_id),
        )
        conn.commit()


def save_measure_result(
    db_path: str | Path,
    record_id: int,
    *,
    measure_time: str,
    operator: str,
    platforms: list[int],
    tare: dict,
    wheels: list,
    axles: list,
    total_kg: float | None,
    balance_kg: float | None,
) -> None:
    """保存测量结果（存储结构即报告结构，单位 kg）。"""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE TblMeasure
            SET measure_time=?, operator=?, platforms=?, tare_json=?,
                wheels_json=?, axles_json=?, total_kg=?, balance_kg=?
            WHERE id=?
            """,
            (
                measure_time, operator,
                json.dumps(platforms, ensure_ascii=False),
                json.dumps(tare, ensure_ascii=False),
                json.dumps(wheels, ensure_ascii=False),
                json.dumps(axles, ensure_ascii=False),
                total_kg, balance_kg,
                record_id,
            ),
        )
        conn.commit()


def update_measure_tare(db_path: str | Path, record_id: int, tare: dict) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE TblMeasure SET tare_json=? WHERE id=?",
            (json.dumps(tare, ensure_ascii=False), record_id),
        )
        conn.commit()


def delete_measure(db_path: str | Path, record_id: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM TblMeasure WHERE id=?", (record_id,))
        conn.commit()
