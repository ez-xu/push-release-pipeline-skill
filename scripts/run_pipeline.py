#!/usr/bin/env python3
"""Single entry point for the push-release pipeline.

Subcommands:
  setup           adopt the pipeline into a repository (probe, config, vendor, hook)
  check           read-only readiness report; changes nothing
  release         the pipeline itself: gate, build, verify, tag, publish, read back
  verify          re-run the read-back check against an already published release
  install-hook    install the vendored pre-push hook into .git/hooks
  uninstall-hook  remove it again

The pipeline is designed so that the failure mode it prevents -- a published tag
whose artifact came from a different tree -- cannot happen silently. Every gate
refuses rather than proceeds, and every refusal names the exact repair.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

# Set before importing the sibling modules below. Importing them would otherwise
# create .ci/lib/__pycache__, which dirties the work tree the pipeline is about to
# check -- so the pipeline would refuse the very push that triggered it.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prp_build import (  # noqa: E402
    build_env,
    clean_outputs,
    embedded_version,
    resolve_artifact,
    run_step,
    toolchain_tokens,
)
from prp_publish import (  # noqa: E402
    auth_check,
    cli_for,
    contract_health,
    create_local_tag,
    create_release,
    detect_provider,
    download_asset,
    push_tag,
    require_cli,
    require_contract,
    rollback,
)
from prp_repo import (  # noqa: E402
    PrpError,
    branch_name,
    changed_mtimes,
    mtime_snapshot,
    remote_branch_commit,
    remote_exists,
    remote_tag_commit,
    remote_url,
    repo_root,
    resolve_tag_commit,
    sha256_file,
    short,
    take_snapshot,
    tag_exists_local,
    tracked_paths,
)
from prp_setup import (  # noqa: E402
    CONFIG_REL,
    HOOK_REL,
    IGNORE_ENTRIES,
    LOCAL_CONFIG_REL,
    OUTPUT_REL,
    default_config,
    ensure_gitignore,
    install_hook,
    is_ignored,
    load_config,
    probe,
    propose_config,
    save_config,
    save_local_config,
    uninstall_hook,
    validate_config,
    vendor_lib,
    write_hook,
)

SKILL_NAME = "push-release-pipeline-skill"


def _tolerant_console() -> None:
    """Stop a narrow console code page from turning a report into a crash.

    Windows consoles and pipes default to a legacy code page such as cp936 or
    cp1252, and the text this pipeline prints includes output captured from git
    and from the release CLI. glab's help and status output carries characters
    such as a check mark, so printing a readiness report to such a stream raised
    UnicodeEncodeError and hid the very message that explained the state of the
    pipeline. Replacing the unencodable characters keeps the report readable.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


