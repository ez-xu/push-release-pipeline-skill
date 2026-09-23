# push-release-pipeline-skill

Make a push produce a release that can be proven to come from the commit that was
pushed. The pipeline refuses rather than publishes when that proof is missing.

## Activation

Use it when a repository should compile, tag and publish an artifact automatically
from a push, or when a published tag must never disagree with the file attached to
it. Chinese triggers: 本地推送自动编译发布, 推送自动出包, 自动打标签发布.
English triggers: push-triggered release, tag and artifact must match, closed-loop
release verification, release integrity pipeline.

Do not use it to publish a release by hand, to choose a new version number, or to
repair a tag that is already published.

## Usage

Adopt the pipeline into a repository, review the generated config, then install the
hook:

```bash
python3 scripts/run_pipeline.py setup --repo <REPO> --install-hook
```

Inspect without changing anything, and rehearse without publishing:

```bash
python3 scripts/run_pipeline.py check   --repo <REPO> --json
python3 scripts/run_pipeline.py release --repo <REPO> --dry-run
python3 scripts/run_pipeline.py verify  --repo <REPO> --tag <TAG>
```

Exit codes: 0 success or nothing to do, 2 refused with nothing published, 1 a
partial publication that was rolled back.

## Gotchas

- GitLab's release CLI creates the tag from the default branch when the named tag
  does not exist, so the release could point at a commit nobody built. Always push
  the tag first and pass an explicit ref.
- An annotated tag is two objects; asking git for the tag returns the tag object,
  not the commit. Dereference to a commit for every comparison, including the
  peeled line in the remote listing.
- shutil.which honours PATHEXT but the Windows process launcher does not, so a
  detected glab.cmd shim can be skipped in favour of a different glab.exe. Resolve
  the CLI to an absolute path and invoke that.
- Importing the vendored modules creates __pycache__ and dirties the tree, which
  the pipeline's own clean-tree gate then refuses. Bytecode writing is disabled.
- Under Git for Windows the hook runs under MSYS bash and git prints POSIX paths
  that native Python cannot open. Resolve the repository root from Python.
- A directory-only ignore entry such as .ci/out/ does not match a path that does
  not exist yet.
- Git has no post-push hook, so the release runs before the branch lands.

## Full detail

Read SKILL.md for the gate table, the required behavior, and the repository files
the skill writes.
