# What each gate checks

Every gate refuses rather than proceeds. A refusal exits 2 and publishes nothing. A
failure after the tag exists exits 1 and rolls back.

## preconditions

Not a git work tree; the config is missing or incomplete; the remote does not exist;
the release CLI is absent; the branch is not the release branch. Also refuses before
the build when the release interface cannot support verification — see the
release_api contract.

## release interface

Loads the registered release_api contract and requires a usable report. It probes
that the provider CLI exists, is authenticated, and exposes create, download and
delete. Download matters most: without it the closed-loop check cannot run, so the
pipeline stops before spending a build on a release it could not verify.

## clean tree

git status --porcelain must be empty. A release built from a dirty tree cannot be
traced to a commit, so the tree has to be clean — including the .ci directory the
pipeline itself lives in. Commit it before the first automatic release.

## identity snapshot and drift guard

Before the build the pipeline records HEAD, HEAD^{tree}, a SHA-256 over git ls-files
-s, and the porcelain status. After the build it records them again and compares.
Any difference means the artifact cannot be tied to the commit that was pushed, so
the run is refused and the difference is printed.

## time guard

A build that rewrites a tracked file with byte-identical content leaves the manifest
unchanged. The pipeline therefore also snapshots every tracked file's mtime in
nanoseconds immediately before the build and compares afterwards. Any file whose
mtime moved is reported, unless it is listed in guard.mutableTrackedPaths.

A wall-clock threshold is deliberately not used: it reports false positives for a
file that merely happened to be saved a moment before the pipeline started.

## version cross-check

The version is read from the artifact file name by artifact.versionRegex and never
recomputed from the build system. When artifact.embeddedVersion is configured, the
binary's own version resource must agree. Disagreement is refused, because the tag
would otherwise name a binary that contradicts it.

## tag occupancy

The tag is resolved locally and remotely, dereferencing annotated tags to a commit
on both sides. If it already exists at this commit the run reports that nothing needs
publishing and exits 0. If it exists at any other commit the run is refused: a
published tag is never moved, and the message names the version to raise.

## publish

Creates the annotated tag locally, pushes it, confirms the remote tag resolves to
this commit, and only then creates the release with an explicit ref. The order
matters: GitLab's release CLI creates the tag from the default branch when the named
tag does not exist, which would attach the release to a commit nobody built.

## closed-loop read-back

Re-reads the remote tag and requires it still to resolve to the built commit, then
downloads the published asset back and compares SHA-256 against the local artifact.
Only when both match is the release reported as successful.

## rollback

Runs when anything fails after the tag exists. Deletes the release, the remote tag
and the local tag, then reports the next push starts clean. Success is judged from
each command's exit code, and any step that failed is listed for manual cleanup.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | published, or nothing to publish |
| 2 | refused; nothing was published and the repair is named |
| 1 | a partial publication was attempted and rolled back |

From the pre-push hook, a non-zero result blocks the push only when hook.mode is
gate. Otherwise the push proceeds and the failure is reported.
