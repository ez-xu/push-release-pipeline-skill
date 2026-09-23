# Adopting this on a team

## The pipeline lives in the repository

setup copies the runtime into .ci/lib and writes .ci/config.json and
.ci/hooks/pre-push. Commit all three. A colleague who clones the repository then has
the whole pipeline, without installing this skill, and installs the hook locally
with:

```bash
python3 .ci/lib/run_pipeline.py install-hook --repo .
```

The hook itself is not committed: .git/hooks is local state, and copying it around
would silently overwrite other hooks.

## What each person needs

| Requirement | Why |
|---|---|
| git 2.40 or newer | hook behaviour and peeled tag listings |
| python 3.9 or newer | the vendored runtime, standard library only |
| glab or gh, authenticated | the pipeline refuses before building when it is missing |
| the project build toolchain | the configured build.build must run |

The hook picks an interpreter by trying the one baked in at setup time first, then
python3, python and py, skipping the Microsoft Store stub that resolves under
WindowsApps. Nothing has to be on PATH as long as one of those works.

## Reviewing the config as a team

.ci/config.json is the contract between the repository and the release process, so
treat changes to it as reviewable:

- artifact.glob must keep matching exactly one file
- artifact.versionRegex must keep exposing the version
- guard.mutableTrackedPaths should stay empty unless a build genuinely regenerates a
  tracked file
- hook.mode decides whether a broken pipeline blocks everyone's pushes

## Choosing hook.mode

release, the default, never blocks a push. A version collision or an unreachable
provider is not a reason to refuse someone's code, and the failure is printed in
full. gate makes the pipeline a hard gate: the push is aborted when the release does
not succeed. Choose gate only where publishing is genuinely a precondition for
merging.

## Sharing the skill itself

The pipeline in .ci is enough to run releases. This skill adds the ability to adopt
the pipeline into a new repository, diagnose a refusal, and re-verify a published
release without rebuilding.

```bash
git clone <url> ~/.claude/skills/push-release-pipeline-skill
```

## Re-verifying an old release

Anyone with the repository and provider access can re-check a published release
without building anything:

```bash
python3 .ci/lib/run_pipeline.py verify --repo . --tag V1.0.14.631
```

That re-reads the remote tag and re-downloads the asset, and reports whether it still
matches the version recorded in that run's manifest.