class Refused(Exception):
    """A gate refused to proceed. Nothing was published; the fix is named."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _render(template: str, tokens: Mapping[str, str]) -> str:
    out = str(template)
    for key, value in tokens.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _record(event: str, started: float) -> None:
    """Best-effort lifecycle recording. Never turns success into failure."""
    try:
        from success_ledger import record_event

        record_event(
            event,
            skill=SKILL_NAME,
            run_id=os.environ.get("ASC_RUN_ID"),
            duration_seconds=time.monotonic() - started,
        )
    except Exception as exc:  # noqa: BLE001 - measurement must never break the pipeline
        print("warning: could not record lifecycle event: " + str(exc), file=sys.stderr)


class Run:
    """Mutable state for one pipeline invocation."""

    def __init__(self, repo: Path, config: Mapping[str, Any]) -> None:
        self.repo = repo
        self.config = config
        self.log: list[str] = []
        self.steps: list[dict[str, str]] = []
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.out_dir = repo / str(config.get("outputDir", OUTPUT_REL)) / stamp
        self.started = time.monotonic()

    def step(self, name: str, status: str, detail: str = "") -> None:
        self.steps.append({"name": name, "status": status, "detail": detail})
        marker = {"pass": "  [ok]  ", "fail": " [FAIL] ", "skip": " [skip] "}.get(
            status, "  [--]  "
        )
        line = marker + name + (("  " + detail) if detail else "")
        print(line)
        self.log.append(line)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _notes_markdown(run: Run, info: Mapping[str, Any]) -> str:
    lines = [
        "# " + str(info["tag"]),
        "",
        "- Project: " + str(info["project"]),
        "- Commit: " + str(info["commit"]),
        "- Tree: " + str(info["tree"]),
        "- Branch: " + str(info["branch"]),
        "- Artifact: " + str(info["artifactName"]),
        "- Artifact SHA-256: " + str(info["sha256"]),
        "- Bytes: " + str(info["size"]),
        "- Version source: " + str(info["versionSource"]),
        "- Built at: " + str(info["builtAt"]),
        "",
        "## Provenance",
        "",
        "This artifact was produced by a clean build from commit " + str(info["commit"]) + ".",
        "The tracked-file manifest, HEAD, and work-tree status were identical before and after",
        "the build, and no tracked file was written during the build window.",
        "",
        "The version was read back out of the produced artifact rather than recomputed, so the",
        "tag cannot disagree with the binary it names.",
        "",
        "## Closed-loop verification",
        "",
        "After publication the pipeline re-read the remote tag and downloaded this asset back:",
        "",
        "- remote tag commit: " + str(info.get("readBackCommit", "(not run)")),
        "- downloaded SHA-256: " + str(info.get("readBackSha256", "(not run)")),
        "- verdict: " + str(info.get("readBackVerdict", "(not run)")),
        "",
    ]
    return "\n".join(lines)


def _save_outputs(run: Run, info: Mapping[str, Any]) -> None:
    run.out_dir.mkdir(parents=True, exist_ok=True)
    _write(run.out_dir / "build.log", "\n".join(run.log) + "\n")
    _write(run.out_dir / "release-notes.md", _notes_markdown(run, info))
    _write(
        run.out_dir / "manifest.json",
        json.dumps({"skill": SKILL_NAME, "generatedAt": _now(), "steps": run.steps, **info},
                   indent=2, ensure_ascii=False) + "\n",
    )


# --------------------------------------------------------------------------- setup


def cmd_setup(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    print("repo: " + str(repo))
    facts = probe(repo)
    config, notes, local = propose_config(facts)

    config_path = repo / CONFIG_REL
    if config_path.is_file() and not args.force:
        print("config already exists at " + str(config_path) + " (use --force to overwrite)")
        config = load_config(repo)
    else:
        save_config(repo, config)
        print("wrote " + str(config_path))

    if local:
        local_path = save_local_config(repo, local)
        print("wrote " + str(local_path) + "  (machine-local, git-ignored, never committed)")

    print("")
    print("Detected:")
    for line in notes:
        print("  - " + line)
    problems = validate_config(config, repo)
    if problems:
        print("")
        print("Config still needs attention before the first release:")
        for problem in problems:
            print("  ! " + problem)

    source_dir = Path(__file__).resolve().parent
    copied = vendor_lib(repo, source_dir)
    print("")
    print("Vendored " + str(len(copied)) + " module(s) into " + str(repo / ".ci/lib"))
    hook = write_hook(repo, sys.executable)
    print("Wrote " + str(hook.relative_to(repo)))
    for entry in IGNORE_ENTRIES:
        if ensure_gitignore(repo, entry):
            print("Added " + entry + " to .gitignore")

    if args.install_hook:
        log: list[str] = []
        target = install_hook(repo, log)
        print("Installed pre-push hook at " + str(target))
    else:
        print("")
        print("Hook not installed yet. Review the config, then run:")
        print("  python " + str(repo / ".ci/lib/run_pipeline.py") + " install-hook --repo " + str(repo))
    print("")
    print("Dry run the pipeline with:")
    print("  python " + str(repo / ".ci/lib/run_pipeline.py") + " release --repo " + str(repo) + " --dry-run")
    return 0


def cmd_install_hook(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    log: list[str] = []
    target = install_hook(repo, log)
    for line in log:
        print(line)
    print("Installed pre-push hook at " + str(target))
    return 0


def cmd_uninstall_hook(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    log: list[str] = []
    if uninstall_hook(repo, log):
        for line in log:
            print(line)
        return 0
    print("no push-release-pipeline hook was installed")
    return 0


# --------------------------------------------------------------------------- check


def cmd_check(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"generatedAt": _now()}
    try:
        repo = repo_root(args.repo)
        config = load_config(repo)
    except PrpError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    report["repo"] = str(repo)
    report["configPath"] = str(repo / CONFIG_REL)
    report["configProblems"] = validate_config(config, repo)
    report["localConfigPath"] = str(repo / LOCAL_CONFIG_REL)
    report["localConfigPresent"] = (repo / LOCAL_CONFIG_REL).is_file()
    try:
        report["toolchain"] = toolchain_tokens(repo)
    except PrpError as exc:
        report["toolchain"] = {}
        report["toolchainError"] = str(exc)
    url = remote_url(repo, str(config.get("remote", "origin")))
    provider = detect_provider(url)
    report["remoteUrl"] = url
    report["provider"] = provider
    report["branch"] = branch_name(repo)
    report["releaseBranch"] = (config.get("project") or {}).get("releaseBranch")
    report["outputIgnored"] = is_ignored(repo, str(config.get("outputDir", OUTPUT_REL)))
    try:
        require_cli(provider)
        ok, text = auth_check(provider, repo)
        report["releaseCli"] = cli_for(provider)
        report["releaseCliAuthenticated"] = ok
        report["releaseCliAuthDetail"] = text.splitlines()[:6]
    except PrpError as exc:
        report["releaseCli"] = None
        report["releaseCliError"] = str(exc)
    try:
        report["releaseContract"] = contract_health(provider, repo)
    except PrpError as exc:
        report["releaseContract"] = {"usable": False, "error": str(exc)}
    try:
        snap = take_snapshot(repo)
        report["clean"] = not snap.status
        report["dirtyEntries"] = snap.status[:20]
        report["head"] = snap.head
        report["tree"] = snap.tree
    except PrpError as exc:
        report["clean"] = None
        report["snapshotError"] = str(exc)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("repo:            " + report["repo"])
    print("branch:          " + str(report["branch"]) + "  (release branch: "
          + str(report["releaseBranch"]) + ")")
    print("remote:          " + report["remoteUrl"] + "  -> " + provider)
    print("release cli:     " + str(report.get("releaseCli"))
          + "  authenticated: " + str(report.get("releaseCliAuthenticated")))
    contract = report.get("releaseContract") or {}
    print("release contract:" + " usable: " + str(contract.get("usable"))
          + "  " + str(contract.get("interface", contract.get("error", ""))))
    print("output ignored:  " + str(report["outputIgnored"]))
    print("local overlay:   " + str(report["localConfigPresent"])
          + "  (" + report["localConfigPath"] + ")")
    resolved = report.get("toolchain") or {}
    print("toolchain:       "
          + (", ".join(key + "=" + str(value) for key, value in sorted(resolved.items()))
             or "unresolved; see config problems below"))
    print("work tree clean: " + str(report["clean"]))
    if report["configProblems"]:
        print("config problems:")
        for problem in report["configProblems"]:
            print("  ! " + problem)
    return 0


# --------------------------------------------------------------------------- release


def cmd_release(args: argparse.Namespace) -> int:
    if os.environ.get("PRP_IN_PROGRESS") == "1":
        return 0
    repo = repo_root(args.repo)
    config = load_config(repo)
    run = Run(repo, config)
    problems = validate_config(config, repo)
    if problems:
        raise Refused("config is not releasable: " + "; ".join(problems))

    remote = args.remote or str(config.get("remote", "origin"))
    provider_cfg = str((config.get("release") or {}).get("provider", "auto"))
    if not remote_exists(repo, remote):
        raise Refused("remote " + repr(remote) + " does not exist in " + str(repo))
    url = remote_url(repo, remote)
    provider = detect_provider(url) if provider_cfg in ("auto", "") else provider_cfg
    require_cli(provider)
    health = require_contract(provider, repo)
    run.step(
        "release interface",
        "pass",
        provider + ": " + str(len(health.get("checks", []))) + " readiness checks passed",
    )

    release_branch = str((config.get("project") or {}).get("releaseBranch"))
    branch = branch_name(repo)
    if branch != release_branch and not args.any_branch:
        raise Refused(
            "on branch " + repr(branch) + " but the release branch is " + repr(release_branch)
            + "; pass --any-branch to release from here anyway"
        )
    run.step("preconditions", "pass", branch + " -> " + provider + " via " + cli_for(provider))

    output_dir = str(config.get("outputDir", OUTPUT_REL))
    if not is_ignored(repo, output_dir):
        raise Refused(
            output_dir + " is not git-ignored, so pipeline output would dirty the tree and "
            "trip the drift guard. Add " + output_dir.rstrip("/") + "/ to .gitignore."
        )

    dirty = take_snapshot(repo).status
    if dirty:
        raise Refused(
            "work tree is not clean; a release built from a dirty tree cannot be traced to a "
            "commit. Commit or stash first:\n  " + "\n  ".join(dirty[:15])
        )
    run.step("clean tree", "pass", "no uncommitted changes")

    # A fresh clone carries no shadow build directory, and a missing working
    # directory fails the run before qmake ever gets a chance to create it.
    fresh_cwd = repo / str((config.get("build") or {}).get("cwd", "."))
    if not fresh_cwd.exists():
        fresh_cwd.mkdir(parents=True, exist_ok=True)
        run.log.append("[build] created missing build directory " + str(fresh_cwd))

    guard = config.get("guard") or {}
    mutable = [str(p) for p in (guard.get("mutableTrackedPaths") or [])]

    before = take_snapshot(repo)
    run.step("identity snapshot (before)", "pass", "HEAD " + short(before.head))
    paths = tracked_paths(repo)

    build_cfg = config.get("build") or {}
    timeout = int(build_cfg.get("timeoutSeconds", 3600))
    build_cwd = repo / str(build_cfg.get("cwd", "."))
    build_start = time.time()
    mtimes_before = mtime_snapshot(repo, paths)
    build_cfg_path = repo / CONFIG_REL
    local_cfg_path = repo / LOCAL_CONFIG_REL
    config_before = build_cfg_path.read_bytes() if build_cfg_path.is_file() else b""
    local_before = local_cfg_path.read_bytes() if local_cfg_path.is_file() else b""
    run.log.append("build window opened at " + _now())
    try:
        clean_outputs(build_cfg.get("clean") or [], repo, run.log)
        step_env = build_env(build_cfg.get("env"), repo)
        run_step("configure", build_cfg.get("configure"), repo=repo, cwd=build_cwd,
                 log_lines=run.log, timeout=timeout, env=step_env)
        run_step("build", build_cfg.get("build"), repo=repo, cwd=build_cwd,
                 log_lines=run.log, timeout=timeout, env=step_env)
    except PrpError as exc:
        run.step("clean build", "fail", "the build did not succeed")
        run.out_dir.mkdir(parents=True, exist_ok=True)
        _write(run.out_dir / "build.log", "\n".join(run.log) + "\n")
        raise
    elapsed = time.time() - build_start
    run.step("clean build", "pass", str(int(elapsed)) + "s")

    after = take_snapshot(repo)
    drift = before.differences(after)
    if drift:
        raise Refused(
            "the repository changed while it was being built, so the artifact cannot be tied "
            "to commit " + short(before.head) + ":\n  " + "\n  ".join(drift)
        )
    run.step("identity snapshot (after)", "pass", "identical to before the build")

    touched = [p for p in changed_mtimes(repo, mtimes_before) if p not in mutable]
    if touched:
        raise Refused(
            str(len(touched)) + " tracked file(s) were written during the build window, which "
            "means the tag and the artifact could disagree. If the build is supposed to "
            "regenerate one of these, list it in guard.mutableTrackedPaths:\n  "
            + "\n  ".join(touched[:20])
        )
    if mutable:
        run.step("time guard", "pass",
                 "no tracked file written (allow-listed: " + ", ".join(mutable) + ")")
    else:
        run.step("time guard", "pass", "no tracked file was written during the build")

    if build_cfg_path.is_file() and build_cfg_path.read_bytes() != config_before:
        raise Refused("the build rewrote " + CONFIG_REL + ", so the run is not reproducible")
    if local_cfg_path.is_file() and local_cfg_path.read_bytes() != local_before:
        raise Refused(
            "the build rewrote " + LOCAL_CONFIG_REL + ", so the toolchain the artifact was "
            "built with cannot be assumed to be the one this run started with"
        )
    run.step("config stability", "pass",
             CONFIG_REL + " and " + LOCAL_CONFIG_REL + " unchanged by the build")

    artifact_cfg = config.get("artifact") or {}
    artifact, version = resolve_artifact(artifact_cfg, repo)
    run.step("artifact located", "pass", artifact.name + " -> version " + version)

    embedded, note = embedded_version(artifact, artifact_cfg, repo)
    if embedded is not None and embedded != version:
        raise Refused(
            "version mismatch: the file name says " + version + " but the binary itself says "
            + embedded + " (" + note + "). Publishing this would put a tag on a binary that "
            "disagrees with it."
        )
    if embedded is None:
        run.step("version cross-check", "skip", note)
    else:
        run.step("version cross-check", "pass", note)

    project_name = str((config.get("project") or {}).get("name", ""))
    tokens = {
        "version": version,
        "project": project_name,
        "artifactName": artifact.name,
        "commit": before.head,
        "branch": branch,
    }
    tag = _render(str((config.get("tag") or {}).get("template", "V{version}")), tokens)
    tokens["tag"] = tag

    local_commit = resolve_tag_commit(repo, tag) if tag_exists_local(repo, tag) else None
    remote_commit = remote_tag_commit(repo, remote, tag)
    if local_commit or remote_commit:
        at_head = {local_commit, remote_commit} == {before.head}
        if at_head:
            run.step("tag occupancy", "skip", tag + " already exists at this commit")
            _save_outputs(run, {
                "project": project_name,
                "tag": tag, "version": version, "commit": before.head, "tree": before.tree,
                "branch": branch, "artifact": str(artifact), "artifactName": artifact.name,
                "sha256": sha256_file(artifact), "size": artifact.stat().st_size,
                "versionSource": note, "builtAt": _now(), "published": False,
                "reason": "tag already published for this commit",
                "readBackVerdict": "not run (nothing new was published)",
            })
            print("")
            print(tag + " already points at " + short(before.head) + "; nothing to publish.")
            return 0
        raise Refused(
            "tag " + tag + " already exists at a different commit (local "
            + short(local_commit) + ", remote " + short(remote_commit) + "), but this build is "
            "from " + short(before.head) + ". A published tag is never moved. Raise the version "
            "in the build system and push again."
        )
    run.step("tag occupancy", "pass", tag + " is free")

    sha = sha256_file(artifact)
    run.step("artifact hash", "pass", sha[:16] + "...  " + str(artifact.stat().st_size) + " bytes")

    if args.dry_run:
        run.step("publish", "skip", "dry run: nothing was tagged, pushed, or released")
        _save_outputs(run, {
            "project": project_name,
            "tag": tag, "version": version, "commit": before.head, "tree": before.tree,
            "branch": branch, "artifact": str(artifact), "artifactName": artifact.name,
            "sha256": sha, "size": artifact.stat().st_size, "versionSource": note,
            "builtAt": _now(), "published": False, "dryRun": True,
            "readBackVerdict": "not run (dry run)",
        })
        print("")
        print("Dry run complete. Would tag " + tag + " at " + short(before.head)
              + " and publish " + artifact.name + " to " + provider + ".")
        print("Output: " + str(run.out_dir))
        return 0

    info: dict[str, Any] = {
        "project": project_name,
        "tag": tag, "version": version, "commit": before.head, "tree": before.tree,
        "branch": branch, "artifact": str(artifact), "artifactName": artifact.name,
        "sha256": sha, "size": artifact.stat().st_size, "versionSource": note,
        "builtAt": _now(), "published": False,
    }

    tag_pushed = False
    release_created = False
    try:
        if not local_commit:
            create_local_tag(
                repo, tag, before.head,
                "Release " + tag + "\n\ncommit " + before.head + "\ntree " + before.tree
                + "\nartifact " + artifact.name + "\nsha256 " + sha,
            )
            run.step("create tag", "pass", tag + " -> " + short(before.head))
        else:
            run.step("create tag", "skip", tag + " already exists locally at this commit")

        push_tag(repo, remote, tag, run.log)
        tag_pushed = True
        run.step("push tag", "pass", "refs/tags/" + tag + " -> " + remote)

        landed = remote_tag_commit(repo, remote, tag)
        if landed != before.head:
            raise PrpError(
                "the tag landed on " + short(landed) + " but this build is from "
                + short(before.head)
            )
        run.step("remote tag check", "pass", "remote tag resolves to " + short(landed))

        notes_file = run.out_dir / "release-notes.md"
        run.out_dir.mkdir(parents=True, exist_ok=True)
        _write(notes_file, _notes_markdown(run, info))
        create_release(
            provider, repo, tag=tag, commit=before.head, artifact=artifact,
            release_name=_render(
                str((config.get("release") or {}).get("name", "{tag}")), tokens
            ),
            notes_file=notes_file, log=run.log, remote=remote,
        )
        release_created = True
        run.step("create release", "pass", tag + " on " + provider)

        verify_cfg = config.get("verify") or {}
        if verify_cfg.get("readBack", True):
            verdict, detail, extra = _read_back(
                run, provider, repo, remote, tag, before.head, artifact, sha
            )
            info.update(extra)
            if verdict != "pass":
                raise PrpError(detail)
            run.step("closed-loop read-back", "pass", detail)
        else:
            run.step("closed-loop read-back", "skip", "verify.readBack is false")
            info["readBackVerdict"] = "disabled by config"
    except Exception as exc:  # noqa: BLE001 - a partial publication must always roll back
        run.step("publish", "fail", str(exc).splitlines()[0][:160])
        problems: list[str] = []
        if (config.get("verify") or {}).get("rollbackOnFailure", True):
            print("")
            print("Rolling back the partial publication ...")
            problems = rollback(
                repo, remote, tag, provider,
                release_created=release_created, tag_pushed=tag_pushed, log=run.log,
            )
            run.step("rollback", "pass" if not problems else "fail",
                     "tag and release removed" if not problems else "manual cleanup needed")
        else:
            run.step("rollback", "skip", "verify.rollbackOnFailure is false")
        info["published"] = False
        info["failure"] = type(exc).__name__ + ": " + str(exc)
        info["rollbackProblems"] = problems
        try:
            _save_outputs(run, info)
        except OSError as save_exc:
            print("warning: could not write the run record: " + str(save_exc), file=sys.stderr)
        print("")
        print("Release FAILED: " + str(exc))
        if problems:
            print("The following rollback steps did not report success; clean up by hand:")
            for problem in problems:
                print("  ! " + problem)
        print("Output: " + str(run.out_dir))
        return 1

    info["published"] = True
    _save_outputs(run, info)
    print("")
    print("Released " + tag + " from " + short(before.head) + " with " + artifact.name)
    print("  sha256 " + sha)
    print("  output " + str(run.out_dir))
    return 0


def _read_back(
    run: Run,
    provider: str,
    repo: Path,
    remote: str,
    tag: str,
    commit: str,
    artifact: Path,
    sha: str,
) -> tuple[str, str, dict[str, Any]]:
    """Re-read what was actually published and compare it to what was built.

    This is the closed-loop standard: the release is only successful if the remote
    tag still resolves to the commit that was built, and the asset that a consumer
    would download is byte-identical to the locally built artifact.
    """
    extra: dict[str, Any] = {}
    landed = remote_tag_commit(repo, remote, tag)
    extra["readBackCommit"] = landed
    if landed != commit:
        extra["readBackVerdict"] = "fail (remote tag commit differs)"
        return (
            "fail",
            "read-back failed: remote tag " + tag + " resolves to " + short(landed)
            + " but this build is from " + short(commit),
            extra,
        )

    dest = run.out_dir / "readback"
    last = ""
    for attempt in range(1, 6):
        try:
            fetched = download_asset(
                provider, repo, tag=tag, asset_name=artifact.name, dest_dir=dest, log=run.log
            )
            break
        except PrpError as exc:
            last = str(exc)
            if attempt == 5:
                extra["readBackVerdict"] = "fail (asset could not be downloaded)"
                return "fail", "read-back failed: " + last, extra
            time.sleep(3 * attempt)
    else:  # pragma: no cover - loop always breaks or returns
        return "fail", "read-back failed: " + last, extra

    fetched_sha = sha256_file(fetched)
    extra["readBackSha256"] = fetched_sha
    extra["readBackPath"] = str(fetched)
    if fetched_sha != sha:
        extra["readBackVerdict"] = "fail (published bytes differ from the build)"
        return (
            "fail",
            "read-back failed: the published asset hashes to " + fetched_sha[:16]
            + "... but the build produced " + sha[:16] + "...",
            extra,
        )
    extra["readBackVerdict"] = "pass"
    return (
        "pass",
        "remote tag -> " + short(landed) + "; downloaded asset matches the build byte for byte",
        extra,
    )


# --------------------------------------------------------------------------- verify


def cmd_verify(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    config = load_config(repo)
    run = Run(repo, config)
    remote = args.remote or str(config.get("remote", "origin"))
    provider = detect_provider(remote_url(repo, remote))
    require_cli(provider)
    artifact_cfg = config.get("artifact") or {}
    artifact, version = resolve_artifact(artifact_cfg, repo)
    tag = args.tag or _render(
        str((config.get("tag") or {}).get("template", "V{version}")),
        {"version": version, "artifactName": artifact.name},
    )
    commit = args.commit or resolve_tag_commit(repo, tag) or ""
    sha = sha256_file(artifact)
    verdict, detail, extra = _read_back(
        run, provider, repo, remote, tag, commit, artifact, sha
    )
    run.step("closed-loop read-back", "pass" if verdict == "pass" else "fail", detail)
    _save_outputs(run, {
        "tag": tag, "version": version, "commit": commit, "artifact": str(artifact),
        "artifactName": artifact.name, "sha256": sha, "builtAt": _now(),
        "published": True, **extra,
    })
    print("")
    print(detail)
    return 0 if verdict == "pass" else 1


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="Integrity-gated, push-triggered release pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="adopt the pipeline into a repository")
    setup.add_argument("--repo", default=".")
    setup.add_argument("--force", action="store_true", help="overwrite an existing config")
    setup.add_argument("--install-hook", action="store_true", help="install the pre-push hook")
    setup.set_defaults(func=cmd_setup)

    check = sub.add_parser("check", help="read-only readiness report")
    check.add_argument("--repo", default=".")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

    release = sub.add_parser("release", help="run the release pipeline")
    release.add_argument("--repo", default=".")
    release.add_argument("--remote", default=None)
    release.add_argument("--dry-run", action="store_true")
    release.add_argument("--any-branch", action="store_true")
    release.add_argument("--triggered-by-hook", action="store_true")
    release.set_defaults(func=cmd_release)

    verify = sub.add_parser("verify", help="re-run the read-back check on a published release")
    verify.add_argument("--repo", default=".")
    verify.add_argument("--remote", default=None)
    verify.add_argument("--tag", default=None)
    verify.add_argument("--commit", default=None)
    verify.set_defaults(func=cmd_verify)

    install = sub.add_parser("install-hook", help="install the vendored pre-push hook")
    install.add_argument("--repo", default=".")
    install.set_defaults(func=cmd_install_hook)

    uninstall = sub.add_parser("uninstall-hook", help="remove the pre-push hook")
    uninstall.add_argument("--repo", default=".")
    uninstall.set_defaults(func=cmd_uninstall_hook)
    return parser


def _hook_blocks_push(args: argparse.Namespace) -> bool:
    """Whether a failed pipeline should also abort the push that triggered it.

    hook.mode "release" (the default) lets the branch push through and reports the
    failure, because a release problem such as a version collision is not a reason
    to refuse someone's code. hook.mode "gate" makes the pipeline a hard gate.
    """
    try:
        config = load_config(repo_root(args.repo))
    except PrpError:
        return False
    return str((config.get("hook") or {}).get("mode", "release")) == "gate"


def main(argv: Sequence[str] | None = None) -> int:
    _tolerant_console()
    started = time.monotonic()
    args = build_parser().parse_args(argv)
    hook_mode = bool(getattr(args, "triggered_by_hook", False))
    code = 0
    try:
        code = args.func(args)
    except Refused as exc:
        print("")
        print("REFUSED: " + str(exc))
        code = 2
    except PrpError as exc:
        print("")
        print("ERROR: " + str(exc), file=sys.stderr)
        code = 1
    _record("skill_run", started)
    if hook_mode and code != 0 and not _hook_blocks_push(args):
        print("")
        print("The push itself is not blocked (hook.mode is not 'gate').")
        print("Fix the problem above and push again, or run the pipeline by hand:")
        print("  python .ci/lib/run_pipeline.py release --repo " + str(args.repo))
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
