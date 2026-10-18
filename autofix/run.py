"""The auto-fix job: Claude teaches the bot its failed messages, in a pull request.

Run on the Pi by .github/workflows/autofix.yml (needs GH_TOKEN and
CLAUDE_CODE_OAUTH_TOKEN). Each run:

1. Settles pull requests from earlier runs: merged → their wrong results are
   fixed (not-understood ones were closed on startup if the fix worked, and
   are retried if not); closed without merging → ignored.
2. Answers new comments from the owner on open auto-fix pull requests.
3. If the admin has new open failed messages, has Claude fix what it can,
   opens a pull request, and answers the automatic review (up to two rounds).
4. Links the fixed entries to the pull request; ignores the unfixable ones.

Claude never holds the GitHub token. It works in a sandbox container
(autofix/Dockerfile: no Docker socket, only a temporary work folder) on an
anonymous clone of this public repository, and hands back its commits as a
git bundle. A separate container with the token, which runs neither Claude
nor any code from the repository, fetches the bundle into a fresh clone and
pushes it. So nothing Claude writes (or runs, like its tests) can merge.

The failed messages are private and the Actions log is public: nothing here
prints them, and Claude's output goes to a log file on the Pi only.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

from datetime import datetime
from pathlib  import Path

BOT = "roman-tech-bot-bot-1"
IMAGE = "roman-tech-bot-autofix"
REPO = "qetlife/roman-tech-bot"
CLONE_URL = f"https://github.com/{REPO}.git"
LABEL = "autofix"
BRANCH = re.compile(r"^autofix/[0-9-]+$")
# Replies the job posts start with this, so they don't count as new comments.
MARKER = "🤖 auto-fix:"
# Comments from anyone else on this public repo are ignored: they could be instructions.
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
REVIEWER = "github-actions"
REVIEW_ROUNDS = 2
HERE = Path(__file__).resolve().parent
LOGS = Path.home() / "autofix-logs"
KEEP_LOGS = 30
TIMEOUT = 40 * 60           # one Claude run
DEADLINE = 120 * 60         # no new Claude run after this (+ 40 min for the last one); the workflow allows 180
STARTED = time.monotonic()
running = None              # the Claude container, killed if the job is cancelled

# Claude has no GitHub token, so these can only touch its own clone.
ALLOWED_TOOLS = ",".join([
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(git:*)", "Bash(python -m pytest:*)", "Bash(python -m pyflakes:*)",
])


# --- the bot and GitHub -----------------------------------------------------

def failed(*args) -> str:
    """scripts/failed.py in the bot container."""
    return subprocess.run(
        ["docker", "exec", BOT, "python", "scripts/failed.py", *map(str, args)],
        check=True, capture_output=True, text=True,
    ).stdout


def open_entries() -> list:
    return [json.loads(line) for line in failed("list", "--admin").splitlines()]


def with_token(*args, work: Path = None) -> str:
    """Run a command in the sandbox with GH_TOKEN (never Claude, never code from the repo)."""
    mount = ["-v", f"{work}:/work"] if work else []
    return subprocess.run(
        ["docker", "run", "--rm", "-e", "GH_TOKEN", *mount, IMAGE, *args],
        check=True, capture_output=True, text=True,
    ).stdout


def gh_json(*args):
    return json.loads(with_token("gh", *args))


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


def new_comments(number: int, reviewer: bool) -> list:
    """Comments on a pull request newer than its last commit and the job's last reply.

    Only from the owner, and from the automatic review if `reviewer`.
    """
    pr = gh_json("pr", "view", str(number), "--repo", REPO, "--json", "commits,comments")
    pages = gh_json("api", "--paginate", "--slurp", f"repos/{REPO}/pulls/{number}/comments?per_page=100")
    inline = [c for page in pages for c in page]
    comments = [
        {"author": c["author"]["login"], "association": c["authorAssociation"],
         "created_at": c["createdAt"], "body": c["body"]}
        for c in pr["comments"]
    ] + [
        {"author": c["user"]["login"], "association": c["author_association"], "created_at": c["created_at"],
         "path": c["path"], "line": c.get("line") or c.get("original_line"), "body": c["body"]}
        for c in inline
    ]
    handled = max([c["committedDate"] for c in pr["commits"]] +
                  [c["created_at"] for c in comments if c["body"].startswith(MARKER)])
    return [
        c for c in comments
        if c["created_at"] > handled and not c["body"].startswith(MARKER)
        and (c["association"] in TRUSTED or (reviewer and c["author"].startswith(REVIEWER)))
    ]


def needs_answer(comments: list) -> bool:
    """Anything besides the review's summary (a comment on the code, or from the owner)."""
    return any("path" in c or c["association"] in TRUSTED for c in comments)


