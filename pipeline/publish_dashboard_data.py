"""Publish ONLY approved generated bundles on a fresh remote-main checkout.

Never stage, commit, reset, merge, or stash the operational checkout. A remote
race fails without force-pushing; re-running starts from the new remote HEAD.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile

ALLOWED = {"dashboard/model-lab-data.js", "dashboard/model-review-data.js"}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()


def publish(root: Path, paths: list[str], message: str, execute: bool = False) -> str:
    if not paths or set(paths) - ALLOWED:
        raise ValueError("Only explicitly approved dashboard data bundles may be published")
    payloads = {name: (root / name).read_bytes() for name in paths}
    if any(not value for value in payloads.values()):
        raise ValueError("Refusing an empty dashboard bundle")
    remote = git(root, "remote", "get-url", "origin")
    with tempfile.TemporaryDirectory(prefix="futscout-publish-") as folder:
        checkout = Path(folder)
        git(checkout, "init", "-q")
        git(checkout, "remote", "add", "origin", remote)
        git(checkout, "fetch", "--depth=1", "origin", "main")
        git(checkout, "checkout", "--detach", "FETCH_HEAD")
        for name, data in payloads.items():
            if not (checkout / name).is_file():
                raise ValueError(f"Remote does not contain approved bundle: {name}")
            (checkout / name).write_bytes(data)
        git(checkout, "add", "--", *paths)
        changed = git(checkout, "diff", "--cached", "--name-only").splitlines()
        if not changed:
            return "unchanged"
        if set(changed) - set(paths):
            raise RuntimeError("Unexpected publication changes")
        if not execute:
            return "dry-run: " + ", ".join(changed)
        for setting in ("user.name", "user.email"):
            git(checkout, "config", setting, git(root, "config", setting))
        git(checkout, "commit", "-m", message)
        commit = git(checkout, "rev-parse", "HEAD")
        git(checkout, "push", "origin", "HEAD:refs/heads/main")
        return commit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(publish(Path(__file__).resolve().parents[1], args.file, args.message, args.execute))


if __name__ == "__main__":
    main()
