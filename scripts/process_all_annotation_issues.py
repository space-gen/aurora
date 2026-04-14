#!/usr/bin/env python3
"""
Process all open issues labeled 'annotation': run parser per issue, commit/push annotation changes,
comment and close issues. Intended to be run inside GitHub Actions with `GITHUB_TOKEN` available.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any

import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")  # owner/repo

if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
    print("GITHUB_TOKEN and GITHUB_REPOSITORY must be set in env")
    sys.exit(1)

API_BASE = f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "aurora-processor",
}

COMMENT_BODY_SUCCESS = (
    "✅ **Annotation recorded!** Thank you for contributing to SolarHub.\n\n"
    "Your label has been saved and will be merged into the master HuggingFace dataset during the next automated pipeline run."
)

COMMENT_BODY_FAILURE = (
    "⚠️ **Annotation processing failed.** The automated parser could not process this issue."
)


def run_cmd(cmd: list[str], cwd: str | None = None, env: dict | None = None) -> tuple[int, str, str]:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env)
    out, err = p.communicate()
    return p.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


def list_annotation_issues() -> list[dict[str, Any]]:
    issues = []
    page = 1
    while True:
        url = f"{API_BASE}/issues"
        params = {"labels": "annotation", "state": "open", "per_page": 100, "page": page}
        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        issues.extend(batch)
        page += 1
    # Filter out PRs (they contain 'pull_request' key)
    return [i for i in issues if 'pull_request' not in i]


def comment_issue(number: int, body: str) -> None:
    url = f"{API_BASE}/issues/{number}/comments"
    r = requests.post(url, headers=HEADERS, json={"body": body})
    r.raise_for_status()


def add_label(number: int, labels: list[str]) -> None:
    url = f"{API_BASE}/issues/{number}/labels"
    r = requests.post(url, headers=HEADERS, json={"labels": labels})
    r.raise_for_status()


def close_issue(number: int) -> None:
    url = f"{API_BASE}/issues/{number}"
    r = requests.patch(url, headers=HEADERS, json={"state": "closed"})
    r.raise_for_status()


def main() -> None:
    repo_dir = os.getcwd()
    issues = list_annotation_issues()
    print(f"Found {len(issues)} open annotation issues")

    successes = []
    failures = []

    for issue in issues:
        num = issue["number"]
        body = issue.get("body", "")
        author = issue.get("user", {}).get("login", "unknown")
        print(f"Processing issue #{num} by {author}")

        env = os.environ.copy()
        env["ISSUE_NUMBER"] = str(num)
        env["ISSUE_BODY"] = body
        env["ISSUE_AUTHOR"] = author

        # Run the parser for this issue
        rc, out, err = run_cmd([sys.executable, "scripts/parse_issue_annotation.py"], cwd=repo_dir, env=env)
        print(f"Parser rc={rc}\nstdout:\n{out}\nstderr:\n{err}")

        if rc == 0:
            successes.append({"number": num, "author": author})
        else:
            failures.append({"number": num, "error": err})

    # After processing all issues, commit any annotation changes once
    run_cmd(["git", "add", "annotations/"], cwd=repo_dir)
    rc2, out2, err2 = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=repo_dir)
    commit_ok = False
    if out2.strip():
        issue_nums = [s["number"] for s in successes]
        coauthors = ""
        for s in successes:
            # Keep author name; email unknown in parser context
            coauthors += f"Co-authored-by: {s['author']} <>\n"
        commit_msg = f"chore(annotation): record annotations from issues {', '.join(['#'+str(n) for n in issue_nums])} [skip ci]\n\n{coauthors}"

        # Use an orphan 'data' branch so annotation commits do not bloat main history.
        # Copy annotations to a temporary location and create a clean orphan branch with only annotations.
        tmpdir = "/tmp/annotations_payload"
        try:
            import shutil
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir)
            shutil.copytree(os.path.join(repo_dir, "annotations"), tmpdir)
        except Exception:
            # If copying fails, fall back to committing from current working tree (safer default)
            print("Warning: failed to copy annotations to temporary dir; will attempt in-place commit to data branch")

        # Shell sequence: delete local 'data' if present, create orphan, clear index, populate annotations, commit, push force
        orphan_script = f"""
        set -e
        if git rev-parse --verify data >/dev/null 2>&1; then
          git branch -D data || true
        fi
        git checkout --orphan data
        git rm -rf --quiet . || true
        mkdir -p annotations
        if [ -d \"{tmpdir}\" ]; then
          cp -r {tmpdir}/* annotations/ || true
        else
          # Fallback: copy from current repo annotations (might already be present)
          cp -r annotations/* annotations/ || true
        fi
        git add -f annotations || true
        if git diff --cached --quiet; then
          echo \"No data changes to commit.\"
          git checkout main || true
          git reset --hard origin/main || true
          exit 0
        fi
        git commit -m "{commit_msg.replace('"', '\\"')}"
        git push --force origin data
        git checkout main || true
        git reset --hard origin/main || true
        """
        rc3, out3, err3 = run_cmd(["bash", "-lc", orphan_script], cwd=repo_dir)
        print(f"orphan branch push rc={rc3}\n{out3}\n{err3}")
        commit_ok = (rc3 == 0)
    else:
        print("No annotation changes to commit (possibly duplicates)")
        # treat as OK to close issues (parser produced no new changes)
        commit_ok = True

    # Comment and close successes only if commit/push succeeded
    if commit_ok:
        for s in successes:
            num = s["number"]
            try:
                comment_issue(num, COMMENT_BODY_SUCCESS)
                add_label(num, ["recorded"])
                close_issue(num)
                print(f"Closed issue #{num}")
            except Exception as e:
                print(f"Failed to comment/close issue #{num}: {e}")
    else:
        print("Commit/push failed; skipping closing successful issues to avoid data loss.")

    # For failures, post failure comments with error output
    for f in failures:
        try:
            comment_issue(f["number"], COMMENT_BODY_FAILURE + "\n\nError output:\n```\n" + f["error"] + "\n```")
            print(f"Posted failure comment for issue #{f['number']}")
        except Exception as e:
            print(f"Failed to post failure comment for issue #{f['number']}: {e}")


if __name__ == "__main__":
    main()
