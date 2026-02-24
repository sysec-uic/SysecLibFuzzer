#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone


def q1(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else 0


def has_column(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def get_top(cur, column, top_n):
    cur.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM({column}), ''), '<empty>') AS key, COUNT(*) AS n
        FROM arvo
        GROUP BY key
        ORDER BY n DESC, key ASC
        LIMIT ?
        """,
        (top_n,),
    )
    return cur.fetchall()


def print_top(title, rows, top_n):
    print(f"\n{title} (top {top_n})")
    print("-" * (len(title) + 10))
    if not rows:
        print("(no rows)")
        return
    for key, n in rows:
        print(f"{n:6d}  {key}")


def main():
    ap = argparse.ArgumentParser(
        description="Print ARVO database state summary (projects, crash types, on_crash_log)."
    )
    ap.add_argument("--db", required=True, help="Path to ARVO sqlite db")
    ap.add_argument("--top", type=int, default=20, help="Top-N rows per category")
    ap.add_argument(
        "--json-out",
        help="Optional output path for machine-readable JSON snapshot",
    )
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    try:
        total = q1(cur, "SELECT COUNT(*) FROM arvo")
    except sqlite3.OperationalError as e:
        print(f"ERROR: failed to query table 'arvo': {e}", file=sys.stderr)
        return 1

    print("ARVO Database State")
    print("===================")
    print(f"db: {args.db}")
    print(f"total_bugs: {total}")

    crash_non_empty = q1(
        cur,
        "SELECT COUNT(*) FROM arvo WHERE crash_output IS NOT NULL AND TRIM(crash_output) <> ''",
    )
    patch_url_non_empty = q1(
        cur,
        "SELECT COUNT(*) FROM arvo WHERE patch_url IS NOT NULL AND TRIM(patch_url) <> ''",
    )
    fix_commit_non_empty = q1(
        cur,
        "SELECT COUNT(*) FROM arvo WHERE fix_commit IS NOT NULL AND TRIM(fix_commit) <> ''",
    )

    print(f"with_crash_output: {crash_non_empty}")
    print(f"with_patch_url: {patch_url_non_empty}")
    print(f"with_fix_commit: {fix_commit_non_empty}")

    on_crash_log = None
    if has_column(cur, "arvo", "on_crash_log"):
        n_null = q1(cur, "SELECT COUNT(*) FROM arvo WHERE on_crash_log IS NULL")
        n_neg1 = q1(cur, "SELECT COUNT(*) FROM arvo WHERE on_crash_log = -1")
        n_zero = q1(cur, "SELECT COUNT(*) FROM arvo WHERE on_crash_log = 0")
        n_one = q1(cur, "SELECT COUNT(*) FROM arvo WHERE on_crash_log = 1")
        on_crash_log = {
            "NULL": n_null,
            "-1": n_neg1,
            "0": n_zero,
            "1": n_one,
            "meaning": {
                "NULL": "not processed yet",
                "-1": "processed, but patch data could not be fetched/parsing failed",
                "0": "processed, patch found, but changed files do not match crash-log files",
                "1": "processed, at least one changed patch file appears in crash log",
            },
        }
        print("\non_crash_log breakdown")
        print("----------------------")
        print(f"NULL: {n_null}")
        print(f"  - not processed yet")
        print(f"-1:   {n_neg1}")
        print("  - processed, but patch data could not be fetched/parsing failed")
        print(f" 0:   {n_zero}")
        print("  - processed, patch found, but changed files do not match crash-log files")
        print(f" 1:   {n_one}")
        print("  - processed, at least one changed patch file appears in crash log")
    else:
        print("\non_crash_log breakdown")
        print("----------------------")
        print("column 'on_crash_log' does not exist in this DB")

    top_projects = get_top(cur, "project", args.top)
    top_crash_types = get_top(cur, "crash_type", args.top)
    top_sanitizers = get_top(cur, "sanitizer", args.top)
    top_languages = get_top(cur, "language", args.top)

    print_top("Projects", top_projects, args.top)
    print_top("Crash Types", top_crash_types, args.top)
    print_top("Sanitizers", top_sanitizers, args.top)
    print_top("Languages",top_languages,args.top )

    if args.json_out:
        out_dir = os.path.dirname(os.path.abspath(args.json_out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        snapshot = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "db": args.db,
            "summary": {
                "total_bugs": total,
                "with_crash_output": crash_non_empty,
                "with_patch_url": patch_url_non_empty,
                "with_fix_commit": fix_commit_non_empty,
            },
            "on_crash_log": on_crash_log,
            "top": {
                "projects": [{"name": k, "count": n} for k, n in top_projects],
                "crash_types": [{"name": k, "count": n} for k, n in top_crash_types],
                "sanitizers": [{"name": k, "count": n} for k, n in top_sanitizers],
                "languages": [{"name": k, "count": n} for k, n in top_languages],
            },
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, sort_keys=False)
        print(f"\njson_snapshot: {args.json_out}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
