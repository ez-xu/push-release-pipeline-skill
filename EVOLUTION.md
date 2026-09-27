# Evolution log

Appended automatically by scripts/run_evals.py (and scripts/evolve.py) when a check fails. Each entry is the raw evidence for a fix/regenerate step.

## 2026-09-23T11:36:24Z — correction from use

Change ID: `correction-20260923-113624-fe2c076b3b`

Reported while using the skill, not caught by any automated check.

> committing a host path into .ci/config.json: the repository is cloned on other machines, so an absolute toolchain path either fails there or silently builds with the wrong toolchain. Name build tools with {qmake}/{make}/{makeBin}; keep every host-specific value in the git-ignored .ci/config.local.json.

Proposed skill edit: add the corrected behavior to `SKILL.md` → `## Gotchas`.

Regression test: `evals/corrections/correction-20260923-113624-fe2c076b3b.json` must keep this behavior in the skill.

Version recommendation: patch — correction from real use.

## 2026-09-23T11:53:08Z — correction from use

Change ID: `correction-20260923-115308-f6bb7b7fa6`

Reported while using the skill, not caught by any automated check.

> baking an interpreter path into .ci/hooks/pre-push: the hook is committed too, so an absolute path pins it to the machine that ran setup and silently skips the pipeline on every other clone. The template resolves PRP_PYTHON, python3, python and py from PATH at run time, and the portability gate scans every file under .ci/hooks/ as well as .ci/config.json.

Proposed skill edit: add the corrected behavior to `SKILL.md` → `## Gotchas`.

Regression test: `evals/corrections/correction-20260923-115308-f6bb7b7fa6.json` must keep this behavior in the skill.

Version recommendation: patch — correction from real use.


## 2026-09-24T07:20:00Z - correction from use

Change ID: `correction-20260924-072000-e2dfe29d63`

Reported while using the skill, not caught by any automated check.

> GitLab refuses a release asset whose filepath is not ASCII: the assets-links call answers 400 Filepath is in an invalid format, and the run then rolls back and deletes the tag, so the push leaves no tag and no file behind. A tag may carry non-ASCII, but an asset name is a filepath, so the published asset must be ASCII, and the version read back out of the binary has to use the same ASCII transliteration or the version cross-check refuses the release. A product whose canonical firmware name is Chinese keeps that name for customers: the build command copies it to an ASCII-named file in the directory artifact.glob watches, byte for byte, and release.assetLabel is not the fix - the implementation names the asset after the artifact file, never after that key.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-072000-e2dfe29d63.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:20:00Z - correction from use

Change ID: `correction-20260924-072000-277a163384`

Reported while using the skill, not caught by any automated check.

> A created release can be unusable even though every step reported success: glab 1.52 records the uploaded file's link URL without the project namespace (https://host/-/project/<id>/uploads/<secret>/<name>), and GitLab's asset download route redirects to exactly that URL, so the asset 404s for every consumer and for the pipeline's own read-back. Rewrite the link to the API uploads route (/api/v4/projects/<id>/uploads/<secret>/<name>) before the read-back, idempotently, and fetch the read-back through the route a consumer clicks rather than through a copy obtained another way.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-072000-277a163384.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:45:00Z - correction from use

Change ID: `correction-20260924-074500-3e3e314242`

Reported while using the skill, not caught by any automated check.

> build.clean patterns are pathlib globs, and pathlib's dir/** matches directories only, so a pattern such as build/** deletes nothing while reporting removed 0 file(s) and a stale artifact then survives into the next build. Write dir/**/* (or name the files explicitly), and read removed 0 file(s) as a signal to check the pattern rather than as proof of a clean tree.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-074500-3e3e314242.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:45:00Z - correction from use

Change ID: `correction-20260924-074500-9129a81362`

Reported while using the skill, not caught by any automated check.

> A build that can run on a tree it did not clean must pick the artifact as the file that did not exist before the build, never as the only file it happens to find: a wrapper that assumes an empty output directory turns one surviving file into the pipeline's ambiguity refusal (N artifacts matched <glob>; the version would be ambiguous). Report how many were seen before and after, and point at build.clean when the selection is not exactly one.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-074500-9129a81362.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:45:00Z - correction from use

Change ID: `correction-20260924-074500-3d37ca89cc`

Reported while using the skill, not caught by any automated check.

> Two things in the config look like levers and are not. {artifactPath} is not a token: only {repo}, the toolchain tokens, {PATH}/{pathsep} in build.env and the release-side tokens in tag.template and release.name are expanded, so a command argument asking for {artifactPath} receives that literal text and the command must locate the artifact itself through artifact.root and artifact.glob. release.assetLabel is written by setup and read by nothing: the published asset is always named after the artifact file, so an ASCII artifact file name is the only way to choose it.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-074500-3d37ca89cc.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:45:00Z - correction from use

