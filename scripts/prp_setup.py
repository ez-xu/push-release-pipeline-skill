#!/usr/bin/env python3
"""Adopt the release pipeline into a repository: probe, configure, vendor, hook.

Setup never guesses silently. It writes the values it detected into a config file
and prints every inference it made, so a wrong guess is visible before the first
push rather than after a wrong release.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from prp_build import LOCAL_CONFIG_REL, find_toolchain
from prp_publish import detect_provider
from prp_repo import PrpError, branch_name, git, remote_url, repo_root, run

CONFIG_REL = ".ci/config.json"
LIB_REL = ".ci/lib"
HOOK_REL = ".ci/hooks/pre-push"
OUTPUT_REL = ".ci/out"
# Entries are written verbatim; a trailing slash marks a directory pattern, and a
# directory-only pattern does not match a file.
IGNORE_ENTRIES = (OUTPUT_REL + "/", LOCAL_CONFIG_REL, "__pycache__/")

VENDOR_MODULES = (
    "run_pipeline.py",
    "prp_repo.py",
    "prp_build.py",
    "prp_publish.py",
    "prp_setup.py",
    "success_ledger.py",
)

HOOK_TEMPLATE = """#!/bin/sh
# pre-push hook installed by push-release-pipeline-skill.
# Runs the integrity-gated release pipeline for the branch refs being pushed.

REMOTE_NAME="$1"
[ -n "$REMOTE_NAME" ] || REMOTE_NAME=origin

# The pipeline pushes a tag itself; that push must not re-enter this hook.
PRP_FLAG="$PRP_IN_PROGRESS"
if [ "$PRP_FLAG" = "1" ]; then
  exit 0
fi

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$ROOT" || exit 0

# Importing the vendored modules would otherwise leave __pycache__ behind and make
# the work tree dirty, which the pipeline's own clean-tree gate then refuses.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

ENTRY="$ROOT/.ci/lib/run_pipeline.py"
[ -f "$ENTRY" ] || exit 0

