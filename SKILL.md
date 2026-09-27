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

## Publishing by hand, without a push

The hook is optional and is **off by default** (see Gotchas). Setup also writes a
double-clickable console next to the pipeline:

    .ci/release.bat          (Windows; CRLF; ASCII by default, GBK when asked for zh;
                              no path baked in - it resolves its own directory)

Double-clicking it opens a menu, so nobody has to remember a command or be told
what the pipeline is:

    1) Check + release     readiness report, then a confirmed real release
    2) Check only          read-only; publishes nothing
    3) Dry run             build + version cross-check, stop before publishing
    4) Install push hook   every git push to the release branch triggers a release
    5) Remove push hook    back to manual releases
    6) Verify a release    re-check an already published release
    Q) Quit

The menu re-reads the hook state every round, so turning it on or off is visible
immediately. Every choice maps to a `run_pipeline.py` subcommand: the console resolves
an interpreter and forwards, nothing else. The same commands work as arguments for
scripts and non-Windows hosts:

    .ci/release.bat check | dry-run | release [-y] | verify --tag T | hook on|off

On a host with no batch file, call the entry point directly:

    python .ci/lib/run_pipeline.py check|release|verify|install-hook|uninstall-hook|hook-status --repo .

The console is written in English by default, and that copy is pure ASCII so it
displays correctly on any code page. For a team that wants it in Chinese, ask setup
for the Chinese copy:

    python3 .ci/lib/run_pipeline.py setup --repo . --console-lang zh

It is the same console - only the display strings differ - written as GBK, and the
template starts it with `chcp 936` so the bytes and the console agree. Re-running
setup to switch languages is safe: without `--force` it keeps the existing
config.json and re-vendors .ci/lib without clearing it.

To re-verify a release that is already published, without building anything:

```bash
python3 scripts/run_pipeline.py verify --repo <REPO> --tag <TAG>
```

## What it does, in order

| Step | Gate | Refuses when |
|---|---|---|
| 1 | preconditions | not a git work tree, config incomplete, remote missing, release CLI absent or unauthenticated, not on the release branch (unless project.releaseBranch is `*`) |
| 2 | clean tree | any uncommitted or untracked change exists |
| 3 | identity snapshot | captures HEAD, tree, tracked-file manifest, status |
| 4 | clean build | the configured build command exits non-zero |
| 5 | drift guard | HEAD, tree, manifest or status differ after the build |
| 6 | time guard | any tracked file's modification time changed during the build |
| 7 | version cross-check | the version in the file name disagrees with the version inside the binary |
| 8 | tag occupancy | the tag already exists at a different commit |
| 9 | publish | tag, push tag, confirm the remote tag resolves to this commit, create the release — with every file artifact.extraGlobs names, each of their asset links repaired |
| 10 | closed-loop read-back | the remote tag moved, or any re-downloaded asset is not byte-identical to the build |
| 11 | record | writes .ci/out/<run>/manifest.json, release-notes.md and build.log |

A refusal at any step before publishing leaves nothing behind. A failure after the
tag exists triggers a rollback that deletes the release, the remote tag and the
local tag, so the next push starts from a consistent state.

## Handing over the link

A successful release and a later `verify` both end by printing the two URLs worth
having, and record them in the run next to the artifact hash:

    Release page : https://host/group/project/-/releases/V1.2.3
    Release file : https://host/group/project/-/releases/V1.2.3/downloads/<asset>

Both are derived from the remote without an API call, which is what lets verify print
the same pair for a release published days ago, and why the run record carries them.
A remote with no link shape - a local path, say - contributes nothing and prints
nothing, rather than a URL that 404s.

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
   unless the config sets hook.mode to gate. Install the hook only on request: it is
   absent in a fresh clone and stays absent unless someone asks for it.
