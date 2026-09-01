"""
database/inspect.py — CLI inspection utility for Phase 2.

Usage:
  python -m database.inspect          # pretty print current DB
  python -m database.inspect --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m database.inspect` when cwd is paytrust-ai
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.database import inspect_db, get_db_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect PayTrust AI SQLite DB")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--db", type=str, default=None, help="Override DB path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None
    info = inspect_db(db_path) if db_path else inspect_db()

    if args.json:
        print(json.dumps(info, indent=2, default=str))
        return

    print(f"DB path      : {info.get('db_path')}")
    print(f"Exists       : {info.get('exists')}")
    print(f"Size         : {info.get('size_bytes', 0):,} bytes")
    print(f"SQLite       : {info.get('sqlite_version')}")
    print(f"Journal      : {info.get('journal_mode')}")
    print(f"FK enforced  : {info.get('foreign_keys')}")
    print(f"Tables       : {', '.join(info.get('tables', []))}")
    print("Counts:")
    for table, count in sorted((info.get("counts") or {}).items()):
        print(f"  {table:20s} {count:6d}")
    if info.get("has_api_key_column"):
        print("WARNING: table contains api_key column — secrets must not be stored in DB!")
    else:
        print("Secret check : no api_key columns (OK)")


if __name__ == "__main__":
    main()
