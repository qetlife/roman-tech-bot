"""The auto-fix job: Claude teaches the bot its failed messages, in a pull request.

Run on the Pi by .github/workflows/autofix.yml (needs GH_TOKEN and
CLAUDE_CODE_OAUTH_TOKEN). Each run:

1. Settles pull requests from earlier runs: merged → their wrong results are
   fixed (not-understood ones were closed on startup if the fix worked, and
   are retried if not); closed without merging → ignored.
2. If the admin has new open failed messages, or someone commented on an open
   auto-fix pull request, runs Claude in a sandbox container (autofix/Dockerfile:
   no Docker socket, only a temporary work folder) with autofix/prompt.md.
3. Applies its result: links the fixed entries to the pull request, ignores
   the unfixable ones.

The failed messages are private and the Actions log is public: nothing here
prints them, and Claude's output goes to a log file on the Pi only.
"""

import json
import os
import subprocess
import sys
import tempfile

from datetime import datetime
from pathlib  import Path

BOT = "roman-tech-bot-bot-1"
IMAGE = "roman-tech-bot-autofix"
REPO = "qetlife/roman-tech-bot"
LABEL = "autofix"
# Claude's replies on pull requests start with this, so they don't count as new comments.
MARKER = "🤖 auto-fix:"
HERE = Path(__file__).resolve().parent
LOGS = Path.home() / "autofix-logs"
KEEP_LOGS = 30

ALLOWED_TOOLS = ",".join([
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(git:*)", "Bash(gh:*)", "Bash(python -m pytest:*)", "Bash(python -m pyflakes:*)",
])


def failed(*args) -> str:
    """scripts/failed.py in the bot container."""
    return subprocess.run(
        ["docker", "exec", BOT, "python", "scripts/failed.py", *map(str, args)],
        check=True, capture_output=True, text=True,
    ).stdout


def open_entries() -> list:
    return [json.loads(line) for line in failed("list", "--admin").splitlines()]


def sandbox(*args, work: Path = None) -> list:
    """`docker run` of the sandbox; the tokens are passed by name, so they aren't on the command line."""
    mount = ["-v", f"{work}:/work"] if work else []
    return ["docker", "run", "--rm", "-e", "GH_TOKEN", "-e", "CLAUDE_CODE_OAUTH_TOKEN", *mount, IMAGE, *args]


def gh_json(*args):
    return json.loads(subprocess.run(sandbox("gh", *args), check=True, capture_output=True, text=True).stdout)


def settle_earlier_prs(entries: list):
    for pr in sorted({e["fix_pr"] for e in entries if e["fix_pr"]}):
        state = gh_json("pr", "view", str(pr), "--repo", REPO, "--json", "state")["state"]
        for entry in (e for e in entries if e["fix_pr"] == pr):
            if state == "MERGED" and entry["reason"] == "wrong_result":
                failed("fixed", entry["id"], f"fixed by pull request #{pr}")
            elif state == "MERGED":
                # Still not understood after the deploy: the fix didn't cover it.
                failed("pr", entry["id"], "none")
            elif state == "CLOSED":
                failed("ignore", entry["id"], f"pull request #{pr} closed without merging")
        print(f"Pull request #{pr}: {state.lower()}")


def prs_with_new_comments() -> list:
    """Open auto-fix pull requests with comments (other than Claude's) after their last commit."""
    prs = gh_json("pr", "list", "--repo", REPO, "--label", LABEL, "--state", "open",
                  "--json", "number,commits,comments")
    waiting = []
    for pr in prs:
        last_commit = max(c["committedDate"] for c in pr["commits"])
        inline = gh_json("api", f"repos/{REPO}/pulls/{pr['number']}/comments")
        comments = [(c["createdAt"], c["body"], c["author"]["login"]) for c in pr["comments"]] + \
                   [(c["created_at"], c["body"], c["user"]["login"]) for c in inline]
        # The review's own comments are answered in the run that pushed.
        if any(when > last_commit and not body.startswith(MARKER) and not author.startswith("github-actions")
               for when, body, author in comments):
            waiting.append(pr["number"])
    return waiting


def run_claude(new: list, work: Path, log: Path) -> dict:
    with open(work / "failed.jsonl", "w") as f:
        for entry in new:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    prompt = (HERE / "prompt.md").read_text() + (
        f"\n\nStart replies to pull request comments with “{MARKER}”.\n"
    )
    (work / "prompt.md").write_text(prompt)

    script = (
        f"gh repo clone {REPO} /work/repo -- -q && cd /work/repo && "
        f"claude -p \"$(cat /work/prompt.md)\" --add-dir /work --permission-mode acceptEdits "
        f"--allowedTools '{ALLOWED_TOOLS}'"
    )
    with open(log, "w") as out:
        result = subprocess.run(
            sandbox("bash", "-c", script, work=work), stdout=out, stderr=subprocess.STDOUT, timeout=80 * 60,
        )
    print(f"Claude finished with exit code {result.returncode} (log on the Pi: {log})")
    path = work / "result.json"
    return json.loads(path.read_text()) if path.exists() else {}


def apply_result(result: dict, new: list):
    known = {e["id"] for e in new}
    pr = result.get("pr")
    for entry_id in result.get("fixed", []):
        if pr and entry_id in known:
            failed("pr", entry_id, pr)
    for item in result.get("ignored", []):
        if item.get("id") in known:
            # The note is Claude's, short; it must not quote the message.
            failed("ignore", item["id"], str(item.get("note") or "unfixable")[:200])
    print(f"Pull request: {('#' + str(pr)) if pr else 'none'}; "
          f"fixed {len(result.get('fixed', []))}, ignored {len(result.get('ignored', []))}")


def main() -> int:
    for name in ("GH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        if not os.environ.get(name):
            print(f"{name} isn't set", file=sys.stderr)
            return 1

    subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE, "-f", str(HERE / "Dockerfile"),
         "--build-arg", f"UID={os.getuid()}", str(HERE.parent)],
        check=True, stdout=subprocess.DEVNULL,
    )

    settle_earlier_prs(open_entries())
    new = [e for e in open_entries() if not e["fix_pr"]]
    commented = prs_with_new_comments()
    print(f"New failed messages: {len(new)}; auto-fix pull requests with new comments: {commented or 'none'}")
    if not new and not commented:
        return 0

    LOGS.mkdir(exist_ok=True)
    log = LOGS / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    with tempfile.TemporaryDirectory(prefix="autofix-") as tmp:
        work = Path(tmp)
        result = run_claude(new, work, log)
    apply_result(result, new)

    for old in sorted(LOGS.glob("*.log"))[:-KEEP_LOGS]:
        old.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
