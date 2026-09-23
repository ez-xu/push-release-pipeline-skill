#!/usr/bin/env python3
"""Git plumbing and identity snapshots for the push-release pipeline.

Every fact this module reports is read from git at call time. Nothing is cached
across a build, because the whole point of the pipeline is to compare the
repository's identity before and after compiling.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class PrpError(RuntimeError):
    """A gate or external command failed; the caller must abort the release."""


def run(
    cmd: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, capturing merged output as text. Never raises on exit code."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        return subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd) if cwd is not None else None,
            env=full_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise PrpError("command not found: " + str(cmd[0])) from exc
    except subprocess.TimeoutExpired as exc:
        raise PrpError(
            "command timed out after " + str(timeout) + "s: " + " ".join(map(str, cmd))
        ) from exc


def git(repo: Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    """Run git in the given repository and return stripped stdout."""
    proc = run(["git", *args], cwd=repo, timeout=timeout)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise PrpError("git " + " ".join(args) + " failed (" + str(proc.returncode) + "): " + detail)
    return proc.stdout.strip()


def repo_root(start: Path | str | None = None) -> Path:
    """Resolve the work-tree root using git itself.

    The hook runs under MSYS bash on Windows, where git rev-parse returns a POSIX
    path such as /c/Users/... that native Python cannot open. Calling git from
    Python avoids that entirely: git.exe hands back a native path.
    """
    base = Path(start) if start is not None else Path.cwd()
    proc = run(["git", "rev-parse", "--show-toplevel"], cwd=base, timeout=60)
    if proc.returncode != 0:
        raise PrpError("not a git work tree: " + str(base))
    return Path(proc.stdout.strip())


def is_dirty(repo: Path) -> list[str]:
    """Return porcelain status lines; empty means a clean work tree."""
    out = git(repo, "status", "--porcelain=v1", "--untracked-files=normal")
    return [line for line in out.splitlines() if line.strip()]


def head_commit(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def head_tree(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD^{tree}")


def branch_name(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def tracked_paths(repo: Path) -> list[str]:
    """Every tracked path, relative to the work-tree root."""
    proc = run(["git", "ls-files", "-z"], cwd=repo, timeout=180)
    if proc.returncode != 0:
        raise PrpError("git ls-files failed")
    return sorted(p for p in proc.stdout.split("\0") if p)


def tracked_manifest(repo: Path) -> str:
    """SHA-256 over the staged content of every tracked path.

    git ls-files -s reports mode, blob SHA, and stage for each path, so this
    digest changes if any tracked file's content changes, if a file is added or
    removed, or if its executable bit changes.
    """
    proc = run(["git", "ls-files", "-s", "-z"], cwd=repo, timeout=180)
    if proc.returncode != 0:
        raise PrpError("git ls-files -s failed")
    digest = hashlib.sha256()
    for entry in proc.stdout.split("\0"):
        if entry:
            digest.update(entry.encode("utf-8", "surrogateescape"))
            digest.update(b"\n")
    return digest.hexdigest()


@dataclass
class Snapshot:
    """The repository's identity at one instant."""

    head: str
    tree: str
    manifest: str
    status: list[str]
    taken_at: float

    def as_dict(self) -> dict:
        return {
            "head": self.head,
            "tree": self.tree,
            "manifest": self.manifest,
            "status": list(self.status),
            "taken_at": self.taken_at,
        }

    def differences(self, other: "Snapshot") -> list[str]:
        """Human-readable list of every identity field that changed."""
        out: list[str] = []
        if self.head != other.head:
            out.append("HEAD moved: " + self.head[:12] + " -> " + other.head[:12])
        if self.tree != other.tree:
            out.append("HEAD tree changed: " + self.tree[:12] + " -> " + other.tree[:12])
        if self.manifest != other.manifest:
            out.append(
                "tracked-file manifest changed: "
                + self.manifest[:12]
                + " -> "
                + other.manifest[:12]
            )
        if self.status != other.status:
            added = [line for line in other.status if line not in self.status]
            removed = [line for line in self.status if line not in other.status]
            if added:
                out.append("work tree became dirty: " + "; ".join(added[:10]))
            if removed:
                out.append("work tree entries disappeared: " + "; ".join(removed[:10]))
        return out


