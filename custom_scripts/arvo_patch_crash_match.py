#!/usr/bin/env python3
import argparse
import base64
import csv
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

SRC_EXTS = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".inc",
    ".m", ".mm",
}

DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
DIFF_PLUS_RE = re.compile(r"^\+\+\+ b/(.+)$")
DIFF_INDEX_RE = re.compile(r"^Index: (.+)$")

BASE64_RE = re.compile(rb"[A-Za-z0-9+/=\r\n]+\Z")
HEX_RE = re.compile(r"[0-9a-fA-F]{7,40}")
URL_RE = re.compile(r"https?://[^\s)>\"]+")

BAD_REPOS = set()
GIT_TIMEOUT = 12


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def read_cache(cache_dir, key):
    if not cache_dir:
        return None
    path = os.path.join(cache_dir, sha1(key) + ".patch")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def write_cache(cache_dir, key, data):
    if not cache_dir:
        return
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, sha1(key) + ".patch")
    with open(path, "wb") as f:
        f.write(data)


def fetch_url(url, timeout=30):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "arvo-patch-check/1.0",
            "Accept": "text/plain, text/x-diff, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def patch_url_candidates(url):
    if url.endswith(".patch") or url.endswith(".diff"):
        return [url]
    if "github.com" in url and "/commit/" in url:
        return [url + ".patch", url + ".diff", url + ".patch?full_index=1", url]
    if "gitlab" in url and "/-/commit/" in url:
        return [url + ".patch", url + ".diff", url]
    if "gitlab" in url and "/-/merge_requests/" in url:
        return [url + ".diff", url + ".patch", url]
    if "bitbucket.org" in url and "/commits/" in url:
        return [url + ".patch", url]
    if "googlesource.com" in url and "/+/" in url:
        return [url + "?format=TEXT", url]
    return [url]


def maybe_decode_patch(data):
    if b"diff --git" in data or b"Index:" in data or b"+++ b/" in data:
        return data
    if BASE64_RE.match(data.strip()):
        try:
            decoded = base64.b64decode(data)
        except Exception:
            return data
        if b"diff --git" in decoded or b"Index:" in decoded or b"+++ b/" in decoded:
            return decoded
    return data


def fetch_patch_from_url(url, cache_dir=None):
    for cand in patch_url_candidates(url):
        cached = read_cache(cache_dir, cand)
        if cached is not None:
            text = maybe_decode_patch(cached)
            if b"diff --git" in text or b"Index:" in text or b"+++ b/" in text:
                return text.decode("utf-8", errors="ignore"), cand
        try:
            data = fetch_url(cand)
        except (URLError, HTTPError, TimeoutError) as e:
            continue
        write_cache(cache_dir, cand, data)
        text = maybe_decode_patch(data)
        if b"diff --git" in text or b"Index:" in text or b"+++ b/" in text:
            return text.decode("utf-8", errors="ignore"), cand
    return None, None


def normalize_repo_url(repo_url):
    if not repo_url:
        return None
    url = repo_url.strip()
    if not url:
        return None
    # Fix malformed scheme like "https:/github.com/..."
    url = re.sub(r"^(https?):/([^/])", r"\1://\2", url)
    if url.startswith("//"):
        url = "https:" + url
    if "://" not in url and "." in url and "/" in url:
        url = "https://" + url.lstrip("/")
    if url.startswith("git@") and ":" in url:
        host_repo = url.split("@", 1)[1]
        host, repo = host_repo.split(":", 1)
        url = f"https://{host}/{repo}"
    elif url.startswith("ssh://git@"):
        parsed = urlparse(url)
        if parsed.hostname and parsed.path:
            url = f"https://{parsed.hostname}{parsed.path}"
    elif url.startswith("git://"):
        parsed = urlparse(url)
        if parsed.hostname and parsed.path:
            url = f"https://{parsed.hostname}{parsed.path}"
    return url


def derive_repo_from_url(url):
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    host = parsed.netloc
    if host == "github.com" and len(parts) >= 2:
        return f"{parsed.scheme}://{host}/{parts[0]}/{parts[1]}"
    if "gitlab" in host and len(parts) >= 2:
        if "-" in parts:
            idx = parts.index("-")
            if idx >= 2:
                return f"{parsed.scheme}://{host}/{'/'.join(parts[:idx])}"
        return f"{parsed.scheme}://{host}/{parts[0]}/{parts[1]}"
    if "googlesource.com" in host:
        if "+" in parts:
            idx = parts.index("+")
            if idx >= 1:
                return f"{parsed.scheme}://{host}/{'/'.join(parts[:idx])}"
        return f"{parsed.scheme}://{host}/{'/'.join(parts)}"
    if host == "bitbucket.org" and len(parts) >= 2:
        return f"{parsed.scheme}://{host}/{parts[0]}/{parts[1]}"
    return None


