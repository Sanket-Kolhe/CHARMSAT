import sqlite3
import json
from typing import Dict, Any, List, Optional
from pathlib import Path

DB_PATH = Path("charmsat_history.db")

class StorageEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            # Rule sets table
            c.execute("""
                CREATE TABLE IF NOT EXISTS rule_sets (
                    name TEXT PRIMARY KEY,
                    yaml_content TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Projects & Revisions table
            c.execute("""
                CREATE TABLE IF NOT EXISTS project_history (
                    id TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    signals_json TEXT NOT NULL,
                    alloc_result_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Benchmark results table
            c.execute("""
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_name TEXT NOT NULL,
                    signal_count INTEGER NOT NULL,
                    engine TEXT NOT NULL,
                    violations INTEGER NOT NULL,
                    cabinets INTEGER NOT NULL,
                    lower_bound INTEGER NOT NULL,
                    rev_b_moves INTEGER NOT NULL,
                    runtime_s REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Per-customer header mapping profiles: remember a confirmed mapping
            # so the next file from the same customer auto-maps.
            c.execute("""
                CREATE TABLE IF NOT EXISTS mapping_profiles (
                    name TEXT PRIMARY KEY,
                    signature TEXT NOT NULL,
                    overrides_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_mapping_sig ON mapping_profiles (signature)")
            conn.commit()

    def save_rule_set(self, name: str, yaml_content: str):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO rule_sets (name, yaml_content, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (name, yaml_content))
            conn.commit()

    def get_rule_set(self, name: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT yaml_content FROM rule_sets WHERE name = ?", (name,))
            row = c.fetchone()
            return row[0] if row else None

    def list_rule_sets(self) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM rule_sets ORDER BY updated_at DESC")
            return [row[0] for row in c.fetchall()]

    @staticmethod
    def header_signature(header: List[str]) -> str:
        """Stable signature for a header row: order-insensitive, case/space-folded."""
        import hashlib
        norm = sorted(str(h).strip().lower() for h in header)
        return hashlib.sha256("|".join(norm).encode("utf-8")).hexdigest()[:16]

    def save_mapping_profile(self, name: str, overrides: Dict[str, Any], signature: str):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO mapping_profiles (name, signature, overrides_json, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (name, signature, json.dumps(overrides)))
            conn.commit()

    def get_mapping_profile(self, name: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT name, signature, overrides_json FROM mapping_profiles WHERE name = ?", (name,))
            row = c.fetchone()
            return {"name": row[0], "signature": row[1], "overrides": json.loads(row[2])} if row else None

    def find_mapping_profile_by_signature(self, signature: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT name, signature, overrides_json FROM mapping_profiles WHERE signature = ? "
                      "ORDER BY updated_at DESC LIMIT 1", (signature,))
            row = c.fetchone()
            return {"name": row[0], "signature": row[1], "overrides": json.loads(row[2])} if row else None

    def list_mapping_profiles(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT name, signature, overrides_json, updated_at FROM mapping_profiles "
                      "ORDER BY updated_at DESC")
            return [{"name": r[0], "signature": r[1], "overrides": json.loads(r[2]), "updated_at": r[3]}
                    for r in c.fetchall()]

    def delete_mapping_profile(self, name: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM mapping_profiles WHERE name = ?", (name,))
            conn.commit()
            return c.rowcount > 0

    def save_benchmark(self, run_name: str, count: int, engine: str, viols: int, cabs: int, lb: int, moves: int, runtime: float):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO benchmark_runs (run_name, signal_count, engine, violations, cabinets, lower_bound, rev_b_moves, runtime_s)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_name, count, engine, viols, cabs, lb, moves, runtime))
            conn.commit()

    def get_benchmarks(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT run_name, signal_count, engine, violations, cabinets, lower_bound, rev_b_moves, runtime_s, created_at FROM benchmark_runs ORDER BY id DESC")
            rows = c.fetchall()
            return [
                {
                    "run_name": r[0],
                    "signal_count": r[1],
                    "engine": r[2],
                    "violations": r[3],
                    "cabinets": r[4],
                    "lower_bound": r[5],
                    "rev_b_moves": r[6],
                    "runtime_s": r[7],
                    "created_at": r[8]
                }
                for r in rows
            ]
