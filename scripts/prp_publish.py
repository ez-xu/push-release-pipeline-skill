#!/usr/bin/env python3
"""Tagging, release publication, read-back verification, and rollback.

Publication is treated as a transaction: if any step fails, or if the read-back
check finds that the published artifact is not the artifact that was built, the
local tag, the remote tag, and the release are removed again so the next push
starts from a consistent state.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Sequence

from prp_repo import PrpError, run

# Provider CLIs print update notices on stderr; nothing here parses stderr for
# success, so that noise is captured and shown rather than interpreted.


def detect_provider(remote_url: str) -> str:
    """Classify the hosting provider from a git remote URL."""
    lowered = remote_url.lower()
    if "github.com" in lowered:
        return "github"
    return "gitlab"


def cli_for(provider: str) -> str:
    return "gh" if provider == "github" else "glab"


def cli_path(provider: str) -> str | None:
    """Absolute path of the provider CLI, or None when it is not installed.

    shutil.which is PATHEXT-aware but CreateProcess is not. Invoking the bare name
    "glab" makes Windows search for glab.exe only, so on a machine where glab is a
    .cmd or .bat shim -- the normal case for scoop, npm and chocolatey installs --
    detection would find the shim while execution silently ran a different binary.
    Resolving once and invoking the absolute path keeps both looking at one program.
    """
    return shutil.which(cli_for(provider))


def require_cli(provider: str) -> str:
    """Fail early, and return the resolved executable, rather than after a build."""
    resolved = cli_path(provider)
    if resolved is None:
        raise PrpError(
            "the "
            + provider
            + " release CLI '"
            + cli_for(provider)
            + "' is not on PATH; install it and authenticate before pushing"
        )
    return resolved


def contract_health(provider: str, repo: Path) -> dict:
    """Load the registered release_api contract and run its health check.

    The contract is loaded by path rather than by name so the vendored copy inside
    .ci/lib and the copy shipped with the skill are both found, in that order.
    """
    import importlib.util

    here = Path(__file__).resolve().parent
    candidates = [
        here / "contract_health.py",
        here.parent / "contracts" / "data_contract_release_api" / "code" / "contract_health.py",
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location("prp_contract_health", candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.report(provider=provider, repo=str(repo))
    raise PrpError(
        "the release_api data contract is missing; expected contract_health.py next to "
        "the vendored modules or under contracts/data_contract_release_api/code/"
    )


def require_contract(provider: str, repo: Path) -> dict:
    """Stop before the build when the release interface cannot be verified against.

    Publishing without a working download path would break the closed-loop
    standard, so this is a refusal rather than a warning.
    """
    health = contract_health(provider, repo)
    if not health.get("usable"):
        failed = ", ".join(
            check["name"] for check in health.get("checks", []) if not check.get("ok")
        )
        raise PrpError(
            "the " + provider + " release interface is not ready (" + failed + "). "
            "The pipeline will not publish what it cannot verify."
        )
    return health


def auth_check(provider: str, repo: Path) -> tuple[bool, str]:
    """Report whether the provider CLI is authenticated. Never raises."""
    cli = cli_path(provider) or cli_for(provider)
    proc = run([cli, "auth", "status"], cwd=repo, timeout=120)
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, text


def create_local_tag(repo: Path, tag: str, commit: str, message: str) -> None:
    """Create an annotated tag at an explicit commit.

    Annotated, not lightweight: the tag message carries the provenance that makes
    the commit-to-artifact binding auditable later.
    """
    proc = run(["git", "tag", "-a", tag, "-m", message, commit], cwd=repo, timeout=120)
    if proc.returncode != 0:
        raise PrpError(
            "could not create tag " + tag + ": " + ((proc.stderr or proc.stdout or "").strip())
        )


def delete_local_tag(repo: Path, tag: str, log: list[str]) -> int:
    proc = run(["git", "tag", "-d", tag], cwd=repo, timeout=120)
    log.append(
        "[rollback] git tag -d " + tag + " -> " + str(proc.returncode) + " "
        + ((proc.stderr or proc.stdout or "").strip())
    )
    return proc.returncode


def push_tag(repo: Path, remote: str, tag: str, log: list[str]) -> None:
    """Push one tag, with the recursion guard set so the hook does not re-enter."""
    proc = run(
        ["git", "push", remote, "refs/tags/" + tag],
        cwd=repo,
        timeout=600,
        env={"PRP_IN_PROGRESS": "1"},
    )
    if proc.stdout:
        log.append(proc.stdout.rstrip())
    if proc.stderr:
        log.append(proc.stderr.rstrip())
    if proc.returncode != 0:
        raise PrpError("could not push tag " + tag + " to " + remote)


def delete_remote_tag(repo: Path, remote: str, tag: str, log: list[str]) -> int:
    proc = run(
        ["git", "push", remote, ":refs/tags/" + tag],
        cwd=repo,
        timeout=600,
        env={"PRP_IN_PROGRESS": "1"},
    )
    log.append(
        "[rollback] delete remote tag " + tag + " -> " + str(proc.returncode) + " "
        + ((proc.stderr or proc.stdout or "").strip())
    )
    return proc.returncode


def create_release(
    provider: str,
    repo: Path,
    *,
    tag: str,
    commit: str,
    artifact: Path,
    release_name: str,
    notes_file: Path,
    log: list[str],
) -> None:
    """Create the release, pinning it to the commit that was actually built.

    Both CLIs will happily invent a tag when the one named does not exist, and
    GitLab resolves that invented tag from the repository default branch. The
    explicit ref and the verify flag remove that possibility: the release can only
    ever point at the commit this pipeline built.
    """
    cli = require_cli(provider)
    if provider == "github":
        argv = [
            cli, "release", "create", tag, str(artifact),
            "--title", release_name,
            "--notes-file", str(notes_file),
            "--verify-tag",
        ]
    else:
        argv = [
            cli, "release", "create", tag, str(artifact),
            "--name", release_name,
            "--notes-file", str(notes_file),
            "--ref", commit,
            "--no-update",
        ]
    log.append("$ " + " ".join(argv))
    proc = run(argv, cwd=repo, timeout=1800, env={"PRP_IN_PROGRESS": "1"})
    if proc.stdout:
        log.append(proc.stdout.rstrip())
    if proc.stderr:
        log.append(proc.stderr.rstrip())
    if proc.returncode != 0:
        raise PrpError("release creation failed for " + tag)


def delete_release(provider: str, repo: Path, tag: str, log: list[str]) -> int:
    argv = [cli_path(provider) or cli_for(provider), "release", "delete", tag, "--yes"]
    proc = run(argv, cwd=repo, timeout=600, env={"PRP_IN_PROGRESS": "1"})
    log.append(
        "[rollback] release delete " + tag + " -> " + str(proc.returncode) + " "
        + ((proc.stderr or proc.stdout or "").strip())
    )
    return proc.returncode


def download_asset(
    provider: str,
    repo: Path,
    *,
    tag: str,
    asset_name: str,
    dest_dir: Path,
    log: list[str],
) -> Path:
    """Download one named asset from a published release into dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cli = require_cli(provider)
    if provider == "github":
        argv = [cli, "release", "download", tag, "--pattern", asset_name,
                "--dir", str(dest_dir), "--clobber"]
    else:
        argv = [cli, "release", "download", tag, "--asset-name", asset_name,
                "--dir", str(dest_dir)]
    log.append("$ " + " ".join(argv))
    proc = run(argv, cwd=repo, timeout=1800, env={"PRP_IN_PROGRESS": "1"})
    if proc.stdout:
        log.append(proc.stdout.rstrip())
    if proc.stderr:
        log.append(proc.stderr.rstrip())
    if proc.returncode != 0:
        raise PrpError("could not download asset " + asset_name + " from release " + tag)
    candidate = dest_dir / asset_name
    if candidate.is_file():
        return candidate
    matches = sorted(p for p in dest_dir.rglob(asset_name) if p.is_file())
    if not matches:
        matches = sorted(p for p in dest_dir.rglob("*") if p.is_file())
    if not matches:
        raise PrpError("release " + tag + " yielded no downloadable asset named " + asset_name)
    return matches[0]


