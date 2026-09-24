# Configuration reference

The pipeline reads two files, both under .ci/.

| File | Committed? | Holds |
|---|---|---|
| .ci/config.json | yes | everything that means the same thing in every clone |
| .ci/config.local.json | no — git-ignored | what only this machine can know: where its toolchain lives |

setup writes a first draft of both and prints every inference it made. Review the
committed one, fix anything wrong, and commit it — it is part of the repository, not
local state. The local one is regenerated on each machine and never reviewed.

## The hard rule: no host paths in any committed CI file

.ci/config.json is read by every clone, so a path that exists on your machine is a
config that only builds on your machine. It either fails on a colleague's clone or,
worse, quietly builds with whatever toolchain that host happens to have.

The committed file therefore names the build tools by token and reaches the
repository through {repo}; anything host-specific goes into the local overlay. The
portability gate enforces this and refuses a committed config that contains an
absolute host path (a drive path, a UNC path, an absolute POSIX path, ~, $HOME or
%USERPROFILE%), naming the exact field and the file to move it to.

The same rule covers .ci/hooks/pre-push, which is committed too. It resolves an
interpreter from PRP_PYTHON, python3, python and py at run time; setup deliberately
does not bake the interpreter it ran under into the file, because that path exists
only on the machine that ran setup and the hook would silently skip the pipeline
everywhere else. The gate scans every file under .ci/hooks/ and names the line.

## Full shape

```json
{
  "schemaVersion": 1,
  "project": { "name": "BMSSystem", "releaseBranch": "main" },
  "remote": "origin",
  "outputDir": ".ci/out",
  "build": {
    "cwd": "bms/build/Desktop_Qt_5_15_2_MinGW_32_bit-Release",
    "clean": ["bms/**/*.o", "bms/Makefile", "bms/Makefile.*"],
    "configure": ["{qmake}", "{repo}/bms/BMSSystem.pro"],
    "build": ["{make}", "-j4"],
    "env": { "PATH": "{makeBin}{pathsep}{PATH}" },
    "timeoutSeconds": 3600
  },
  "artifact": {
    "root": "bms/build/Desktop_Qt_5_15_2_MinGW_32_bit-Release/bms",
    "glob": "BMSSystem_V*.exe",
    "versionRegex": "_V(?P<version>[0-9]+(?:\\.[0-9]+)+)\\.exe$",
    "embeddedVersion": { "kind": "pe-file-version" }
  },
  "tag": { "template": "V{version}" },
  "release": { "provider": "auto", "name": "{tag}" },
  "verify": { "readBack": true, "rollbackOnFailure": true },
  "guard": { "mutableTrackedPaths": [] },
  "hook": { "mode": "release" }
}
```

## Fields

| Field | Meaning |
|---|---|
| project.name | used in the release notes only |
| project.releaseBranch | the only branch the pipeline will release from; override per run with --any-branch |
| remote | the git remote to push tags to and read tags back from |
| outputDir | where per-run records go; must be git-ignored, and setup adds it |
| build.cwd | working directory for the build steps, relative to the repository root |
| build.clean | globs removed before configuring, relative to the repository root; pathlib semantics, so dir/** matches directories only — use dir/**/* to delete files |
| build.configure | the configure step, as a list of arguments or a single string. If the repository already has a build script its developers run, prefer leaving this empty and calling that script from build.build, so the pipeline and the developer run one recipe instead of two that drift |
| build.build | the compile step; a non-zero exit refuses the release. Calling the project's own build entry is fine and preferred; give it the pipeline's output directory through an environment variable or an argument it already honours |
| build.env | environment overrides for the configure and build steps; {PATH} and {pathsep} expand from the caller's environment, {makeBin} is the directory of the resolved {make} |
| build.timeoutSeconds | per-step timeout, default 3600 |
| artifact.root | directory the produced artifact lands in, relative to the repository root. Keep it to the one file that gets published: a second, differently named copy — an ASCII-named copy of a non-ASCII product name, for instance — belongs in its own directory, or artifact.glob matches both and the release is refused as ambiguous |
| artifact.glob | must match exactly one file after a clean build |
| artifact.versionRegex | a pattern with a named version group, applied to the artifact file name |
| artifact.embeddedVersion | how to read the version out of the binary itself; see below |
| tag.template | the tag name; must contain {version} |
| release.provider | auto, gitlab or github; auto decides from the remote URL |
| release.name | the release title template |
| release.assetLabel | accepted and ignored. The published asset is always named after the artifact file, so an ASCII artifact file name is the only way to choose it. |
| verify.readBack | whether to re-download and compare the published asset |
| verify.rollbackOnFailure | whether to delete the tag and release a failed run created |
| guard.mutableTrackedPaths | tracked files the build is allowed to rewrite |
| hook.mode | release (never block the push) or gate (block it when the pipeline fails) |

