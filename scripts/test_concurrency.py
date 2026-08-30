"""Quick concurrency test: simulate multiple parallel audit writes to SQLite."""

from __future__ import annotations

import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def worker(worker_id: int, db_path: Path) -> tuple[int, float]:
    """Simulate an audit result write."""
    start = time.time()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"proj-{worker_id}", 100, 3.0, 0, "main", f"abc{worker_id:04d}", 1),
        )
        conn.commit()
        elapsed = time.time() - start
        return worker_id, elapsed
    except Exception as e:
        print(f"  Worker {worker_id}: ERROR: {e}")
        return worker_id, -1
    finally:
        conn.close()


# Setup
with tempfile.TemporaryDirectory() as tmp:
    db_path = Path(tmp) / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metrics ("
        "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "project TEXT, loc INTEGER, ccn REAL, warnings INTEGER, "
        "branch TEXT, commit_hash TEXT, runs_count INTEGER DEFAULT 1, "
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.close()

    print(f"Testing {db_path} with 100 concurrent writes...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(worker, i, db_path): i for i in range(100)}
        errors = 0
        for future in as_completed(futures):
            wid, elapsed = future.result()
            if elapsed < 0:
                errors += 1

    print(f"  Errors: {errors}/100")
    print(f"  Result: {'PASS - no concurrency issues' if errors == 0 else 'FAIL - concurrency issues detected'}")