Change ID: `correction-20260924-074500-9d38a1e11d`

Reported while using the skill, not caught by any automated check.

> A dry run is not a rehearsal of publishing. release --dry-run stops before the tag is created, so it cannot reach the upload, the asset link or the read-back, and a repository can pass a dry run and still fail its first real release. Only a real run, or verify against a release that already exists, covers that path.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-074500-9d38a1e11d.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:45:00Z - correction from use

Change ID: `correction-20260924-074500-1ba4fab450`

Reported while using the skill, not caught by any automated check.

> On a private instance a release asset is not anonymously reachable, and the refusal is quiet: an unauthenticated GET of the asset URL can answer 200 with the sign-in page, while the API route answers 401 or 404. A read-back that judges by status code accepts a login page as a successful download, so it must compare the bytes (size and SHA-256) and never the status.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-074500-1ba4fab450.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T07:45:00Z - correction from use

Change ID: `correction-20260924-074500-3e7449d856`

Reported while using the skill, not caught by any automated check.

> Committed CI files have to survive the console and the platform. Keep every message a build step prints ASCII: CMake and Ninja write raw UTF-8 into a legacy code page such as cp936 or cp1252 and the transcript becomes mojibake, while Python's console API is unaffected. Pin line endings too: .ci/hooks/pre-push is executed by MSYS bash under Git for Windows and a CRLF copy does not run, while a CRLF-sensitive .bat or .cmd breaks when core.autocrlf rewrites it, so .gitattributes should force eol=lf for the hook, *.sh and *.py and eol=crlf for *.bat and *.cmd.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-074500-3e7449d856.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T08:30:00Z - correction from use

Change ID: `correction-20260924-083000-2089b27391`

Reported while using the skill, not caught by any automated check.

> A pipeline that re-lists the build commands duplicates the project's own build script, and the two drift: the release then builds something the developer never ran. When the repository already has a build entry point (build.bat, a Makefile, a script), leave build.configure empty and call that entry from build.build, passing the pipeline's isolation through environment variables or extra arguments the script already honours. Keep one source of truth for the directories as well - a thin wrapper can derive its build directory from artifact.root instead of repeating it.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-083000-2089b27391.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T08:30:00Z - correction from use

Change ID: `correction-20260924-083000-a3b1d68a31`

Reported while using the skill, not caught by any automated check.

> Deciding "the artifact this build produced" by file name alone breaks on a rebuild that produces the same name: the same commit on the same day yields a byte-identical file with an identical name, so a name-based diff reports zero new files and the run stops on a complete build. Treat a file as this build's output when it did not exist before the build or its mtime is not older than the build start, and require exactly one such file.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-083000-a3b1d68a31.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-24T12:00:00Z - correction from use

Change ID: `correction-20260924-200000-a1b2c3d4`

Reported while using the skill, not caught by any automated check.

> Project-specific pipeline code had nowhere to live, so it ended up as loose scripts at the .ci/ root. Put it in .ci/lib/ instead, next to the vendored runtime: vendor_lib() copies its own modules and never clears the directory, so a project module placed there survives re-running setup, while a file at the .ci/ root is neither protected nor obviously the project's. config.json then reaches it as {repo}/.ci/lib/<project>_project.py, which keeps the committed config free of host paths. The same change adds the double-clickable console at .ci/release.bat: setup writes it, it is ASCII and CRLF, and it resolves its interpreter from PATH at run time so the committed file works in every clone.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Required behavior` (rule 6, where the project's own code goes).

Regression test: `evals/corrections/correction-20260924-200000-a1b2c3d4.json` must keep this behavior in the skill.

Version recommendation: minor - adds a file the skill writes and a rule about where project code lives.

## 2026-09-24T12:05:00Z - correction from use

Change ID: `correction-20260924-200000-b2c3d4e5`

Reported while using the skill, not caught by any automated check.