def take_snapshot(repo: Path) -> Snapshot:
    """Freeze HEAD, tree, tracked manifest, and work-tree status."""
    return Snapshot(
        head=head_commit(repo),
        tree=head_tree(repo),
        manifest=tracked_manifest(repo),
        status=is_dirty(repo),
        taken_at=time.time(),
    )


def mtime_snapshot(repo: Path, paths: Sequence[str]) -> dict[str, int]:
    """Record each tracked path's modification time, in nanoseconds."""
    out: dict[str, int] = {}
    for rel in paths:
        try:
            out[rel] = (repo / rel).stat().st_mtime_ns
        except OSError:
            out[rel] = -1
    return out


def changed_mtimes(repo: Path, before: Mapping[str, int]) -> list[str]:
    """Tracked paths whose modification time changed since the snapshot.

    A build that rewrites a tracked file with byte-identical content leaves the
    content manifest unchanged, so the manifest alone cannot prove the tree was
    untouched. Comparing against a snapshot taken immediately before the build
    detects exactly that, and unlike a wall-clock threshold it cannot report a
    false positive for a file that merely happened to be saved a moment earlier.
    """
    hits: list[str] = []
    for rel, prior in before.items():
        try:
            now = (repo / rel).stat().st_mtime_ns
        except OSError:
            hits.append(rel)
            continue
        if now != prior:
            hits.append(rel)
    return hits


def resolve_tag_commit(repo: Path, tag: str) -> str | None:
    """Commit a local tag points at, dereferencing annotated tags.

    git rev-parse on an annotated tag returns the tag object id, not the commit.
    Comparing that against HEAD is always false, so the commit dereference is
    mandatory here.
    """
    proc = run(
        ["git", "rev-parse", "--verify", "--quiet", tag + "^{commit}"], cwd=repo, timeout=60
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def tag_exists_local(repo: Path, tag: str) -> bool:
    proc = run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/tags/" + tag], cwd=repo, timeout=60
    )
    return proc.returncode == 0


def remote_tag_commit(repo: Path, remote: str, tag: str) -> str | None:
    """Commit a tag points at on the remote, dereferencing annotated tags.

    git ls-remote --tags prints two lines for an annotated tag: the tag object and
    a peeled line carrying the commit. Only the peeled line is the commit.
    """
    proc = run(
        [
            "git",
            "ls-remote",
            "--tags",
            remote,
            "refs/tags/" + tag,
            "refs/tags/" + tag + "^{}",
        ],
        cwd=repo,
        timeout=180,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise PrpError("git ls-remote failed: " + detail)
    peeled: str | None = None
    direct: str | None = None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref.endswith("^{}"):
            peeled = sha
        elif ref == "refs/tags/" + tag:
            direct = sha
    return peeled or direct


def remote_exists(repo: Path, remote: str) -> bool:
    proc = run(["git", "remote", "get-url", remote], cwd=repo, timeout=60)
    return proc.returncode == 0


def remote_url(repo: Path, remote: str) -> str:
    return git(repo, "remote", "get-url", remote)


def remote_branch_commit(repo: Path, remote: str, branch: str) -> str | None:
    proc = run(
        ["git", "ls-remote", "--heads", remote, "refs/heads/" + branch], cwd=repo, timeout=180
    )
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "refs/heads/" + branch:
            return parts[0]
    return None


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def short(sha: str | None, width: int = 12) -> str:
    return sha[:width] if sha else "(none)"


def main(argv: Sequence[str] | None = None) -> int:
    """Diagnostic entry point: print the current identity snapshot as JSON."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Print a repository identity snapshot.")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    try:
        root = repo_root(args.repo)
        snap = take_snapshot(root)
    except PrpError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"repo": str(root), **snap.as_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
