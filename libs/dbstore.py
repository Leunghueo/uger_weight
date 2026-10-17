"""user.db 初始化与测量记录存取.

表:
    TblUser    - 登录用户（沿用旧结构）
    TblMeasure - 测量记录：车型/车号/编号 + 18路称重 + 去皮 + 六项计算结果
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

CREATE_USER_SQL = """
CREATE TABLE IF NOT EXISTS TblUser(
  [id] VARCHAR(50) PRIMARY KEY,
  [UserName] CHAR(20),
  [LoginPassword] CHAR(255),
  [UserClass] CHAR(255))
"""

CREATE_MEASURE_SQL = """
CREATE TABLE IF NOT EXISTS TblMeasure(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model TEXT NOT NULL,
  car_no TEXT NOT NULL,
  serial_no TEXT NOT NULL,
  measure_time TEXT NOT NULL,
  platforms TEXT NOT NULL,
  tare_json TEXT,
  values_json TEXT NOT NULL,
  results_json TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL)
"""

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


def init_db(db_path: str | Path) -> Path:
    """确保数据库文件、表结构、演示账号就绪。幂等。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_USER_SQL)
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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def insert_measure(
    db_path: str | Path,
    *,
    model: str,
    car_no: str,
    serial_no: str,
    measure_time: str = "",
    platforms: list[int] | None = None,
    tare: dict | None = None,
    values: dict | None = None,
    results: dict | None = None,
    note: str = "",
) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO TblMeasure
              (model, car_no, serial_no, measure_time, platforms,
               tare_json, values_json, results_json, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                model, car_no, serial_no,
                measure_time or _now_iso(),
                json.dumps(platforms or [], ensure_ascii=False),
                json.dumps(tare or {}, ensure_ascii=False),
                json.dumps(values or {}, ensure_ascii=False),
                json.dumps(results or {}, ensure_ascii=False),
                note, _now_iso(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("platforms", "tare_json", "values_json", "results_json"):
        raw = d.get(key)
        try:
            d[key] = json.loads(raw) if raw else ({} if "json" in key else [])
        except (TypeError, ValueError):
            d[key] = {} if "json" in key else []
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
    serial_no: str,
    note: str = "",
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE TblMeasure SET model=?, car_no=?, serial_no=?, note=? WHERE id=?",
            (model, car_no, serial_no, note, record_id),
        )
        conn.commit()


def save_measure_result(
    db_path: str | Path,
    record_id: int,
    *,
    measure_time: str,
    platforms: list[int],
    tare: dict,
    values: dict,
    results: dict,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE TblMeasure
            SET measure_time=?, platforms=?, tare_json=?, values_json=?, results_json=?
            WHERE id=?
            """,
            (
                measure_time,
                json.dumps(platforms, ensure_ascii=False),
                json.dumps(tare, ensure_ascii=False),
                json.dumps(values, ensure_ascii=False),
                json.dumps(results, ensure_ascii=False),
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
