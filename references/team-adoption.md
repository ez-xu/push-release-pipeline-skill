# Adopting this on a team

## The pipeline lives in the repository

setup copies the runtime into .ci/lib and writes .ci/config.json,
.ci/hooks/pre-push and the .ci/release.bat console. Commit those four. A colleague
who clones the repository then has the whole pipeline, without installing this skill,
and installs the hook locally with:

```bash
python3 .ci/lib/run_pipeline.py install-hook --repo .
```

The hook itself is not committed: .git/hooks is local state, and copying it around
would silently overwrite other hooks.

## What is committed and what is local

| Path | Committed | Why |
|---|---|---|
| .ci/config.json | yes | the shared contract; must contain no host path |
| .ci/lib/ | yes | so a clone runs the pipeline without this skill; also holds the project's own build and read-back module. The console templates are vendored here too, so setup can be re-run from the clone |
| .ci/hooks/pre-push | yes | the hook source, installed into .git/hooks per machine |
| .ci/release.bat | yes | the double-clickable console; publishes without a push |
| .ci/config.local.json | **no** | this machine's toolchain pin; git-ignored, written by setup |

The committed config names the build tools by token ({qmake}, {make}, {makeBin}), so
each clone resolves its own installation. Never commit the local overlay: it holds
absolute paths that are meaningless anywhere else, and the portability gate refuses a
committed config that carries one. A teammate who clones the repository needs this
much and no more:

```bash
python3 .ci/lib/run_pipeline.py check --repo .     # resolves the toolchain and reports
```

## What each person needs

| Requirement | Why |
|---|---|
| git 2.40 or newer | hook behaviour and peeled tag listings |
| python 3.9 or newer | the vendored runtime, standard library only |
| glab or gh, authenticated | the pipeline refuses before building when it is missing |
| the project build toolchain | the configured build.build must run |

The hook resolves an interpreter at run time from PRP_PYTHON, then python3, python
and py, skipping the Microsoft Store stub that resolves under WindowsApps. Nothing
has to be on PATH as long as one of those works. No interpreter path is baked in:
the hook is committed, so an absolute path would pin it to the machine that ran
setup and silently skip the pipeline everywhere else.

## Reviewing the config as a team

.ci/config.json is the contract between the repository and the release process, so
treat changes to it as reviewable:

- artifact.glob must keep matching exactly one file
- artifact.versionRegex must keep exposing the version
- guard.mutableTrackedPaths should stay empty unless a build genuinely regenerates a
  tracked file
- hook.mode decides whether a broken pipeline blocks everyone's pushes

## The colleague who does not use a shell

Not everyone on a release team wants a command line, and the hook is deliberately not
installed for them. Point them at .ci/release.bat: double-clicking it opens a menu
(check, release, dry run, verify, and turning the push hook on or off) and pauses so
the result stays on screen. It is ASCII-only and CRLF, and it resolves its interpreter
from PATH at run time, so the same committed file works on every clone.

Nothing in that path needs the hook, so a release operator can ship a build on a
machine where nobody ever pushes.

The console is English and ASCII by default, which displays correctly on any code
page. For a team that wants it in Chinese, generate it that way:

```bash
python3 .ci/lib/run_pipeline.py setup --repo . --console-lang zh
```

Same console, only the display strings differ: the Chinese copy is written as GBK and
starts with `chcp 936`, so the file bytes and the console code page agree. Keep
`*.bat` pinned to `eol=crlf` in .gitattributes either way - cmd refuses a LF-only
batch file, and a checked-out copy that lost its CRLF looks like a broken console
rather than a line-ending problem.

## Choosing hook.mode

release, the default, never blocks a push. A version collision or an unreachable
provider is not a reason to refuse someone's code, and the failure is printed in
full. gate makes the pipeline a hard gate: the push is aborted when the release does
not succeed. Choose gate only where publishing is genuinely a precondition for
merging.

## Exercising the publish path before trusting it

A dry run stops before the tag exists, so the upload, the asset link and the read-back are
first exercised by a real release. Test that path without publishing anything permanent by
using a throwaway tag:

```bash
git tag -a _probe -m probe <sha> && git push origin refs/tags/_probe
glab release create _probe probe.bin --name _probe --ref <sha> --no-update
glab release download _probe --asset-name probe.bin --dir <tmp>   # must return the bytes
glab release delete _probe --yes
git push origin :refs/tags/_probe && git tag -d _probe
```

The hook only reacts to refs/heads/*, so a tag-only push starts no release. Use an ASCII
tag and an ASCII file name: a probe that breaks on a naming rule proves nothing about a
release that would break on it too. Confirm the cleanup with git ls-remote --tags.

When the release and the asset both exist but the download fails, read the link back
before assuming an access problem:

```bash
glab api projects/<url-encoded-path>/releases/<tag>
```

A link whose url is missing the project namespace (https://host/-/project/<id>/uploads/...)
cannot be downloaded by anyone, the pipeline included, because GitLab's asset download
route redirects to exactly that URL.

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