def extract_urls(text):
    if not text:
        return []
    urls = []
    seen = set()
    for match in URL_RE.finditer(text):
        u = match.group(0).rstrip(".,;:")
        if u in seen:
            continue
        seen.add(u)
        urls.append(u)
    return urls


def candidate_patch_urls(patch_url, report):
    candidates = []
    seen = set()
    for url in [patch_url] + extract_urls(report):
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append(url)
    return candidates


def git_show_patch(repo_url, commit, cache_dir):
    if not repo_url or not commit:
        return None
    if not cache_dir:
        return None
    normalized_repo = normalize_repo_url(repo_url)
    if not normalized_repo:
        return None
    if normalized_repo in BAD_REPOS:
        return None
    repo_dir = os.path.join(cache_dir, "git", sha1(normalized_repo))
    os.makedirs(repo_dir, exist_ok=True)
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        try:
            subprocess.run(["git", "init"], cwd=repo_dir, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
            subprocess.run(["git", "remote", "add", "origin", normalized_repo], cwd=repo_dir, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            BAD_REPOS.add(normalized_repo)
            return None
    lock_path = os.path.join(repo_dir, ".git", "shallow.lock")
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except OSError:
            pass
    # Fetch commit if missing
    try:
        subprocess.run([
            "git", "fetch", "--depth", "1", "origin", commit
        ], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Retry with a broader fetch depth for hosts that disallow hash-only fetch.
        try:
            subprocess.run([
                "git", "fetch", "--depth", "200", "origin"
            ], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            BAD_REPOS.add(normalized_repo)
            return None
        try:
            out = subprocess.check_output([
                "git", "show", "--no-color", commit
            ], cwd=repo_dir, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
            patch = out.decode("utf-8", errors="ignore")
            if "diff --git" in patch or "+++ b/" in patch or "Index:" in patch:
                return patch
            return None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            BAD_REPOS.add(normalized_repo)
            return None
    try:
        out = subprocess.check_output([
            "git", "show", "--no-color", commit
        ], cwd=repo_dir, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    patch = out.decode("utf-8", errors="ignore")
    if "diff --git" in patch or "+++ b/" in patch or "Index:" in patch:
        return patch
    return None


def normalize_commit(value):
    if not value:
        return None
    match = HEX_RE.search(value)
    if not match:
        return None
    return match.group(0)


def extract_patch_files(diff_text):
    files = set()
    for line in diff_text.splitlines():
        m = DIFF_GIT_RE.match(line)
        if m:
            path = m.group(2)
            if path != "/dev/null":
                files.add(path)
            continue
        m = DIFF_PLUS_RE.match(line)
        if m:
            path = m.group(1)
            if path != "/dev/null":
                files.add(path)
            continue
        m = DIFF_INDEX_RE.match(line)
        if m:
            path = m.group(1)
            if path != "/dev/null":
                files.add(path)
            continue
    return files


def extract_crash_paths(crash_output):
    if not crash_output:
        return set()
    paths = set()
    for line in crash_output.splitlines():
        for match in re.finditer(r"(/[^\s\):]+\.[A-Za-z0-9_]+)", line):
            path = match.group(1).rstrip(":),")
            if "+0x" in path:
                path = path.split("+0x", 1)[0]
            ext = os.path.splitext(path)[1].lower()
            if ext in SRC_EXTS:
                paths.add(path)
    return paths


def normalize_path(path):
    path = path.replace("\\", "/")
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def match_paths(crash_paths, patch_paths):
    if not crash_paths or not patch_paths:
        return set()
    crash_norm = [normalize_path(p) for p in crash_paths]
    patch_norm = [normalize_path(p) for p in patch_paths]
    matched = set()
    for p in patch_norm:
        for c in crash_norm:
            if c.endswith("/" + p) or c.endswith(p):
                matched.add(p)
                break
    return matched


def parse_args():
    ap = argparse.ArgumentParser(description="Match patch files against crash log paths.")
    ap.add_argument("--db", required=True, help="Path to arvo sqlite db")
    ap.add_argument("--out-csv", required=True, help="Output CSV path")
    ap.add_argument("--out-db", help="Optional enriched sqlite db output")
    ap.add_argument("--cache-dir", default="/tmp/arvo_patch_cache", help="Cache dir")
    ap.add_argument("--use-git", action="store_true", help="Fallback to git fetch using repo_addr + fix_commit")
    ap.add_argument("--limit", type=int, default=0, help="Limit rows processed")
    ap.add_argument("--offset", type=int, default=0, help="Offset rows processed")
    ap.add_argument("--log-every", type=int, default=100, help="Progress log interval")
    ap.add_argument("--append-csv", action="store_true", help="Append to CSV (no header)")
    ap.add_argument("--resume-db", action="store_true", help="Reuse existing out-db if present")
    ap.add_argument("--only-null", action="store_true", help="Only process rows with on_crash_log IS NULL")
    ap.add_argument("--only-unresolved", action="store_true",
                    help="Only process rows with on_crash_log IS NULL or -1")
    return ap.parse_args()


def main():
    args = parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    out_conn = None
    if args.out_db:
        if os.path.exists(args.out_db) and not args.resume_db:
            os.remove(args.out_db)
        if not os.path.exists(args.out_db):
            # Copy db then add column
            with open(args.db, "rb") as src, open(args.out_db, "wb") as dst:
                dst.write(src.read())
        out_conn = sqlite3.connect(args.out_db)
        out_cur = out_conn.cursor()
        try:
            out_cur.execute("ALTER TABLE arvo ADD COLUMN on_crash_log INTEGER")
            out_conn.commit()
        except sqlite3.OperationalError:
            pass

    out_csv_dir = os.path.dirname(os.path.abspath(args.out_csv))
    if out_csv_dir:
        os.makedirs(out_csv_dir, exist_ok=True)

    total = 0
    matched_count = 0
    no_patch_count = 0

    query = "SELECT localId, project, patch_url, fix_commit, repo_addr, crash_output, report FROM arvo"
    if args.only_null or args.only_unresolved:
        try:
            cur.execute("PRAGMA table_info(arvo)")
            cols = {row[1] for row in cur.fetchall()}
            if "on_crash_log" in cols:
                if args.only_unresolved:
                    query += " WHERE on_crash_log IS NULL OR on_crash_log=-1"
                else:
                    query += " WHERE on_crash_log IS NULL"
        except sqlite3.OperationalError:
            pass
    query += " ORDER BY localId"
    if args.limit and args.limit > 0:
        query += f" LIMIT {args.limit}"
    if args.offset and args.offset > 0:
        query += f" OFFSET {args.offset}"

    csv_mode = "a" if args.append_csv else "w"
    with open(args.out_csv, csv_mode, encoding="utf-8", newline="") as csvf:
        writer = csv.writer(csvf)
        if not args.append_csv:
            writer.writerow(
                ["localId", "project", "patch_url", "fix_commit", "repo_addr",
                 "on_crash_log", "matched_files", "crash_files", "patch_source"]
            )

        for row in cur.execute(query):
            total += 1
            local_id, project, patch_url, fix_commit, repo_addr, crash_output, report = row

            crash_paths = extract_crash_paths(crash_output or "")

            patch_text = None
            patch_source = None
            for patch_candidate in candidate_patch_urls(patch_url, report):
                patch_text, patch_source = fetch_patch_from_url(patch_candidate, args.cache_dir)
                if patch_text is not None:
                    break

            commit_norm = normalize_commit(fix_commit or "")
            if patch_text is None and args.use_git and commit_norm:
                repo_candidates = []
                if repo_addr:
                    repo_candidates.append(repo_addr)
                for patch_candidate in candidate_patch_urls(patch_url, report):
                    derived_repo = derive_repo_from_url(patch_candidate)
                    if derived_repo:
                        repo_candidates.append(derived_repo)
                seen_repos = set()
                for repo_candidate in repo_candidates:
                    norm_repo = normalize_repo_url(repo_candidate)
                    if not norm_repo or norm_repo in seen_repos:
                        continue
                    seen_repos.add(norm_repo)
                    patch_text = git_show_patch(norm_repo, commit_norm, args.cache_dir)
                    if patch_text is not None:
                        patch_source = "git"
                        break

            if patch_text is None:
                on_crash_log = -1
                no_patch_count += 1
                matched_files = []
            else:
                patch_files = extract_patch_files(patch_text)
                matched = match_paths(crash_paths, patch_files)
                on_crash_log = 1 if matched else 0
                if matched:
                    matched_count += 1
                matched_files = sorted(matched)

            if out_conn:
                out_cur.execute(
                    "UPDATE arvo SET on_crash_log=? WHERE localId=?",
                    (on_crash_log, local_id),
                )
                if total % 100 == 0:
                    out_conn.commit()

            writer.writerow(
                [
                    local_id,
                    project or "",
                    patch_url or "",
                    fix_commit or "",
                    repo_addr or "",
                    on_crash_log,
                    ";".join(matched_files),
                    ";".join(sorted(crash_paths)),
                    patch_source or "",
                ]
            )

            if args.log_every and total % args.log_every == 0:
                log(f"processed {total}")

    if out_conn:
        out_conn.commit()
        out_conn.close()
    conn.close()

    log(f"done. total={total} matched={matched_count} no_patch={no_patch_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
