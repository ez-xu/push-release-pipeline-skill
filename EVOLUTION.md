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

