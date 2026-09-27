# push-release-pipeline-skill

Turn a local git push into a release whose artifact is provably built from the
commit that was pushed. Ten gates refuse rather than publish whenever that proof is
missing, and a failed publication is rolled back.

## Install

Claude Code, through the plugin marketplace:

```bash
/plugin marketplace add <path-or-url-to-this-skill>
```

Any other tool, by cloning into that tool's native skills directory:

```bash
git clone <url> ~/.claude/skills/push-release-pipeline-skill    # Claude Code
git clone <url> ~/.codex/skills/push-release-pipeline-skill    # Codex CLI
git clone <url> ~/.cursor/rules/push-release-pipeline-skill    # Cursor
```

Or run the bundled installer, which detects the platform and places the skill
correctly:

```bash
./install.sh
```

## Use

```bash
python3 scripts/run_pipeline.py setup --repo /path/to/repo --install-hook
```

Then every push to the release branch builds, verifies, tags, publishes, and
re-downloads the published asset to confirm it matches the build. A successful
release - and a later `verify` - prints the release page and the direct link to the
published file.

The hook is off until someone installs it. To publish by hand instead, double-click
the console setup writes at `.ci/release.bat`: it opens a menu (check, release, dry
run, verify, and turning the push hook on or off) and needs no command line. It is
written in English by default; add `--console-lang zh` to setup for a Chinese copy.
Both consoles are checked in under `templates/` and copied byte for byte, so what a
repository gets is exactly the file reviewed here.

## Verification

[VERIFICATION.md](VERIFICATION.md) records the latest gate and rollout evidence.
