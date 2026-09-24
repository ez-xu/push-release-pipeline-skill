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

A dry run stops before the tag is created, so it never exercises the upload, the asset link or the read-back: passing one is not evidence that a release will succeed. references/team-adoption.md shows how to exercise that path with a throwaway release.

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
6. Never commit a host path. .ci/config.json is shared by every clone, so it may
   name the build tools only through the {qmake}, {make} and {makeBin} tokens and
   may reach the repository only through {repo}. Anything bound to one machine —
   a toolchain location, an interpreter path, a home directory — belongs in
   .ci/config.local.json, which is git-ignored and regenerated per machine by
   setup. The rule covers every committed CI file, not only the config: the hook
   resolves its interpreter from PATH (or PRP_PYTHON) at run time, so no
   interpreter path is ever baked into it. A committed CI file carrying an
   absolute host path is refused before anything is built, because it would
   either fail on every other clone or silently build with whatever toolchain
   that host happens to have.

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
  directory" even though qmake itself ran fine. build.env adds {makeBin} — the
  directory of the make that was resolved — which is where the compiler sits.
- A fresh clone has no shadow build directory, so the configured build working
  directory may not exist yet. The pipeline creates it before the build rather than
  failing the first push on a machine that has never built the project.
- The three toolchain tokens are resolved from the local pin first, then PATH, then
  the usual install roots. An unresolved token refuses the run and names the pin file
  to write; it never falls back to a path the config did not ask for.
- A Windows pipe defaults to a legacy code page such as cp936 or cp1252. The readiness
  report embeds text captured from the release CLI, which carries a check mark, so
  printing it raised UnicodeEncodeError and hid the report itself. stdout and stderr
  are reconfigured with errors="replace" before anything is printed.
- A build directory that keeps every version it ever produced makes the artifact
  ambiguous, because artifact.glob must match exactly one file. Either clean the old
  artifacts in build.clean or narrow the glob, and archive what you delete first.
- committing a host path into .ci/config.json: the repository is cloned on other machines, so an absolute toolchain path either fails there or silently builds with the wrong toolchain. Name build tools with {qmake}/{make}/{makeBin}; keep every host-specific value in the git-ignored .ci/config.local.json.
- baking an interpreter path into .ci/hooks/pre-push: the hook is committed too, so an absolute path pins it to the machine that ran setup and silently skips the pipeline on every other clone. The template resolves PRP_PYTHON, python3, python and py from PATH at run time, and the portability gate scans every file under .ci/hooks/ as well as .ci/config.json.

- GitLab refuses a release asset whose filepath is not ASCII: the assets-links call answers 400 Filepath is in an invalid format, and the run then rolls back and deletes the tag, so the push leaves no tag and no file behind. A tag may carry non-ASCII, but an asset name is a filepath, so the published asset must be ASCII, and the version read back out of the binary has to use the same ASCII transliteration or the version cross-check refuses the release. A product whose canonical firmware name is Chinese keeps that name for customers: the build command copies it to an ASCII-named file in the directory artifact.glob watches, byte for byte, and release.assetLabel is not the fix - the implementation names the asset after the artifact file, never after that key.

- A created release can be unusable even though every step reported success: glab 1.52 records the uploaded file's link URL without the project namespace (https://host/-/project/<id>/uploads/<secret>/<name>), and GitLab's asset download route redirects to exactly that URL, so the asset 404s for every consumer and for the pipeline's own read-back. Rewrite the link to the API uploads route (/api/v4/projects/<id>/uploads/<secret>/<name>) before the read-back, idempotently, and fetch the read-back through the route a consumer clicks rather than through a copy obtained another way.

- build.clean patterns are pathlib globs, and pathlib's dir/** matches directories only, so a pattern such as build/** deletes nothing while reporting removed 0 file(s) and a stale artifact then survives into the next build. Write dir/**/* (or name the files explicitly), and read removed 0 file(s) as a signal to check the pattern rather than as proof of a clean tree.
- A build that can run on a tree it did not clean must pick the artifact as the file that did not exist before the build, never as the only file it happens to find: a wrapper that assumes an empty output directory turns one surviving file into the pipeline's ambiguity refusal (N artifacts matched <glob>; the version would be ambiguous). Report how many were seen before and after, and point at build.clean when the selection is not exactly one.
- Two things in the config look like levers and are not. {artifactPath} is not a token: only {repo}, the toolchain tokens, {PATH}/{pathsep} in build.env and the release-side tokens in tag.template and release.name are expanded, so a command argument asking for {artifactPath} receives that literal text and the command must locate the artifact itself through artifact.root and artifact.glob. release.assetLabel is written by setup and read by nothing: the published asset is always named after the artifact file, so an ASCII artifact file name is the only way to choose it.
- A dry run is not a rehearsal of publishing. release --dry-run stops before the tag is created, so it cannot reach the upload, the asset link or the read-back, and a repository can pass a dry run and still fail its first real release. Only a real run, or verify against a release that already exists, covers that path.
- On a private instance a release asset is not anonymously reachable, and the refusal is quiet: an unauthenticated GET of the asset URL can answer 200 with the sign-in page, while the API route answers 401 or 404. A read-back that judges by status code accepts a login page as a successful download, so it must compare the bytes (size and SHA-256) and never the status.
- Committed CI files have to survive the console and the platform. Keep every message a build step prints ASCII: CMake and Ninja write raw UTF-8 into a legacy code page such as cp936 or cp1252 and the transcript becomes mojibake, while Python's console API is unaffected. Pin line endings too: .ci/hooks/pre-push is executed by MSYS bash under Git for Windows and a CRLF copy does not run, while a CRLF-sensitive .bat or .cmd breaks when core.autocrlf rewrites it, so .gitattributes should force eol=lf for the hook, *.sh and *.py and eol=crlf for *.bat and *.cmd.

- A pipeline that re-lists the build commands duplicates the project's own build script, and the two drift: the release then builds something the developer never ran. When the repository already has a build entry point (build.bat, a Makefile, a script), leave build.configure empty and call that entry from build.build, passing the pipeline's isolation through environment variables or extra arguments the script already honours. Keep one source of truth for the directories as well - a thin wrapper can derive its build directory from artifact.root instead of repeating it.
- Deciding "the artifact this build produced" by file name alone breaks on a rebuild that produces the same name: the same commit on the same day yields a byte-identical file with an identical name, so a name-based diff reports zero new files and the run stops on a complete build. Treat a file as this build's output when it did not exist before the build or its mtime is not older than the build start, and require exactly one such file.

## References

| File | Read it when |
|---|---|
| references/config-reference.md | you need to fill in or change .ci/config.json |
| references/gates.md | a gate refused and you need to know exactly what it checked |
| references/team-adoption.md | a second developer or machine needs the same pipeline |
| contracts/data_contract_release_api/code/contract_health.py | you need to see what the release interface readiness check verifies |

## Files the skill writes into the repository

- .ci/config.json — the pipeline configuration; committed, and deliberately free of
  any host path so it means the same thing in every clone
- .ci/config.local.json — this machine's toolchain pin; written by setup, git-ignored,
  never committed
- .ci/lib/ — the vendored runtime, so a clone works without this skill installed
- .ci/hooks/pre-push — the hook source, installed into .git/hooks by install-hook
- .ci/out/<run>/ — per-run build log, release notes and provenance manifest