def rollback(
    repo: Path,
    remote: str,
    tag: str,
    provider: str,
    *,
    release_created: bool,
    tag_pushed: bool,
    log: list[str],
) -> list[str]:
    """Undo everything this run created. Returns the remediation steps that failed.

    Failure is judged from each command's exit code, never from its text: the
    transcript line carries the command's own output after the code, so matching on
    the text would report a false "clean up by hand" for every successful step and
    train the reader to ignore the warning.
    """
    problems: list[str] = []
    if release_created and delete_release(provider, repo, tag, log) != 0:
        problems.append("delete the release " + tag + " by hand")
    if tag_pushed and delete_remote_tag(repo, remote, tag, log) != 0:
        problems.append("delete the remote tag " + tag + " by hand")
    if delete_local_tag(repo, tag, log) != 0:
        problems.append("delete the local tag " + tag + " by hand")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Diagnostic entry point: report the provider CLI and its auth state."""
    import argparse

    parser = argparse.ArgumentParser(description="Check the release CLI for a remote.")
    parser.add_argument("--url", required=True, help="git remote URL")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    provider = detect_provider(args.url)
    try:
        resolved = require_cli(provider)
    except PrpError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    ok, text = auth_check(provider, Path(args.repo))
    print("provider: " + provider)
    print("cli: " + resolved)
    print("authenticated: " + ("yes" if ok else "no"))
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
