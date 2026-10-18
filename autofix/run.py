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
TIMEOUT = 80 * 60
# Comments from anyone else on this public repo are ignored: they could be instructions.
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")

# No `gh pr merge` and no `gh api`: Claude can open and comment on pull
# requests but never merge one (every merge deploys).
ALLOWED_TOOLS = ",".join([
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(git:*)", "Bash(python -m pytest:*)", "Bash(python -m pyflakes:*)",
    "Bash(gh pr create:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)", "Bash(gh pr diff:*)",
    "Bash(gh pr comment:*)", "Bash(gh run list:*)", "Bash(gh run watch:*)", "Bash(review-comments:*)",
])


def failed(*args) -> str:
    """scripts/failed.py in the bot container."""
    return subprocess.run(
        ["docker", "exec", BOT, "python", "scripts/failed.py", *map(str, args)],
        check=True, capture_output=True, text=True,
    ).stdout


def open_entries() -> list:
    return [json.loads(line) for line in failed("list", "--admin").splitlines()]


def sandbox(*args, work: Path = None, name: str = None) -> list:
    """`docker run` of the sandbox; the tokens are passed by name, so they aren't on the command line."""
    extra = (["-v", f"{work}:/work"] if work else []) + (["--name", name] if name else [])
    return ["docker", "run", "--rm", "-e", "GH_TOKEN", "-e", "CLAUDE_CODE_OAUTH_TOKEN", *extra, IMAGE, *args]


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
    """Open auto-fix pull requests with trusted comments Claude hasn't dealt with yet.

    Dealt with: older than the last commit or than Claude's last reply. The
    review's own comments are answered in the run that pushed.
    """
    prs = gh_json("pr", "list", "--repo", REPO, "--label", LABEL, "--state", "open",
                  "--json", "number,commits,comments")
    waiting = []
    for pr in prs:
        inline = gh_json("api", f"repos/{REPO}/pulls/{pr['number']}/comments")
        comments = [(c["createdAt"], c["body"], c["authorAssociation"]) for c in pr["comments"]] + \
                   [(c["created_at"], c["body"], c["author_association"]) for c in inline]
        handled = max([c["committedDate"] for c in pr["commits"]] +
                      [when for when, body, _ in comments if body.startswith(MARKER)])
        if any(when > handled and not body.startswith(MARKER) and association in TRUSTED
               for when, body, association in comments):
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
    name = f"autofix-{datetime.now():%Y%m%d%H%M%S}"
    with open(log, "w") as out:
        try:
            result = subprocess.run(
                sandbox("bash", "-c", script, work=work, name=name),
                stdout=out, stderr=subprocess.STDOUT, timeout=TIMEOUT,
            )
            print(f"Claude finished with exit code {result.returncode} (log on the Pi: {log})")
        except subprocess.TimeoutExpired:
            # Killing `docker run` leaves the container running; stop it, then keep what it wrote.
            subprocess.run(["docker", "kill", name], capture_output=True)
            print(f"Claude timed out after {TIMEOUT // 60} min (log on the Pi: {log})")
    # Claude writes it as soon as the pull request exists, so a timeout doesn't lose it.
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