BRANCH_REF=""
while read -r local_ref local_sha remote_ref remote_sha; do
  case "$local_ref" in
    refs/heads/*) BRANCH_REF="$local_ref" ;;
  esac
done

[ -n "$BRANCH_REF" ] || exit 0

PY=""
# No interpreter path is baked in here: this hook is committed, so an absolute
# path would pin it to the machine that ran setup and silently skip the pipeline
# on every other clone. Resolve it from PATH at run time instead.
for candidate in "${PRP_PYTHON:-}" python3 python py; do
  [ -n "$candidate" ] || continue
  RESOLVED=$(command -v "$candidate" 2>/dev/null)
  [ -n "$RESOLVED" ] || continue
  # The Microsoft Store python3.exe stub resolves under WindowsApps and does not
  # run a script; skip it rather than let it open the Store on every push.
  case "$RESOLVED" in
    *WindowsApps*) continue ;;
  esac
  if "$candidate" -c "import sys" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "pre-push: no working python interpreter found; release pipeline skipped" >&2
  exit 0
fi

exec "$PY" "$ENTRY" release --repo "$ROOT" --remote "$REMOTE_NAME" --triggered-by-hook
"""


def default_config() -> dict[str, Any]:
    """The config shape written on first setup, with nothing detected yet."""
    return {
        "schemaVersion": 1,
        "project": {"name": "", "releaseBranch": "main"},
        "remote": "origin",
        "outputDir": OUTPUT_REL,
        "build": {
            "cwd": ".",
            "clean": [],
            "configure": [],
            "build": [],
            "env": {},
            "timeoutSeconds": 3600,
        },
        "artifact": {
            "root": "",
            "glob": "",
            "versionRegex": "",
            "embeddedVersion": {"kind": "pe-file-version"},
        },
        "tag": {"template": "V{version}"},
        "release": {"provider": "auto", "name": "{tag}"},
        "verify": {"readBack": True, "rollbackOnFailure": True},
        "guard": {"mutableTrackedPaths": []},
        "hook": {"mode": "release"},
    }


def _read_json(path: Path, required: bool) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise PrpError(
                "no pipeline config at "
                + str(path)
                + "; run: python run_pipeline.py setup --repo "
                + str(path.parent.parent)
            )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrpError("config at " + str(path) + " is not valid JSON: " + str(exc)) from exc
    if not isinstance(data, dict):
        raise PrpError("config at " + str(path) + " must be a JSON object")
    return data


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay wins, section by section, so a local file patches rather than replaces."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def load_config(repo: Path) -> dict[str, Any]:
    """Read the committed config, then apply this machine's local overlay.

    The committed file is shared by every clone, so it may only contain values that
    mean the same thing everywhere. Anything that depends on where the repository
    sits or which toolchain this host installed belongs in the local overlay.
    """
    config = _read_json(repo / CONFIG_REL, required=True)
    local = repo / LOCAL_CONFIG_REL
    if local.is_file():
        config = _deep_merge(config, _read_json(local, required=False))
    return config


def save_config(repo: Path, config: Mapping[str, Any]) -> Path:
    path = repo / CONFIG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def save_local_config(repo: Path, overlay: Mapping[str, Any]) -> Path:
    """Write the machine-local overlay, merging into whatever is already pinned."""
    path = repo / LOCAL_CONFIG_REL
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            existing = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _deep_merge(existing, overlay)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# Host paths that mean nothing on another machine. A committed config that carries
# one is a config that only builds on the machine that wrote it.
_ABS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]"), "a Windows drive path"),
    (re.compile(r"\\\\[^\\/\s]+[\\/]"), "a UNC path"),
    (
        re.compile(r"(?:^|[\s\"'=:,])/(?:usr|opt|home|Users|Applications|etc|var|mnt|media|srv)/"),
        "a POSIX absolute path",
    ),
    (re.compile(r"(?:^|[\s\"'=:,])~(?:[/\\])"), "a home-relative path"),
    (re.compile(r"%USERPROFILE%|%HOMEPATH%|\$\{?HOME", re.IGNORECASE), "a home environment variable"),
)


def _walk_strings(value: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_strings(item, prefix + "." + str(key) if prefix else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk_strings(item, prefix + "[" + str(index) + "]")


def _hook_host_path_problems(rel: str, text: str) -> list[str]:
    """Report every host-specific path that appears in a committed hook script."""
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for pattern, label in _ABS_PATTERNS:
            if not pattern.search(line):
                continue
            problems.append(
                rel
                + " line "
                + str(number)
                + " carries "
                + label
                + " ("
                + line.strip()
                + "), so the hook only runs on the machine that wrote it and silently "
                "skips the pipeline on every other clone. Resolve the interpreter from "
                "PATH (or the PRP_PYTHON override) at run time instead of baking in an "
                "absolute path."
            )
            break
    return problems


def portability_problems(repo: Path) -> list[str]:
    """Host paths in the committed CI files cannot survive another machine.

    The config and the hook are both committed, so both are checked: a hook that
    hard-codes the setup machine's interpreter is exactly as unshippable as a
    config that hard-codes its compiler.
    """
    problems: list[str] = []
    path = repo / CONFIG_REL
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, Mapping):
            for field, text in _walk_strings(data):
                for pattern, label in _ABS_PATTERNS:
                    if not pattern.search(text):
                        continue
                    problems.append(
                        CONFIG_REL
                        + " carries "
                        + label
                        + " in "
                        + field
                        + " ("
                        + text
                        + "), so it only builds on the machine that wrote it. Commit a "
                        "machine-independent value instead: name build tools with the {qmake}, "
                        "{make} and {makeBin} tokens, and move anything host-specific into "
                        + LOCAL_CONFIG_REL
                        + " (git-ignored, regenerated per machine by setup)."
                    )
                    break
    hooks_dir = repo / ".ci" / "hooks"
    if hooks_dir.is_dir():
        for hook in sorted(hooks_dir.iterdir()):
            if not hook.is_file():
                continue
            try:
                text = hook.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            problems.extend(
                _hook_host_path_problems(hook.relative_to(repo).as_posix(), text)
            )
    return problems


def validate_config(config: Mapping[str, Any], repo: Path | None = None) -> list[str]:
    """Return the list of blocking config problems.

    With a repository, the committed file itself is also checked: a value that only
    makes sense on one host is a blocking problem, because the clone that runs the
    pipeline is not necessarily the clone that wrote the config.
    """
    problems: list[str] = []
    build = config.get("build") or {}
    if not build.get("build"):
        problems.append("build.build is empty: there is no compile command to run")
    artifact = config.get("artifact") or {}
    for key in ("root", "glob", "versionRegex"):
        if not artifact.get(key):
            problems.append("artifact." + key + " is required")
    tag = config.get("tag") or {}
    if not tag.get("template"):
        problems.append("tag.template is required")
    elif "{version}" not in str(tag["template"]):
        problems.append("tag.template must contain the {version} placeholder")
    if not (config.get("project") or {}).get("releaseBranch"):
        problems.append("project.releaseBranch is required")
    if repo is not None:
        problems.extend(portability_problems(repo))
    return problems


def probe(repo: Path) -> dict[str, Any]:
    """Inspect a repository and report what the pipeline would need."""
    facts: dict[str, Any] = {"repo": str(repo)}
    facts["branch"] = branch_name(repo)
    facts["remote"] = remote_url(repo, "origin")
    facts["provider"] = detect_provider(facts["remote"])
    facts["head"] = git(repo, "rev-parse", "HEAD")
    facts["projectFiles"] = [str(p.relative_to(repo)) for p in sorted(repo.glob("*.pro"))][:10]
    facts["subprojectFiles"] = sorted(str(p.relative_to(repo)) for p in repo.glob("*/*.pro"))[:20]
    facts["toolchain"] = find_toolchain()
    facts["localConfig"] = (repo / LOCAL_CONFIG_REL).is_file()
    facts["buildDirs"] = sorted(
        str(p.relative_to(repo)) for p in repo.glob("build/*") if p.is_dir()
    )[:20]
    binaries: list[str] = []
    for pattern in ("build/**/*.exe", "build/**/*.bin", "build/**/*.elf", "build/**/*.hex"):
        for path in repo.glob(pattern):
            if path.is_file():
                binaries.append(str(path.relative_to(repo)))
    facts["binaries"] = sorted(binaries)[:20]
    facts["hasConfig"] = (repo / CONFIG_REL).is_file()
    return facts


