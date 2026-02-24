#!/usr/bin/env python3
import argparse
import base64
import csv
import hashlib
import os
import posixpath
import re
import sqlite3
import subprocess
import sys
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

SRC_EXTS = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".inc", ".m", ".mm",
}

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
DIFF_PLUS_RE = re.compile(r"^\+\+\+ b/(.+)$")
URL_RE = re.compile(r"https?://[^\s)>\"]+")
HEX_RE = re.compile(r"[0-9a-fA-F]{7,40}")
BASE64_RE = re.compile(rb"[A-Za-z0-9+/=\r\n]+\Z")
STACK_LINE_RE = re.compile(
    r"^\s*#\d+\s+0x[0-9a-fA-F]+\s+(?:in\s+)?(?P<func>.*?)\s+"
    r"(?P<path>/[^:\s]+):(?P<line>\d+)(?::\d+)?"
)

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


def fetch_url(url, timeout=25):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "arvo-location-check/1.0",
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
    if b"diff --git" in data or b"+++ b/" in data:
        return data
    if BASE64_RE.match(data.strip()):
        try:
            decoded = base64.b64decode(data)
            if b"diff --git" in decoded or b"+++ b/" in decoded:
                return decoded
        except Exception:
            pass
    return data


def fetch_patch_from_url(url, cache_dir):
    for cand in patch_url_candidates(url):
        cached = read_cache(cache_dir, cand)
        if cached is not None:
            text = maybe_decode_patch(cached)
            if b"diff --git" in text or b"+++ b/" in text:
                return text.decode("utf-8", errors="ignore"), cand
        try:
            data = fetch_url(cand)
        except (URLError, HTTPError, TimeoutError):
            continue
        write_cache(cache_dir, cand, data)
        text = maybe_decode_patch(data)
        if b"diff --git" in text or b"+++ b/" in text:
            return text.decode("utf-8", errors="ignore"), cand
    return None, None


def normalize_repo_url(repo_url):
    if not repo_url:
        return None
    url = repo_url.strip()
    if not url:
        return None
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


