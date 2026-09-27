#!/usr/bin/env python3
"""Tagging, release publication, read-back verification, and rollback.

Publication is treated as a transaction: if any step fails, or if the read-back
check finds that the published artifact is not the artifact that was built, the
local tag, the remote tag, and the release are removed again so the next push
starts from a consistent state.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from prp_repo import PrpError, remote_url, run

# The GitLab CLI records the uploaded file's link URL as
# https://<host>/-/project/<id>/uploads/<secret>/<name> -- the project namespace is
# missing, so the URL 404s. GitLab's own asset download route redirects to exactly
# that URL, which is why the asset is unreachable for every consumer.
_UPLOAD_LINK_RE = re.compile(
    r"^(?P<base>https?://[^/]+)/-/project/(?P<project_id>\d+)/uploads/"
    r"(?P<secret>[^/]+)/(?P<name>[^/?#]+)$"
)

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
    remote: str = "origin",
    extra_assets: Sequence[Path] = (),
) -> None:
    """Create the release, pinning it to the commit that was actually built.

    Both CLIs will happily invent a tag when the one named does not exist, and
    GitLab resolves that invented tag from the repository default branch. The
    explicit ref and the verify flag remove that possibility: the release can only
    ever point at the commit this pipeline built.

    extra_assets ride along in the same release as further positional files: a firmware
    release often ships the raw image and a flashing-ready hex, and keeping them on one
    release leaves a consumer a single place to look.
    """
    cli = require_cli(provider)
    files = [str(artifact)] + [str(path) for path in extra_assets]
    if provider == "github":
        argv = [
            cli, "release", "create", tag, *files,
            "--title", release_name,
            "--notes-file", str(notes_file),
            "--verify-tag",
        ]
    else:
        argv = [
            cli, "release", "create", tag, *files,
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
    repair_asset_link(
        provider, repo, remote=remote, tag=tag,
        asset_names=[artifact.name] + [path.name for path in extra_assets], log=log,
    )


def web_base_and_path(remote_url_value: str) -> tuple[str, str] | None:
    """Split a git remote URL into (https base, repository path).

    Handles the forms git actually stores: https://host/group/project.git,
    ssh://git@host/group/project.git and the scp-like git@host:group/project.git.
    Returns None for anything that is not a hosted remote (for example a local path),
    so callers leave their link untouched instead of inventing a host from it.

    Shared by the GitLab and GitHub link builders so both accept the same forms.
    """
    value = (remote_url_value or "").strip()
    if not value:
        return None
    if "://" not in value:
        head, _, path = value.partition(":")
        # The scp-like form is user@host:path. Without the "@" this is a local path
        # (on Windows even C:\repo looks like it has a host), so refuse rather than
        # invent a host from it.
        if "@" not in head:
            return None
        base = "https://" + head.split("@")[-1]
    else:
        _, _, rest = value.partition("://")
        host, _, path = rest.split("@")[-1].partition("/")
        if not host:
            return None
        base = "https://" + host
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if "/" not in path:
        return None
    return base, path


def gitlab_project(remote_url_value: str) -> tuple[str, str] | None:
    """(web base, url-encoded project path) for a hosted remote, else None."""
    split = web_base_and_path(remote_url_value)
    if split is None:
        return None
    base, path = split
    return base, quote(path, safe="")


def github_slug(remote_url_value: str) -> str | None:
    """owner/repo when the remote is on github.com, else None."""
    split = web_base_and_path(remote_url_value)
    if split is None:
        return None
    base, path = split
    host = base[len("https://"):].lower()
    if host not in ("github.com", "www.github.com"):
        return None
    return path


def release_urls(
    provider: str,
    repo: Path,
    remote: str,
    tag: str,
    asset_name: str,
) -> dict[str, str]:
    """The two links worth handing to a human: the release page and the file itself.

    Derived from the remote with no API call, so the identical pair can be printed for
    a release that was just published and for one being re-verified later, and so the
    links cost nothing on a run that already talked to the provider. An empty mapping
    means this remote has no link shape we can build - the caller then prints nothing
    rather than a URL that 404s.
    """
    url = remote_url(repo, remote)
    quoted_tag = quote(tag, safe="")
    quoted_asset = quote(asset_name, safe="/")
    if provider == "gitlab":
        # The browser route wants the real slashes: gitlab_project() returns the API
        # form (percent-encoded project path) and is for the REST calls only.
        split = web_base_and_path(url)
        if split is None:
            return {}
        base, path = split
        page = base + "/" + path + "/-/releases/" + quoted_tag
        return {
            "releaseUrl": page,
            "assetUrl": page + "/downloads/" + quoted_asset,
        }
    if provider == "github":
        slug = github_slug(url)
        if slug is None:
            return {}
        page = "https://github.com/" + slug + "/releases/tag/" + quoted_tag
        return {
            "releaseUrl": page,
            "assetUrl": (
                "https://github.com/" + slug
                + "/releases/download/" + quoted_tag + "/" + quoted_asset
            ),
        }
    return {}


def release_asset_names(
    provider: str, repo: Path, remote: str, tag: str, log: list[str]
) -> list[str]:
    """Names of the assets attached to a published release, as the provider lists them.

    A re-check of an older release has to name the asset that release actually holds: it may
    have been published by another clone on another day, so the name cannot be taken from
    whatever the local build tree happens to contain now. An empty list means the release
    could not be read (unknown tag, no access, unparseable answer) - the caller says so
    instead of inventing a name.
    """
    url = remote_url(repo, remote)
    cli = require_cli(provider)
    if provider == "gitlab":
        project = gitlab_project(url)
        if project is None:
            return []
        _, encoded = project
        proc = run(
            [cli, "api", "projects/" + encoded + "/releases/" + quote(tag, safe="")],
            cwd=repo, timeout=300, env={"PRP_IN_PROGRESS": "1"},
        )
        if proc.returncode != 0:
            if proc.stderr:
                log.append("[assets] " + proc.stderr.strip()[:200])
            return []
        try:
            data = json.loads(proc.stdout or "{}")
        except ValueError:
            return []
        links = (data.get("assets") or {}).get("links") or []
        return [str(link["name"]) for link in links if link.get("name")]
    slug = github_slug(url)
    if slug is None:
        return []
    proc = run(
        [cli, "api", "repos/" + slug + "/releases/tags/" + quote(tag, safe="")],
        cwd=repo, timeout=300, env={"PRP_IN_PROGRESS": "1"},
    )
    if proc.returncode != 0:
        if proc.stderr:
            log.append("[assets] " + proc.stderr.strip()[:200])
        return []
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return []
    return [str(asset["name"]) for asset in (data.get("assets") or []) if asset.get("name")]


def repair_asset_link(
    provider: str,
    repo: Path,
    *,
    remote: str,
    tag: str,
    asset_names: Sequence[str],
    log: list[str],
) -> None:
    """Give every published asset a URL that can be downloaded.

    The GitLab CLI uploads the files correctly but records each link URL without the
    project namespace, and GitLab's asset download route redirects to exactly that
    URL -- so the asset 404s for every consumer, and for this pipeline's own
    read-back. Rewriting the link to the API uploads route keeps the uploaded bytes
    and makes both the browser that clicks the release asset and the read-back see
    the file. Left unchanged when a URL already resolves.

    Every name is repaired, not just the first: a release that ships a raw image and a
    hex would otherwise leave the second file unreachable for everyone.
    """
    if provider != "gitlab":
        return
    project = gitlab_project(remote_url(repo, remote))
    if project is None:
        log.append("[link] remote is not a GitLab URL; asset link left as created")
        return
    base, encoded = project
    cli = require_cli(provider)
    release_arg = "projects/" + encoded + "/releases/" + quote(tag, safe="")
    listing = run([cli, "api", release_arg], cwd=repo, timeout=300, env={"PRP_IN_PROGRESS": "1"})
    if listing.returncode != 0:
        log.append("[link] could not read the release back to inspect the asset URL")
        return
    try:
        release = json.loads(listing.stdout or "{}")
    except ValueError:
        log.append("[link] the release listing was not JSON; asset URL left unchanged")
        return
    links = (release.get("assets") or {}).get("links") or []
    wanted = {str(name) for name in asset_names}
    inspected = 0
    for link in links:
        if str(link.get("name")) not in wanted:
            continue
        inspected += 1
        match = _UPLOAD_LINK_RE.match(str(link.get("url") or ""))
        if match is None:
            log.append("[link] asset URL needs no repair: " + str(link.get("url")))
            continue
        fixed = (
            base
            + "/api/v4/projects/"
            + match["project_id"]
            + "/uploads/"
            + match["secret"]
            + "/"
            + match["name"]
        )
        argv = [
            cli, "api", "--method", "PUT",
            release_arg + "/assets/links/" + str(link.get("id")),
            "-f", "url=" + fixed,
            "-f", "direct_asset_path=/" + match["name"],
        ]
        log.append("$ " + " ".join(argv))
        proc = run(argv, cwd=repo, timeout=300, env={"PRP_IN_PROGRESS": "1"})
        if proc.returncode != 0:
            if proc.stderr:
                log.append(proc.stderr.rstrip())
            raise PrpError(
                "could not point the release asset " + str(link.get("name"))
                + " at a downloadable URL"
            )
        log.append("[link] asset URL repaired -> " + fixed)
    if not inspected:
        log.append("[link] no asset link named " + ", ".join(sorted(wanted)) + " to inspect")


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