def propose_config(
    facts: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Turn probe facts into a config plus the list of inferences made.

    The config returned is the one that gets committed, so it names the build tools
    by token and holds no host path. The third value is the machine-local pin that
    records what was detected here; it is written to a git-ignored file instead.
    """
    config = default_config()
    notes: list[str] = []
    local: dict[str, Any] = {}
    config["project"]["name"] = Path(str(facts["repo"])).name
    config["project"]["releaseBranch"] = str(facts.get("branch") or "main")
    notes.append("project.releaseBranch <- the branch currently checked out")

    toolchain = facts.get("toolchain") or {}
    qmake = toolchain.get("qmake")
    make = toolchain.get("make") or toolchain.get("mingw32-make")
    subprojects = list(facts.get("subprojectFiles") or [])
    binaries = list(facts.get("binaries") or [])

    if qmake and make:
        build_dirs = list(facts.get("buildDirs") or [])
        shadow = next((d for d in build_dirs if "Release" in d or "release" in d), None)
        target = None
        for candidate in subprojects:
            stem = Path(candidate).stem
            if any(stem.lower() in b.lower() for b in binaries):
                target = candidate
                break
        if target is None and subprojects:
            target = subprojects[0]
        if target is None:
            notes.append("no .pro file found; build commands left empty for you to fill in")
        else:
            pro = target
            if shadow:
                build_dir = shadow + "/" + Path(pro).stem
                notes.append(
                    "build dir <- existing shadow build directory "
                    + shadow
                    + " (keeping the build outside the source tree)"
                )
            else:
                build_dir = "build/" + Path(pro).stem
                notes.append("build dir <- build/<project> (no shadow build directory existed)")
            config["build"]["cwd"] = str(Path(build_dir).parent)
            config["build"]["configure"] = ["{qmake}", "{repo}/" + pro]
            config["build"]["build"] = ["{make}", "-j4"]
            config["build"]["clean"] = [
                Path(build_dir).name + "/**/*.o",
                Path(build_dir).name + "/Makefile",
                Path(build_dir).name + "/Makefile.*",
            ]
            # {qmake} and {make} are resolved on whichever machine runs the build,
            # so the committed config stays valid in every clone.
            config["build"]["env"] = {"PATH": "{makeBin}{pathsep}{PATH}"}
            notes.append("build.configure <- {qmake} on " + pro + " (resolved per machine)")
            notes.append("build.build <- {make} -j4 (resolved per machine)")
            notes.append(
                "build.env.PATH <- {makeBin} prepended, because the generated Makefile"
                " calls the compiler by bare name"
            )
            local["toolchain"] = {"qmake": qmake, "make": make}
            notes.append(
                "toolchain pinned for this machine only in "
                + LOCAL_CONFIG_REL
                + " ("
                + qmake
                + "; "
                + make
                + "); the committed config carries no host path"
            )
            config["artifact"]["root"] = build_dir
            notes.append("artifact.root <- " + build_dir)
        if binaries:
            sample = Path(binaries[0]).name
            suffix = Path(sample).suffix
            if "_V" in sample:
                stem = sample.split("_V")[0]
                config["artifact"]["glob"] = stem + "_V*" + suffix
                config["artifact"]["versionRegex"] = "_V(?P<version>[0-9]+(?:\\.[0-9]+)+)\\" + suffix + "$"
                notes.append(
                    "artifact.versionRegex <- read back from the version in the name of " + sample
                )
            else:
                config["artifact"]["glob"] = "*" + suffix
                notes.append(
                    "artifact.glob <- *"
                    + suffix
                    + " from "
                    + sample
                    + "; add artifact.versionRegex before the first release"
                )
    else:
        notes.append("no Qt/MinGW toolchain found; build commands left empty for you to fill in")
    return config, notes, local


CONTRACT_SOURCE = ("contract_health.py", "contracts/data_contract_release_api/code/contract_health.py")


def vendor_lib(repo: Path, source_dir: Path) -> list[str]:
    """Copy the runtime modules into the repository so the hook is self-contained.

    The release_api contract is vendored too: the pre-build readiness check is part
    of the pipeline, so a clone must be able to run it without this skill installed.
    """
    target = repo / LIB_REL
    target.mkdir(parents=True, exist_ok=True)
    sources = [(name, source_dir / name) for name in VENDOR_MODULES]
    sources.append((CONTRACT_SOURCE[0], source_dir.parent / CONTRACT_SOURCE[1]))
    copied: list[str] = []
    for name, src in sources:
        if not src.is_file():
            continue
        shutil.copyfile(src, target / name)
        copied.append(name)
    return copied


def write_hook(repo: Path, python_executable: str | None = None) -> Path:
    """Write the pre-push hook.

    python_executable is accepted for call-site compatibility and deliberately
    ignored. The hook is committed, so baking the setup machine's interpreter into
    it would pin the hook to one host; PATH resolution already finds that same
    interpreter on the machine that ran setup.
    """
    path = repo / HOOK_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HOOK_TEMPLATE, encoding="utf-8", newline="\n")
    return path


def install_hook(repo: Path, log: list[str]) -> Path:
    """Copy the hook into .git/hooks/pre-push, refusing to clobber a foreign one."""
    source = repo / HOOK_REL
    if not source.is_file():
        raise PrpError("no hook at " + str(source) + "; run setup first")
    git_dir = Path(git(repo, "rev-parse", "--git-dir"))
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    hooks = git_dir / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-push"
    if target.is_file():
        existing = target.read_text(encoding="utf-8", errors="replace")
        if "push-release-pipeline-skill" not in existing:
            raise PrpError(
                "an unrelated pre-push hook already exists at "
                + str(target)
                + "; merge it manually or move it aside first"
            )
        log.append("[hook] replacing the existing push-release-pipeline hook")
    shutil.copyfile(source, target)
    try:
        os.chmod(target, 0o755)
    except OSError:
        pass
    return target


def uninstall_hook(repo: Path, log: list[str]) -> bool:
    git_dir = Path(git(repo, "rev-parse", "--git-dir"))
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    target = git_dir / "hooks" / "pre-push"
    if target.is_file() and "push-release-pipeline-skill" in target.read_text(
        encoding="utf-8", errors="replace"
    ):
        target.unlink()
        log.append("[hook] removed " + str(target))
        return True
    return False


def ensure_gitignore(repo: Path, entry: str) -> bool:
    """Make sure nothing the pipeline writes can ever dirty the work tree.

    The entry is written exactly as given. Appending a slash unconditionally would
    turn a file entry such as .ci/config.local.json into a directory-only pattern,
    which never matches the file it is supposed to ignore.
    """
    path = repo / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = [line.strip() for line in text.splitlines()]
    if entry in lines or entry.rstrip("/") + "/" in lines:
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += (
        "\n# push-release-pipeline-skill: never let pipeline state dirty the work tree\n"
        + entry
        + "\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def is_ignored(repo: Path, rel: str) -> bool:
    """Whether git ignores a path; the pipeline refuses to run when it does not.

    The directory form is tried as well: a .gitignore entry written as .ci/out/
    only matches a directory, and git cannot classify a path that does not exist
    yet, so the bare path alone would report a false negative before the first run.
    """
    for candidate in (rel.rstrip("/") + "/", rel):
        proc = run(["git", "check-ignore", "--quiet", candidate], cwd=repo, timeout=60)
        if proc.returncode == 0:
            return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    """Diagnostic entry point: print the probe result for a repository."""
    import argparse

    parser = argparse.ArgumentParser(description="Probe a repository for release readiness.")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    try:
        root = repo_root(args.repo)
        facts = probe(root)
    except PrpError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    config, notes, local = propose_config(facts)
    print(
        json.dumps(
            {
                "facts": facts,
                "proposedConfig": config,
                "localConfig": local,
                "inferences": notes,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