def git_show_patch(repo_url, commit, cache_dir):
    if not repo_url or not commit:
        return None
    norm = normalize_repo_url(repo_url)
    if not norm:
        return None
    if norm in BAD_REPOS:
        return None
    repo_dir = os.path.join(cache_dir, "git", sha1(norm))
    os.makedirs(repo_dir, exist_ok=True)
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        try:
            subprocess.run(["git", "init"], cwd=repo_dir, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
            subprocess.run(["git", "remote", "add", "origin", norm], cwd=repo_dir, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            BAD_REPOS.add(norm)
            return None
    try:
        subprocess.run(["git", "fetch", "--depth", "1", "origin", commit], cwd=repo_dir, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        try:
            subprocess.run(["git", "fetch", "--depth", "200", "origin"], cwd=repo_dir, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            BAD_REPOS.add(norm)
            return None
    try:
        out = subprocess.check_output(["git", "show", "--no-color", commit], cwd=repo_dir,
                                      stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    text = out.decode("utf-8", errors="ignore")
    if "diff --git" in text or "+++ b/" in text:
        return text
    return None


def normalize_commit(value):
    if not value:
        return None
    m = HEX_RE.search(value)
    return m.group(0) if m else None


def extract_urls(text):
    if not text:
        return []
    seen = set()
    out = []
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".,;:")
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def candidate_patch_urls(patch_url, report):
    out = []
    seen = set()
    for u in [patch_url] + extract_urls(report):
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def normalize_path(path):
    p = (path or "").replace("\\", "/")
    if "+0x" in p:
        p = p.split("+0x", 1)[0]
    p = p.rstrip(":),")
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return posixpath.normpath(p)


def path_matches(crash_file, patch_file):
    c = normalize_path(crash_file)
    p = normalize_path(patch_file)
    return c == p or c.endswith("/" + p) or c.endswith(p)


def extract_patch_hunks(diff_text):
    file_to_ranges = {}
    current = None
    for line in diff_text.splitlines():
        m = DIFF_GIT_RE.match(line)
        if m:
            path = m.group(2)
            current = normalize_path(path) if path != "/dev/null" else None
            if current and current not in file_to_ranges:
                file_to_ranges[current] = []
            continue
        m = DIFF_PLUS_RE.match(line)
        if m:
            path = m.group(1)
            current = normalize_path(path) if path != "/dev/null" else None
            if current and current not in file_to_ranges:
                file_to_ranges[current] = []
            continue
        m = HUNK_RE.match(line)
        if not m or not current:
            continue
        start = int(m.group(1))
        length = int(m.group(2)) if m.group(2) else 1
        end = start if length <= 1 else start + length - 1
        file_to_ranges[current].append((start, end))
    return file_to_ranges


def ignored_frame(path, func):
    p = (path or "").lower()
    f = (func or "").lower()
    if "/llvm-project/" in p:
        return True
    if "/compiler-rt/lib/fuzzer/" in p or "/src/libfuzzer/" in p:
        return True
    if "afl_driver.cpp" in p:
        return True
    ignore_tokens = [
        "llvmfuzzertestoneinput",
        "fuzzer::",
        "__sanitizer",
        "__interceptor",
        "executefilesonybyone",
    ]
    return any(t in f for t in ignore_tokens)


def extract_crash_locations(crash_output):
    rows = []
    ignored = 0
    if not crash_output:
        return rows, ignored
    for line in crash_output.splitlines():
        m = STACK_LINE_RE.match(line)
        if not m:
            continue
        path = normalize_path(m.group("path"))
        func = (m.group("func") or "").strip()
        line_no = int(m.group("line"))
        ext = os.path.splitext(path)[1].lower()
        if ext not in SRC_EXTS:
            continue
        if ignored_frame(path, func):
            ignored += 1
            continue
        rows.append((path, line_no, func))
    return rows, ignored


def parse_args():
    ap = argparse.ArgumentParser(
        description="Check location overlap between crash stack and patch hunks for on_crash_log=1 rows."
    )
    ap.add_argument("--db", required=True, help="Input sqlite DB")
    ap.add_argument("--out-csv", required=True, help="Output CSV report")
    ap.add_argument("--out-db", help="Optional DB to update with on_crash_loc_match")
    ap.add_argument("--cache-dir", default="/tmp/arvo_patch_cache", help="Cache dir")
    ap.add_argument("--use-git", action="store_true", help="Fallback to git fetch+show")
    ap.add_argument("--limit", type=int, default=0, help="Row limit")
    ap.add_argument("--offset", type=int, default=0, help="Row offset")
    ap.add_argument("--log-every", type=int, default=100, help="Progress interval")
    ap.add_argument("--append-csv", action="store_true", help="Append CSV")
    ap.add_argument("--resume-db", action="store_true", help="Reuse output DB")
    ap.add_argument("--only-null", action="store_true",
                    help="Only process rows where on_crash_loc_match IS NULL (requires out-db column)")
    return ap.parse_args()


def main():
    args = parse_args()
    in_conn = sqlite3.connect(args.db)
    in_cur = in_conn.cursor()

    out_conn = None
    if args.out_db:
        if os.path.exists(args.out_db) and not args.resume_db:
            os.remove(args.out_db)
        if not os.path.exists(args.out_db):
            with open(args.db, "rb") as src, open(args.out_db, "wb") as dst:
                dst.write(src.read())
        out_conn = sqlite3.connect(args.out_db)
        out_cur = out_conn.cursor()
        try:
            out_cur.execute("ALTER TABLE arvo ADD COLUMN on_crash_loc_match INTEGER")
            out_conn.commit()
        except sqlite3.OperationalError:
            pass

    query = (
        "SELECT localId, project, patch_url, fix_commit, repo_addr, crash_output, report, on_crash_log "
        "FROM arvo WHERE on_crash_log=1"
    )
    if args.only_null:
        query += " AND (on_crash_loc_match IS NULL)"
    query += " ORDER BY localId"
    if args.limit and args.limit > 0:
        query += f" LIMIT {args.limit}"
    if args.offset and args.offset > 0:
        query += f" OFFSET {args.offset}"

    out_dir = os.path.dirname(os.path.abspath(args.out_csv))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    total = 0
    matched = 0
    mismatched = 0
    unknown = 0
    no_patch = 0

    mode = "a" if args.append_csv else "w"
    with open(args.out_csv, mode, encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not args.append_csv:
            w.writerow([
                "localId",
                "project",
                "on_crash_log",
                "on_crash_loc_match",
                "patch_source",
                "matched_files",
                "overlap_files",
                "crash_locations",
                "ignored_frames",
            ])

        for row in in_cur.execute(query):
            total += 1
            local_id, project, patch_url, fix_commit, repo_addr, crash_output, report, on_crash = row

            patch_text = None
            patch_source = None
            for url in candidate_patch_urls(patch_url, report):
                patch_text, patch_source = fetch_patch_from_url(url, args.cache_dir)
                if patch_text is not None:
                    break

            if patch_text is None and args.use_git:
                commit = normalize_commit(fix_commit or "")
                if commit:
                    candidates = []
                    if repo_addr:
                        candidates.append(repo_addr)
                    for url in candidate_patch_urls(patch_url, report):
                        rep = derive_repo_from_url(url)
                        if rep:
                            candidates.append(rep)
                    seen = set()
                    for rep in candidates:
                        rep_norm = normalize_repo_url(rep)
                        if not rep_norm or rep_norm in seen:
                            continue
                        seen.add(rep_norm)
                        patch_text = git_show_patch(rep_norm, commit, args.cache_dir)
                        if patch_text is not None:
                            patch_source = "git"
                            break

            crash_locs, ignored = extract_crash_locations(crash_output or "")
            if patch_text is None:
                loc_match = -1
                no_patch += 1
                overlap_files = []
                matched_files = []
            else:
                hunks = extract_patch_hunks(patch_text)
                patch_files = sorted(hunks.keys())
                matched_files = sorted({
                    pf for pf in patch_files for cf, _, _ in crash_locs if path_matches(cf, pf)
                })
                overlap_files = set()
                for cf, line_no, _ in crash_locs:
                    for pf in matched_files:
                        if not path_matches(cf, pf):
                            continue
                        for start, end in hunks.get(pf, []):
                            if start <= line_no <= end:
                                overlap_files.add(pf)
                                break
                if overlap_files:
                    loc_match = 1
                    matched += 1
                elif matched_files:
                    loc_match = 0
                    mismatched += 1
                else:
                    loc_match = -1
                    unknown += 1
                overlap_files = sorted(overlap_files)

            if out_conn:
                out_cur.execute(
                    "UPDATE arvo SET on_crash_loc_match=? WHERE localId=?",
                    (loc_match, local_id),
                )
                if total % 100 == 0:
                    out_conn.commit()

            crash_loc_text = ";".join(
                f"{cf}:{ln}:{fn}" for cf, ln, fn in crash_locs
            )
            w.writerow([
                local_id,
                project or "",
                on_crash,
                loc_match,
                patch_source or "",
                ";".join(matched_files),
                ";".join(overlap_files),
                crash_loc_text,
                ignored,
            ])

            if args.log_every and total % args.log_every == 0:
                log(
                    f"processed={total} loc_match=1:{matched} loc_match=0:{mismatched} "
                    f"loc_match=-1:{unknown} no_patch:{no_patch}"
                )

    if out_conn:
        out_conn.commit()
        out_conn.close()
    in_conn.close()
    log(
        f"done total={total} loc_match=1:{matched} loc_match=0:{mismatched} "
        f"loc_match=-1:{unknown} no_patch={no_patch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
