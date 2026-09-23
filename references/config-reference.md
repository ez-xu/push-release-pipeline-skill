# Configuration reference

The pipeline reads one file: .ci/config.json at the repository root. setup writes a
first draft from what it detected and prints every inference it made. Review it, fix
anything wrong, and commit it — the file is part of the repository, not local state.

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
    "configure": ["C:/Qt/5.15.2/mingw81_32/bin/qmake.exe", "{repo}/bms/BMSSystem.pro"],
    "build": ["C:/Qt/Tools/mingw810_32/bin/mingw32-make.exe", "-j4"],
    "env": { "PATH": "C:/Qt/Tools/mingw810_32/bin{pathsep}{PATH}" },
    "timeoutSeconds": 3600
  },
  "artifact": {
    "root": "bms/build/Desktop_Qt_5_15_2_MinGW_32_bit-Release/bms",
    "glob": "BMSSystem_V*.exe",
    "versionRegex": "_V(?P<version>[0-9]+(?:\\.[0-9]+)+)\\.exe$",
    "embeddedVersion": { "kind": "pe-file-version" }
  },
  "tag": { "template": "V{version}" },
  "release": { "provider": "auto", "name": "{tag}", "assetLabel": "{artifactName}" },
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
| build.clean | globs removed before configuring, relative to the repository root |
| build.configure | the configure step, as a list of arguments or a single string |
| build.build | the compile step; a non-zero exit refuses the release |
| build.env | environment overrides for the configure and build steps; {PATH} and {pathsep} expand from the caller's environment |
| build.timeoutSeconds | per-step timeout, default 3600 |
| artifact.root | directory the produced artifact lands in, relative to the repository root |
| artifact.glob | must match exactly one file after a clean build |
| artifact.versionRegex | a pattern with a named version group, applied to the artifact file name |
| artifact.embeddedVersion | how to read the version out of the binary itself; see below |
| tag.template | the tag name; must contain {version} |
| release.provider | auto, gitlab or github; auto decides from the remote URL |
| release.name | the release title template |
| verify.readBack | whether to re-download and compare the published asset |
| verify.rollbackOnFailure | whether to delete the tag and release a failed run created |
| guard.mutableTrackedPaths | tracked files the build is allowed to rewrite |
| hook.mode | release (never block the push) or gate (block it when the pipeline fails) |

## Template tokens

Any of these may appear in tag.template, release.name and the command arguments:
{repo}, {version}, {tag}, {project}, {artifactName}, {commit}, {branch}.

build.env values additionally expand {PATH} and {pathsep}, so an override extends the
caller's PATH instead of replacing it.

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
{ "command": ["python", "tools/read_version.py", "{artifactPath}"] }
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

build.configure and build.build are plain argument lists, so any toolchain works.
The Qt/MinGW case setup detects on this machine is:

```bash
C:/Qt/5.15.2/mingw81_32/bin/qmake.exe
C:/Qt/Tools/mingw810_32/bin/mingw32-make.exe
```

Neither is on PATH by default, which is why setup writes absolute paths.

Absolute paths are not enough on their own. A qmake-generated Makefile invokes the
compiler by bare name (`g++`), so the build step also needs the compiler's own
directory on PATH, or it fails with:

```
g++: error: CreateProcess: No such file or directory
```

setup detects that the directory is missing from PATH and writes the override, so keep
it when you re-point the toolchain:

```json
"env": { "PATH": "C:/Qt/Tools/mingw810_32/bin{pathsep}{PATH}" }
```
