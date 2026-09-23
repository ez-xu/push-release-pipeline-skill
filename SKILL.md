---
name: push-release-pipeline-skill
description: >-
  Turn a local git push into a release whose artifact is provably built from the
  commit that was pushed. Use when a repository must compile, tag and publish
  firmware or a binary automatically, and when a published tag must never disagree
  with the file attached to it. Adopt it into a repository with setup, then let the
  pre-push hook gate the build, verify no tracked file changed during it, read the
  version back out of the produced artifact, tag, publish, and re-download the
  published asset to confirm it is byte-identical to what was built. Triggers on
  本地推送自动编译发布, 推送自动出包, 自动打标签发布, push-triggered release,
  tag and artifact must match, closed-loop release verification, release integrity
  pipeline, firmware auto release. Do not use it to publish a release by hand, to
  bump a version, or to repair an already-published tag.
license: MIT
activation: /push-release-pipeline-skill
metadata:
  author: agent-skills-platform
  version: 1.0.0
  created: 2026-09-23
  last_reviewed: 2026-09-23
  review_interval_days: 90
  dependencies:
    - name: git
      type: command
      note: 2.40 or newer; hooks run under the platform shell git provides
    - name: glab
      type: command
      note: required only for GitLab remotes; used to create and re-download releases
    - name: gh
      type: command
      note: required only for GitHub remotes; used to create and re-download releases
    - name: python
      type: runtime
      note: 3.9 or newer; standard library only, no third-party packages
provenance:
  maintainer: Jinghan Xu
  version: 1.0.0
  created: 2026-09-23
  source_references:
    - https://docs.gitlab.com/ee/api/releases/
    - https://cli.github.com/manual/gh_release_create
    - https://git-scm.com/docs/githooks#_pre_push
---

# /push-release-pipeline-skill

Make a push produce a release that can be proven to come from the commit that was
pushed. The pipeline refuses rather than publishes whenever that proof is missing.

## One command

Adopt it into a repository, review the config, then install the hook:

```bash
python3 scripts/run_pipeline.py setup --repo <REPO> --install-hook
```

After that, every push to the release branch runs the pipeline. To run it without
pushing, or to see what it would do without publishing anything:

```bash
python3 scripts/run_pipeline.py check   --repo <REPO> --json
python3 scripts/run_pipeline.py release --repo <REPO> --dry-run
```

To re-verify a release that is already published, without building anything:

```bash
python3 scripts/run_pipeline.py verify --repo <REPO> --tag <TAG>
```

## What it does, in order

| Step | Gate | Refuses when |
|---|---|---|
| 1 | preconditions | not a git work tree, config incomplete, remote missing, release CLI absent or unauthenticated, not on the release branch |
| 2 | clean tree | any uncommitted or untracked change exists |
| 3 | identity snapshot | captures HEAD, tree, tracked-file manifest, status |
| 4 | clean build | the configured build command exits non-zero |
| 5 | drift guard | HEAD, tree, manifest or status differ after the build |
| 6 | time guard | any tracked file's modification time changed during the build |
| 7 | version cross-check | the version in the file name disagrees with the version inside the binary |
| 8 | tag occupancy | the tag already exists at a different commit |
| 9 | publish | tag, push tag, confirm the remote tag resolves to this commit, create the release |
| 10 | closed-loop read-back | the remote tag moved, or the re-downloaded asset is not byte-identical to the build |
| 11 | record | writes .ci/out/<run>/manifest.json, release-notes.md and build.log |

A refusal at any step before publishing leaves nothing behind. A failure after the
tag exists triggers a rollback that deletes the release, the remote tag and the
local tag, so the next push starts from a consistent state.

## The standard this enforces

A release counts as successful only when all three hold at once:

1. the published tag resolves to the commit that was pushed;
2. the artifact was produced from that commit while no tracked file changed;
3. the asset downloaded back from the release is byte-identical to the local artifact.

Anything less is reported as a failed release, not a successful one.

## Required behavior

1. Never move a tag that already exists. A version collision is refused, and the
   message names the build-system version to raise.
2. Never recompute the version from the build system. Read it out of the artifact
   that was produced, then cross-check the binary's own version resource.
3. Never treat a successful upload as proof. Re-read the remote tag and re-download
   the asset before calling the release successful.
4. Report a refusal as a refusal. Exit code 2 means nothing was published and the
   repair is named; exit code 1 means a partial publication was rolled back.
5. When the pipeline runs from the hook, a failure does not block the code push
   unless the config sets hook.mode to gate.

## Gotchas

- GitLab's release CLI will create the tag itself from the repository default branch
  when the named tag does not exist. The release would then point at a commit nobody
  built. The pipeline always pushes the tag first and passes an explicit ref.
- An annotated tag is two objects. Asking git for the tag returns the tag object id,
  not the commit, so comparing it with HEAD is always false. Every tag comparison
  must dereference to a commit, and the remote listing must use the peeled line.
- shutil.which is PATHEXT-aware but the Windows process launcher is not. Invoking the
  bare name glab can run a different glab.exe than the .cmd shim that was detected,
  which is the normal layout for scoop, npm and chocolatey installs. Resolve the CLI
  to an absolute path once and invoke that.
- Importing the vendored modules creates __pycache__, which dirties the work tree and
  makes the pipeline refuse the very push that triggered it. Bytecode writing is
  disabled, and setup adds the ignore entries anyway.
- Under Git for Windows the hook runs under MSYS bash, where git prints a POSIX path
  such as /c/Users/... that native Python cannot open. Resolve the repository root
  from Python, never from the shell.
- A directory-only ignore entry such as .ci/out/ does not match when the path does
  not exist yet, so an ignore check on the bare path reports a false negative.
- Git has no post-push hook. The release necessarily runs before the branch lands,
  which is why the tag is pushed explicitly rather than relying on the branch push.
- The release CLI prints an update notice on stderr for every invocation. Never infer
  success from stderr being non-empty; use the exit code.
- A version derived from a date can be computed two ways. PowerShell's [int] rounds
  while a day count truncates, so the same day can yield two versions at noon. The
  pipeline never recomputes it; it reads the artifact.
- An absolute path to the build tool is not enough. A qmake-generated Makefile calls
  the compiler by bare name, so the build step also needs the compiler's directory on
  PATH; without it the build dies with "g++: error: CreateProcess: No such file or
  directory" even though qmake itself ran fine. That is what build.env is for.
- A Windows pipe defaults to a legacy code page such as cp936 or cp1252. The readiness
  report embeds text captured from the release CLI, which carries a check mark, so
  printing it raised UnicodeEncodeError and hid the report itself. stdout and stderr
  are reconfigured with errors="replace" before anything is printed.
- A build directory that keeps every version it ever produced makes the artifact
  ambiguous, because artifact.glob must match exactly one file. Either clean the old
  artifacts in build.clean or narrow the glob, and archive what you delete first.

## References

| File | Read it when |
|---|---|
| references/config-reference.md | you need to fill in or change .ci/config.json |
| references/gates.md | a gate refused and you need to know exactly what it checked |
| references/team-adoption.md | a second developer or machine needs the same pipeline |
| contracts/data_contract_release_api/code/contract_health.py | you need to see what the release interface readiness check verifies |

## Files the skill writes into the repository

- .ci/config.json — the pipeline configuration, reviewed and committed by a human
- .ci/lib/ — the vendored runtime, so a clone works without this skill installed
- .ci/hooks/pre-push — the hook source, installed into .git/hooks by install-hook
- .ci/out/<run>/ — per-run build log, release notes and provenance manifest