## Template tokens

Any of these may appear in tag.template, release.name and the command arguments:
{repo}, {version}, {tag}, {project}, {artifactName}, {commit}, {branch}.

build.env values additionally expand {PATH} and {pathsep}, so an override extends the
caller's PATH instead of replacing it.

### Toolchain tokens

Three tokens resolve to this machine's toolchain at run time, which is what keeps the
committed config portable:

| Token | Resolves to |
|---|---|
| {qmake} | the Qt qmake executable |
| {make} | mingw32-make, or make |
| {makeBin} | the directory containing {make} — where the compiler sits |

Resolution order is the local pin (.ci/config.local.json, key toolchain.qmake /
toolchain.make), then PATH, then the usual install roots (C:/Qt, /opt/Qt, ~/Qt). An
unresolved token refuses the run and tells you which pin to write; it never silently
falls back to a different toolchain.

A token appearing literally in a value that is not a command is expanded too, so keep
{make} and friends out of artifact globs, tag templates and release names.

{artifactPath} is not one of these tokens. It appears in older examples, but nothing
expands it: a command that asks for it receives the literal text and has to find the
artifact itself.

## artifact.embeddedVersion

The default reads the PE version resource directly, with no external tool:

```json
{ "kind": "pe-file-version" }
```

It compares the fixed file version against the version in the file name and refuses
when they disagree. Set it to null to skip the cross-check, which is only reasonable
for artifacts that carry no version at all.

For anything else, supply a command whose stdout is the version:

```json
{ "command": ["python", "tools/read_version.py"] }
```

The command receives no artifact path: {artifactPath} is not a token and is not expanded. The script locates the artifact itself — reading artifact.root and artifact.glob out of .ci/config.json is the portable way, since the same script must work in every clone — prints the version on stdout, and that version must equal the one in the file name or the cross-check refuses the release.
```

## guard.mutableTrackedPaths

By default no tracked file may be written during the build. If a project legitimately
regenerates a tracked file, name it here:

```json
{ "mutableTrackedPaths": ["src/version.h"] }
```

The file is then allowed to be touched, but its content must still be identical
before and after the build — the tracked-file manifest comparison always applies.

## Which build tool

build.configure and build.build are plain argument lists, so any toolchain works — but
they must name it portably. The Qt/MinGW case is:

```json
"configure": ["{qmake}", "{repo}/bms/BMSSystem.pro"],
"build": ["{make}", "-j4"],
"env": { "PATH": "{makeBin}{pathsep}{PATH}" }
```

Neither tool is on PATH by default in a Qt Creator install, which is exactly why the
tokens exist rather than a fixed path: the token resolution finds them wherever this
machine put them, and the clone next door finds its own.

The PATH override is not optional. A qmake-generated Makefile invokes the compiler by
bare name (`g++`), so the build step also needs the compiler's own directory on PATH,
or it fails with:

```
g++: error: CreateProcess: No such file or directory
```

{makeBin} is that directory — the one holding the resolved {make} — so the override
follows the toolchain automatically and never has to be edited.

### Pinning a machine

If a host has several Qt versions and discovery would pick the wrong one, pin it. Run
setup (it writes this for you) or create the file by hand:

```json
{
  "toolchain": {
    "qmake": "C:/Qt/5.15.2/mingw81_32/bin/qmake.exe",
    "make": "C:/Qt/Tools/mingw810_32/bin/mingw32-make.exe"
  }
}
```

The local overlay is a full config overlay, not only a toolchain pin: any section or
key of .ci/config.json may be overridden there, and it is merged section by section.
This is the supported place for every host-specific value — an interpreter path in
artifact.embeddedVersion.command, a different output directory, a pinned toolchain.

### The build working directory

build.cwd is relative to the repository root, and a fresh clone will not have it yet:
build outputs are normally git-ignored. The pipeline creates a missing build.cwd before
the build, so the first push on a new machine does not fail on a directory nobody has
made yet.