6. Where the project's own code goes: everything the skill writes under .ci/ is
   generic, so any project-specific implementation — the build wrapper and the
   version read-back that artifact.embeddedVersion calls — belongs in .ci/lib/
   alongside the vendored modules, never loose at the .ci/ root. Two consequences
   the implementation must respect: vendor_lib() copies its modules and never clears
   .ci/lib (a rmtree there would delete the project's module on the next setup), and
   config.json reaches that module through {repo}/.ci/lib/<project>_project.py so the
   committed config still carries no host path.
7. Never commit a host path. .ci/config.json is shared by every clone, so it may
   name the build tools only through the {qmake}, {make} and {makeBin} tokens and
   may reach the repository only through {repo}. Anything bound to one machine —
   a toolchain location, an interpreter path, a home directory — belongs in
   .ci/config.local.json, which is git-ignored and regenerated per machine by
   setup. The rule covers every committed CI file, not only the config: the hook
   and the .ci/release.bat console both resolve their interpreter from PATH (or
   PRP_PYTHON) at run time, so no interpreter path is ever baked into either. The
   portability gate scans .ci/config.json, every file under .ci/hooks/ and the
   console, and refuses a committed CI file carrying an absolute host path before
   anything is built, because it would either fail on every other clone or
   silently build with whatever toolchain that host happens to have.
8. A run describes itself with what it produced. release records a build, verify
   records a re-check of someone else's, so the run record has to render the fields the
   run actually has and name the ones that are absent. Render a record from the fields
   the run actually produced rather than indexing the release shape: a verification
   that succeeds must not die with a KeyError while writing its own record.

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
- setup has to survive being re-run from the vendored copy. There, .ci/lib is both the
  source and the destination of the vendor step, so copying a module onto itself must
  count as "already in place": shutil.copyfile answers that with SameFileError, and the
  old code let it abort setup half way through - after the config was validated and
  before the console was written. The console templates have to travel with the runtime
  for the same reason, since a clone re-runs setup from .ci/lib and setup looks for the
  template next to itself.
- The push hook is off by default, and that is a property of git, not a second
  switch: .git/hooks/ is per-clone and never committed, so a fresh clone has no hook
  and will not get one unless someone asks. Setup must not install it silently, and
  the manual console must never need it. Turning it on is an explicit act - the
  console's menu and `hook on` are the same code path - and turning it off must
  leave a hook the skill did not write completely alone rather than replacing or
  deleting it.
- A menu that fires its default action on empty input is a trap, and a menu that
  re-reads stdin after EOF spins forever. Read the choice, treat an empty read or a
  `set /p` errorlevel as "no choice" rather than as the default, and bound the number
  of consecutive empty reads before quitting. `set /p` is also not a line reader when
  stdin is redirected: it can hand back several lines at once, and a value with an
  embedded newline makes the next `if "%VAR%"==...` a multi-line statement that cmd
  rejects with "The syntax of the command is incorrect."
- Capturing a quoted interpreter with `for /f` in a .bat silently yields nothing:
  when the inner command line starts with a quote, cmd strips its first and last
  quote, so `for /f ... in ('"%PY%" "%ENTRY%" hook-status')` returns an empty string
  while the same line without quotes works. Send the output through a temp file
  instead - that also survives an interpreter path containing spaces. And compare the
  state it prints case-insensitively: the query prints lowercase, and a menu that
  compares uppercase simply prints nothing at all.
- Committed CI files have to survive the console and the platform. Keep every message a build step prints ASCII: CMake and Ninja write raw UTF-8 into a legacy code page such as cp936 or cp1252 and the transcript becomes mojibake, while Python's console API is unaffected. Pin line endings too: .ci/hooks/pre-push is executed by MSYS bash under Git for Windows and a CRLF copy does not run, while a CRLF-sensitive .bat or .cmd breaks when core.autocrlf rewrites it, so .gitattributes should force eol=lf for the hook, *.sh and *.py and eol=crlf for *.bat and *.cmd. The same reasoning explains why the default .ci/release.bat is ASCII: a non-ASCII console is only correct together with the code page that matches it, so the Chinese copy is GBK *and* starts with chcp 936, and the two have to be changed together.

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
- .ci/lib/ — the vendored runtime, so a clone works without this skill installed.
  Also where the adopting project keeps its own build and version read-back module:
  see Required behavior, "Where the project's own code goes"
- .ci/hooks/pre-push — the hook source, installed into .git/hooks by install-hook
- .ci/release.bat — the double-clickable manual console; resolves an interpreter from
  PATH and forwards to .ci/lib/run_pipeline.py, so no path is baked into it. setup
  copies it byte for byte from templates/console-en.bat (ASCII, default) or
  templates/console-zh.bat (GBK with chcp 936, --console-lang zh), which are checked in
  as a real .bat per language rather than assembled from a string at run time -
  templates/*.bat is pinned `-text` so no checkout rewrites them
- .ci/out/<run>/ — per-run build log, release notes and provenance manifest
