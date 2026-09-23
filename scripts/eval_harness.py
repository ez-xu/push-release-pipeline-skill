#!/usr/bin/env python3
"""Offline regression harness for the push-release pipeline.

Builds a throwaway git repository with a synthetic build, a bare origin and a fake
release provider, then runs the real pipeline against one scenario and writes a JSON
verdict. It touches no network, no real provider and no real repository, so it is
safe to run as often as the eval suite wants.

The verdict records both what the pipeline decided and whether its safety invariants
held, so a scenario that refuses and a scenario that publishes can be graded by the
same criteria.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENTRY = HERE / "run_pipeline.py"

FAKE_PROVIDER = '''"""A stand-in for glab that stores releases in a directory."""
import os, shutil, sys
from pathlib import Path

STORE = Path(os.environ["PRP_EVAL_STORE"])
STORE.mkdir(parents=True, exist_ok=True)
argv = sys.argv[1:]
if not argv:
    sys.exit(2)
if argv[0] == "auth":
    print("fake provider: authenticated")
    sys.exit(0)
if argv[0] != "release":
    sys.exit(2)
if "--help" in argv or "-h" in argv:
    print("CORE COMMANDS create delete download list upload view")
    sys.exit(0)
cmd = argv[1]
if cmd == "create":
    tag = argv[2]
    files = [a for a in argv[3:] if not a.startswith("-")]
    src = Path(files[0])
    dest = STORE / tag
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest / src.name)
    if os.environ.get("PRP_EVAL_CORRUPT") == "1":
        (dest / src.name).write_bytes(b"CORRUPTED IN TRANSIT")
    print("fake provider: created release " + tag)
    sys.exit(0)
if cmd == "download":
    tag = argv[2]
    args = argv[3:]
    name, dest_dir, i = None, ".", 0
    while i < len(args):
        if args[i] in ("--asset-name", "-n"):
            name = args[i + 1]; i += 2; continue
        if args[i] in ("--dir", "-D"):
            dest_dir = args[i + 1]; i += 2; continue
        i += 1
    d = Path(dest_dir); d.mkdir(parents=True, exist_ok=True)
    src = STORE / tag / name
    if not src.is_file():
        print("fake provider: asset missing", file=sys.stderr)
        sys.exit(1)
    shutil.copyfile(src, d / name)
    print("fake provider: downloaded " + name)
    sys.exit(0)
if cmd == "delete":
    shutil.rmtree(STORE / argv[2], ignore_errors=True)
    print("fake provider: deleted release " + argv[2])
    sys.exit(0)
sys.exit(2)
'''

BUILD = '''import os, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                      text=True).stdout.strip()
if os.environ.get("PRP_EVAL_MUTATE") == "1":
    (root / "src" / "app.txt").write_text("mutated during the build\\n", encoding="utf-8")
if os.environ.get("PRP_EVAL_TOUCH") == "1":
    p = root / "src" / "app.txt"
    p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
out = root / "build" / "app" / "bin"
out.mkdir(parents=True, exist_ok=True)
version = os.environ.get("PRP_EVAL_VERSION", "1.2.3")
name = "app_V" + version + ".bin"
(out / name).write_bytes(("FIRMWARE\\ncommit=" + head + "\\nversion=" + version + "\\n").encode())
print("built " + name + " for " + head[:12])
'''

CONFIG_OVERRIDES = {
    "build": {"build": ["{python}", "tool/build.py"], "configure": [],
              "clean": ["build/**/*.bin"], "cwd": ".", "timeoutSeconds": 600},
    "artifact": {"root": "build/app/bin", "glob": "app_V*.bin",
                 "versionRegex": r"_V(?P<version>[0-9]+(?:\.[0-9]+)+)\.bin$",
                 "embeddedVersion": None},
}


def run(cmd, cwd=None, env=None):
    full = dict(os.environ)
    if env:
        full.update(env)
    return subprocess.run(cmd, cwd=cwd, env=full, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def force_remove(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def make_fake_provider(bindir: Path) -> None:
    """Write a provider CLI the platform can actually execute.

    On Windows the launcher cannot run a .py directly, and a bare name would resolve
    to any real glab.exe on PATH, so a .cmd shim sits beside it and the shim's
    directory is placed first on PATH.
    """
    script = bindir / "glab.py"
    write(script, FAKE_PROVIDER)
    if os.name == "nt":
        write(bindir / "glab.cmd",
              '@echo off\r\n"' + sys.executable + '" "%~dp0glab.py" %*\r\n')
    else:
        launcher = bindir / "glab"
        write(launcher, "#!/bin/sh\nexec " + '"' + sys.executable + '" "$(dirname "$0")/glab.py" "$@"\n')
        launcher.chmod(0o755)


def _substitute(value):
    """Replace {python} anywhere in a config value, including inside argument lists."""
    if isinstance(value, str):
        return value.replace("{python}", sys.executable)
    if isinstance(value, list):
        return [_substitute(item) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item) for key, item in value.items()}
    return value


def build_scenario(scenario: dict, root: Path) -> dict:
    """Create the throwaway repository and return the paths the run needs."""
    repo = root / "repo"
    origin = root / "origin.git"
    store = root / "store"
    bindir = root / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    make_fake_provider(bindir)
    run(["git", "init", "--bare", "-b", "main", str(origin)])
    repo.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-b", "main", str(repo)])
    run(["git", "config", "user.name", "Eval Harness"], cwd=repo)
    run(["git", "config", "user.email", "eval@example.invalid"], cwd=repo)
    run(["git", "remote", "add", "origin", str(origin)], cwd=repo)
    write(repo / ".gitignore", "build/\n.ci/out/\n__pycache__/\n")
    write(repo / "src" / "app.txt", "application source\n")
    write(repo / "tool" / "build.py", BUILD)
    run(["git", "add", "-A"], cwd=repo)
    run(["git", "commit", "-m", "initial"], cwd=repo)

    if scenario.get("collideTag"):
        run(["git", "tag", "-a", "V" + str(scenario.get("version", "1.2.3")),
             "-m", "an earlier release"], cwd=repo)
        run(["git", "push", "origin", "main", "--tags"], cwd=repo)
        write(repo / "src" / "app.txt", "second revision\n")
        run(["git", "add", "-A"], cwd=repo)
        run(["git", "commit", "-m", "second revision"], cwd=repo)
    else:
        run(["git", "push", "-u", "origin", "main"], cwd=repo)

    env = {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
           "PRP_EVAL_STORE": str(store),
           "PYTHONIOENCODING": "utf-8"}
    setup = run([sys.executable, str(ENTRY), "setup", "--repo", str(repo)], env=env)
    config_path = repo / ".ci" / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for section, values in CONFIG_OVERRIDES.items():
            config.setdefault(section, {})
            for key, value in values.items():
                config[section][key] = _substitute(value)
        write(config_path, json.dumps(config, indent=2) + "\n")
    run(["git", "add", "-A"], cwd=repo)
    run(["git", "commit", "-m", "add the release pipeline config"], cwd=repo)

    if scenario.get("dirtyTree"):
        write(repo / "src" / "app.txt", "uncommitted edit\n")

    return {"repo": repo, "origin": origin, "store": store, "bindir": bindir,
            "env": env, "setupOutput": setup.stdout + setup.stderr,
            "tagsBefore": run(["git", "tag"], cwd=repo).stdout.split()}


def git(repo: Path, *args):
    proc = run(["git", *args], cwd=repo)
    return proc.stdout.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one pipeline scenario offline.")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    version = str(scenario.get("version", "1.2.3"))
    root = Path(tempfile.mkdtemp(prefix="prp-eval-"))
    try:
        ctx = build_scenario(scenario, root)
        env = dict(ctx["env"])
        env["PRP_EVAL_VERSION"] = version
        if scenario.get("touchTracked"):
            env["PRP_EVAL_TOUCH"] = "1"
        if scenario.get("mutateTracked"):
            env["PRP_EVAL_MUTATE"] = "1"
        if scenario.get("corruptUpload"):
            env["PRP_EVAL_CORRUPT"] = "1"

        proc = run([sys.executable, str(ENTRY), "release", "--repo", str(ctx["repo"])],
                   env=env)
        transcript = proc.stdout + proc.stderr

        tag = "V" + version
        tags_before = set(ctx["tagsBefore"])
        local_tags = git(ctx["repo"], "tag").split()
        remote_tags = [line.split("/")[-1]
                       for line in git(ctx["repo"], "ls-remote", "--tags", "origin").splitlines()
                       if line.strip()]
        release_present = (ctx["store"] / tag).is_dir()

        manifests = sorted((ctx["repo"] / ".ci" / "out").glob("*/manifest.json")) \
            if (ctx["repo"] / ".ci" / "out").is_dir() else []
        manifest = json.loads(manifests[-1].read_text(encoding="utf-8")) if manifests else {}

        published = bool(manifest.get("published"))
        verdict = str(manifest.get("readBackVerdict", ""))
        refused = "REFUSED:" in transcript

        # The invariants this skill exists to guarantee, checked on every scenario.
        closed_loop_consistent = (not published) or verdict == "pass"
        no_orphan_tag = (
            tag not in local_tags and tag not in remote_tags
        ) or published or tag in tags_before
        provenance_complete = (
            bool(manifest.get("commit")) and bool(manifest.get("tree"))
            and bool(manifest.get("sha256"))
        ) if manifest else (not published)

        result = {
            "scenario": scenario.get("id", args.scenario.stem),
            "exitCode": proc.returncode,
            "refused": refused,
            "published": published,
            "readBackVerdict": verdict or "not run",
            "refusalReason": next(
                (line.strip() for line in transcript.splitlines() if line.startswith("REFUSED:")),
                "",
            ),
            "rollback": "ran" if "Rolling back" in transcript else "not-needed",
            "tagRemains": tag in local_tags or tag in remote_tags,
            "releaseRemains": release_present,
            "checks": {
                "closedLoopConsistent": closed_loop_consistent,
                "noOrphanTag": no_orphan_tag,
                "provenanceComplete": provenance_complete,
            },
            "transcriptTail": transcript.strip().splitlines()[-22:],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        return 0
    finally:
        shutil.rmtree(root, onexc=force_remove)


if __name__ == "__main__":
    raise SystemExit(main())