def wait_for_review(branch: str):
    """Until the "Claude review" run for the branch's latest push has finished."""
    head = with_token("git", "ls-remote", CLONE_URL, f"refs/heads/{branch}").split()[0]
    for _ in range(60):
        runs = gh_json("run", "list", "--repo", REPO, "--workflow", "review.yml", "--branch", branch,
                       "--json", "databaseId,headSha,status")
        run = next((r for r in runs if r["headSha"] == head), None)
        if run and run["status"] == "completed":
            return
        time.sleep(30)
    print("The review didn't finish in 30 minutes")


# --- Claude, without the token ----------------------------------------------

def time_left() -> bool:
    return time.monotonic() - STARTED < DEADLINE


def on_cancel(signum, frame):
    """Actions cancels with SIGTERM/SIGINT; killing `docker run` would leave the container running."""
    if running:
        subprocess.run(["docker", "kill", running], capture_output=True)
    sys.exit(1)


def run_claude(work: Path, task: str, branch: str, start: str, log: Path) -> dict:
    """Claude does `task` on `branch` (created from `start`); returns its result.json.

    Its new commits are left in /work/out.bundle.
    """
    global running
    (work / "task.md").write_text(task)
    (work / "result.json").unlink(missing_ok=True)
    (work / "out.bundle").unlink(missing_ok=True)
    script = (
        f"rm -rf /work/repo && git clone -q {CLONE_URL} /work/repo && cd /work/repo"
        f" && git checkout -q -B '{branch}' 'origin/{start}'"
        f" && claude -p \"$(cat /work/prompt.md /work/task.md)\" --add-dir /work"
        f" --permission-mode acceptEdits --allowedTools '{ALLOWED_TOOLS}'"
        f"; git bundle create /work/out.bundle 'origin/{start}..{branch}' 2>/dev/null"
    )
    name = running = f"autofix-{datetime.now():%Y%m%d%H%M%S}"
    with open(log, "a") as out:
        try:
            subprocess.run(
                ["docker", "run", "--rm", "--name", name, "-e", "CLAUDE_CODE_OAUTH_TOKEN",
                 "-v", f"{work}:/work", IMAGE, "bash", "-c", script],
                stdout=out, stderr=subprocess.STDOUT, timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            # Killing `docker run` leaves the container running.
            subprocess.run(["docker", "kill", name], capture_output=True)
            print(f"Claude timed out after {TIMEOUT // 60} min")
        finally:
            running = None
    path = work / "result.json"
    try:
        result = json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        result = {}
    return result if isinstance(result, dict) else {}


def ids(items, known: set) -> list:
    """The ids in `items` (Claude's output) that are entries we gave it."""
    return [i for i in items if type(i) is int and i in known] if isinstance(items, list) else []


def publish(work: Path, branch: str) -> bool:
    """Push Claude's commits (the bundle) to `branch`, from a fresh clone. False if there are none."""
    if not BRANCH.match(branch) or not (work / "out.bundle").exists():
        return False
    with_token("bash", "-c",
               f"git clone -q {CLONE_URL} /tmp/repo && cd /tmp/repo"
               f" && git fetch -q /work/out.bundle '{branch}:{branch}' && git push -q origin '{branch}'",
               work=work)
    return True


def answer_comments(work: Path, number: int, branch: str, comments: list, log: Path):
    """Claude addresses comments on a pull request; the job pushes and replies."""
    (work / "comments.json").write_text(json.dumps(comments, ensure_ascii=False, indent=1))
    result = run_claude(work, (
        f"\n\n## Task\n\nAddress the comments on pull request #{number} (`/work/comments.json`). "
        f"You're on its branch `{branch}`. Write `/work/result.json` as "
        '`{"reply": "..."}`: one reply covering each comment, saying what you changed or why it '
        "isn't a problem.\n"
    ), branch, branch, log)
    pushed = publish(work, branch)
    reply = str(result.get("reply") or ("Pushed changes for the comments." if pushed else "No changes."))
    (work / "reply.md").write_text(f"{MARKER} {reply}")
    with_token("gh", "pr", "comment", str(number), "--repo", REPO, "--body-file", "/work/reply.md", work=work)
    print(f"Pull request #{number}: answered {len(comments)} comments" + (", pushed" if pushed else ""))


def fix_new(work: Path, new: list, log: Path):
    """Claude fixes the new failed messages; the job opens the pull request and links them."""
    with open(work / "failed.jsonl", "w") as f:
        for entry in new:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    branch = f"autofix/{datetime.now():%Y-%m-%d-%H%M}"
    result = run_claude(work, (
        "\n\n## Task\n\nTeach the bot the failed messages in `/work/failed.jsonl`. "
        f"You're on the new branch `{branch}`. Write `/work/result.json` as described above.\n"
    ), branch, "master", log)

    known = {e["id"] for e in new}
    ignored = result.get("ignored")
    ignored = [i for i in ignored if isinstance(i, dict) and ids([i.get("id")], known)] if isinstance(ignored, list) else []
    for item in ignored:
        # The note is Claude's, short; it must not quote the message.
        failed("ignore", item["id"], str(item.get("note") or "unfixable")[:200])

    fixed = [i for i in ids(result.get("fixed"), known) if i not in {item["id"] for item in ignored}]
    if not fixed or not publish(work, branch):
        print(f"No pull request; ignored {len(ignored)}")
        return

    (work / "body.md").write_text(str(result.get("body") or ""))
    url = with_token("gh", "pr", "create", "--repo", REPO, "--base", "master", "--head", branch,
                     "--label", LABEL, "--title", str(result.get("title") or f"Learn {len(fixed)} failed messages"),
                     "--body-file", "/work/body.md", work=work).strip()
    number = int(url.rstrip("/").rsplit("/", 1)[-1])
    for entry_id in fixed:
        failed("pr", entry_id, number)
    print(f"Opened pull request #{number}: {len(fixed)} fixed, {len(ignored)} ignored")

    for _ in range(REVIEW_ROUNDS):
        if not time_left():
            print("Out of time; the review is answered on the next run")
            break
        wait_for_review(branch)
        comments = new_comments(number, reviewer=True)
        if not needs_answer(comments):
            break   # only the review's summary: nothing on the code
        if not time_left():
            print("Out of time; the review is answered on the next run")
            break
        answer_comments(work, number, branch, comments, log)


def main() -> int:
    signal.signal(signal.SIGTERM, on_cancel)
    signal.signal(signal.SIGINT, on_cancel)
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
    commented = []
    for pr in gh_json("pr", "list", "--repo", REPO, "--label", LABEL, "--state", "open",
                      "--json", "number,headRefName"):
        # The review's too: a run may have stopped before answering it.
        comments = new_comments(pr["number"], reviewer=True)
        if needs_answer(comments) and BRANCH.match(pr["headRefName"]):
            commented.append((pr["number"], pr["headRefName"], comments))
    new = [e for e in open_entries() if not e["fix_pr"]]
    print(f"New failed messages: {len(new)}; auto-fix pull requests with new comments: "
          f"{[n for n, _, _ in commented] or 'none'}")
    if not new and not commented:
        return 0

    LOGS.mkdir(exist_ok=True)
    log = LOGS / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    with tempfile.TemporaryDirectory(prefix="autofix-") as tmp:
        work = Path(tmp)
        (work / "prompt.md").write_text((HERE / "prompt.md").read_text())
        for number, branch, comments in commented:
            if time_left():
                answer_comments(work, number, branch, comments, log)
        if new and time_left():
            fix_new(work, new, log)
    print(f"Claude's log on the Pi: {log}")

    for old in sorted(LOGS.glob("*.log"))[:-KEEP_LOGS]:
        old.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
