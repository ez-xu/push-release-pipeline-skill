# What each gate checks

Every gate refuses rather than proceeds. A refusal exits 2 and publishes nothing. A
failure after the tag exists exits 1 and rolls back.

## preconditions

Not a git work tree; the config is missing or incomplete; the remote does not exist;
the release CLI is absent; the branch is not the release branch. Also refuses before
the build when the release interface cannot support verification — see the
release_api contract.

## config portability

No committed CI file may contain a host path: a Windows drive path, a UNC path, an
absolute POSIX path, a home-relative ~, $HOME or %USERPROFILE%. Such a value means the
repository only works on the machine that wrote it, so the gate refuses and names the
offending field or line together with the file to move it to. Both .ci/config.json and
every file under .ci/hooks/ are checked — a hook with the setup machine's interpreter
baked in is exactly as unshippable as a config with that machine's compiler.

The check reads the committed file, never the merged view, because a local overlay is
precisely where such values are supposed to live. It runs before the build, so a config
that would fail on another machine never produces an artifact that looks releasable.
The build working directory is created if a fresh clone does not have it yet.

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

The asset name must be ASCII: GitLab answers 400 Filepath is in an invalid format for a non-ASCII filepath, and the rollback then deletes the tag. Once the release exists the pipeline also rewrites the uploaded asset's link URL - glab 1.52 omits the project namespace, which makes the asset unreachable - and the read-back downloads through that link, so what is verified is the bytes a consumer receives.

## closed-loop read-back

Re-reads the remote tag and requires it still to resolve to the built commit, then
downloads the published asset back and compares SHA-256 against the local artifact.
Only when both match is the release reported as successful.

Success here is judged from the downloaded bytes, never from an HTTP status. On a private
instance the asset is not anonymously reachable, and the refusal is quiet: an
unauthenticated GET of the asset URL can answer 200 with the sign-in page, while the API
route answers 401 or 404 for the same asset. A read-back that trusted the status code
would accept a login page as a successful download.

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