> A .bat menu has three failure modes that do not show up until someone double-clicks it. Capturing a quoted interpreter with for /f returns an empty string, because cmd strips the first and last quote of an inner command line that starts with a quote - the same line unquoted works, and a temp file works for both. The hook state must be compared case-insensitively, because the query prints lowercase and a menu comparing uppercase prints no state line at all. And empty input must not mean the default action: set /p can hand back several lines when stdin is redirected (a value with an embedded newline makes the next if a multi-line statement cmd rejects), an exhausted stdin would otherwise spin the menu forever, and a menu whose default is 'publish' would fire it on a stray Enter.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260924-200000-b2c3d4e5.json` must keep this behavior in the skill.

Version recommendation: minor - adds a user-facing entry point and the failure modes it must avoid.

## 2026-09-27T10:05:00Z - correction from use

Change ID: `correction-20260927-100500-c3d4e5f6`

Reported while using the skill, not caught by any automated check.

> A successful verify crashed while writing its own record. verify records a subset of what release records, but the run record renderer indexed project, tree, branch, size and versionSource directly, so the re-check died with KeyError: 'project' after the read-back had already run - and because the crash happened before the final print, the command returned a traceback instead of the result. Render a record from the fields the run actually produced, and say which are not recorded rather than assuming the release shape; a verification that succeeds must not fail while describing itself.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Required behavior` (rule 8, a run describes itself with what it produced).

Regression test: `evals/corrections/correction-20260927-100500-c3d4e5f6.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.

## 2026-09-27T10:06:00Z - correction from use

Change ID: `correction-20260927-100500-d4e5f6a7`

Reported while using the skill, not caught by any automated check.

> A release that does not hand over its own URL makes everyone reconstruct it by hand from the tag, and the reconstruction is easy to get wrong (the browser route wants real slashes while the API route wants the project path percent-encoded, so using the API form in a link produces a URL that cannot be clicked). Print the release page and the direct link to the published file at the end of both a real release and a verify, derive both from the remote without an API call so a re-check prints the same pair, record them in the run, and print nothing for a remote with no link shape rather than a URL that 404s.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Handing over the link`.

Regression test: `evals/corrections/correction-20260927-100500-d4e5f6a7.json` must keep this behavior in the skill.

Version recommendation: minor - adds a user-facing output to release and verify.

## 2026-09-27T11:00:00Z - correction from use

Change ID: `correction-20260927-110000-e5f6a7b8`

Reported while using the skill, not caught by any automated check.

> setup ran from the vendored copy - which is exactly how a colleague re-runs it after cloning, and what the docs tell them to type - aborted with shutil.SameFileError: .ci/lib is both the source and the destination of the vendor step, so copying a module onto itself is the normal case there, not an error. The crash landed after the config step and before the console was written, so the run looked half-done for no reason. Treat 'already in place' as success, and let the console templates travel with the runtime, because setup looks for the template next to itself and a clone has no copy of the skill.

Proposed skill edit: add the corrected behavior to `SKILL.md` -> `## Gotchas`.

Regression test: `evals/corrections/correction-20260927-110000-e5f6a7b8.json` must keep this behavior in the skill.

Version recommendation: patch - correction from real use.
## 2026-09-27T02:36:13Z — run_evals --rollout FAILED

- counts: passed=17, failed=30, errors=0, regressions=0, judge_failed=0
- failing checks (raw):

```json
[
  {
    "case": "clean-release",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "scenario-identified",
    "status": "fail"
  },
  {
    "case": "dirty-tree-refused",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "dirty-tree-refused",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "dirty-tree-refused",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "dirty-tree-refused",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "dirty-tree-refused",
    "criterion": "scenario-identified",
    "status": "fail"
  },
  {
    "case": "version-collision-refused",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "version-collision-refused",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "version-collision-refused",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "version-collision-refused",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "version-collision-refused",
    "criterion": "scenario-identified",
    "status": "fail"
  },
  {
    "case": "tracked-file-touched-refused",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "tracked-file-touched-refused",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "tracked-file-touched-refused",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "tracked-file-touched-refused",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "tracked-file-touched-refused",
    "criterion": "scenario-identified",
    "status": "fail"
  },
  {
    "case": "host-path-config-refused",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "host-path-config-refused",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "host-path-config-refused",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "host-path-config-refused",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "host-path-config-refused",
    "criterion": "scenario-identified",
    "status": "fail"
  },
  {
    "case": "corrupted-upload-rolled-back",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "corrupted-upload-rolled-back",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "corrupted-upload-rolled-back",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "corrupted-upload-rolled-back",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "corrupted-upload-rolled-back",
    "criterion": "scenario-identified",
    "status": "fail"
  }
]
```

## 2026-09-27T02:37:20Z — run_evals --rollout FAILED

- counts: passed=17, failed=5, errors=0, regressions=0, judge_failed=0
- failing checks (raw):

```json
[
  {
    "case": "clean-release",
    "criterion": "harness-ran",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "closed-loop-consistent",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "no-orphan-tag",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "provenance-complete",
    "status": "fail"
  },
  {
    "case": "clean-release",
    "criterion": "scenario-identified",
    "status": "fail"
  }
]
```

