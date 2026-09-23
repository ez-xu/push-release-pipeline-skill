#!/usr/bin/env python3
"""Build execution, artifact resolution, and PE version extraction.

The version is never recomputed from the build system. It is read back out of the
artifact that was actually produced, and cross-checked against the version encoded
in the binary's own PE version resource. A build system that computes a version
differently from the pipeline would otherwise be able to publish a mismatched pair
without anyone noticing.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from prp_repo import PrpError, run

RT_VERSION = 16
VS_FFI_SIGNATURE = 0xFEEF04BD


def _expand(value: Any, repo: Path, extra: Mapping[str, str] | None = None) -> Any:
    """Substitute {repo} and any supplied tokens in a config string."""
    if not isinstance(value, str):
        return value
    tokens = {"repo": str(repo)}
    if extra:
        tokens.update({k: str(v) for k, v in extra.items()})
    out = value
    for key, replacement in tokens.items():
        out = out.replace("{" + key + "}", replacement)
    return out


def _argv(spec: Any, repo: Path, extra: Mapping[str, str] | None = None) -> list[str]:
    """Accept a shell-style string or a list; always produce an argv list."""
    if spec is None:
        return []
    if isinstance(spec, str):
        return [str(_expand(part, repo, extra)) for part in spec.split()] if spec.strip() else []
    if isinstance(spec, list):
        return [str(_expand(part, repo, extra)) for part in spec]
    raise PrpError("command must be a string or list, got " + type(spec).__name__)


def run_step(
    label: str,
    spec: Any,
    *,
    repo: Path,
    cwd: Path,
    log_lines: list[str],
    timeout: int,
    extra: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run one build step, appending a transcript to log_lines."""
    argv = _argv(spec, repo, extra)
    if not argv:
        return
    log_lines.append("$ [" + label + "] " + " ".join(argv))
    proc = run(argv, cwd=cwd, timeout=timeout, env=dict(env) if env else None)
    if proc.stdout:
        log_lines.append(proc.stdout.rstrip())
    if proc.stderr:
        log_lines.append(proc.stderr.rstrip())
    if proc.returncode != 0:
        raise PrpError(
            label
            + " step failed with exit code "
            + str(proc.returncode)
            + ": "
            + " ".join(argv)
            + "\ntail:\n"
            + "\n".join(log_lines[-25:])
        )
    log_lines.append("[" + label + "] exit 0")


def build_env(spec: Any, repo: Path) -> dict[str, str] | None:
    """Environment overrides applied to every build step.

    A qmake-generated Makefile invokes the compiler by bare name, so a toolchain
    that is not on PATH -- the normal case for a Qt/MinGW shadow build -- fails
    with "CreateProcess: No such file or directory". {PATH} and {pathsep} are
    expanded from the caller's environment so an override extends PATH instead of
    replacing it.
    """
    if not isinstance(spec, Mapping) or not spec:
        return None
    extra = {"PATH": os.environ.get("PATH", ""), "pathsep": os.pathsep}
    return {str(key): str(_expand(value, repo, extra)) for key, value in spec.items()}


def clean_outputs(globs: Sequence[str], repo: Path, log_lines: list[str]) -> int:
    """Delete files matching the configured clean globs. Returns the count removed."""
    removed = 0
    for pattern in globs or []:
        for path in sorted(repo.glob(pattern)):
            if not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                log_lines.append("[clean] could not remove " + str(path) + ": " + str(exc))
    log_lines.append(
        "[clean] removed " + str(removed) + " file(s) matching " + repr(list(globs or []))
    )
    return removed


def resolve_artifact(artifact_cfg: Mapping[str, Any], repo: Path) -> tuple[Path, str]:
    """Locate exactly one artifact and read its version out of the file name."""
    root = repo / str(_expand(artifact_cfg.get("root", "."), repo))
    pattern = str(artifact_cfg.get("glob", "*"))
    if not root.is_dir():
        raise PrpError("artifact root does not exist: " + str(root))
    matches = sorted(p for p in root.glob(pattern) if p.is_file())
    if not matches:
        raise PrpError("no artifact matched " + repr(pattern) + " under " + str(root))
    if len(matches) > 1:
        listing = ", ".join(p.name for p in matches[:10])
        raise PrpError(
            str(len(matches))
            + " artifacts matched "
            + repr(pattern)
            + " under "
            + str(root)
            + "; the version would be ambiguous. Narrow artifact.glob. Matches: "
            + listing
        )
    artifact = matches[0]
    regex = artifact_cfg.get("versionRegex")
    if not regex:
        raise PrpError("artifact.versionRegex is required to read the version from the artifact")
    match = re.search(str(regex), artifact.name)
    if not match:
        raise PrpError(
            "artifact.versionRegex "
            + repr(regex)
            + " did not match "
            + repr(artifact.name)
            + "; the version cannot be read, so the tag cannot be trusted"
        )
    version = match.groupdict().get("version") or (match.group(1) if match.groups() else None)
    if not version:
        raise PrpError("artifact.versionRegex must expose a 'version' named group or group 1")
    return artifact, version


def _rva_to_offset(data: bytes, rva: int, sections: list[tuple[int, int, int, int]]) -> int | None:
    for va, vsize, raw_ptr, raw_size in sections:
        if va <= rva < va + max(vsize, raw_size):
            return raw_ptr + (rva - va)
    return None


def _iter_children(data: bytes, start: int, end: int):
    """Yield (key, value_offset, value_length, block_end) for version-info children."""
    offset = start
    while offset + 6 <= end:
        length, value_length, _value_type = struct.unpack_from("<HHH", data, offset)
        if length <= 0 or offset + length > end:
            return
        block_end = offset + length
        key_start = offset + 6
        key_end = key_start
        while key_end + 1 < block_end and data[key_end:key_end + 2] != b"\x00\x00":
            key_end += 2
        key = data[key_start:key_end].decode("utf-16-le", "replace")
        cursor = key_end + 2
        cursor += (-cursor) % 4
        yield key, cursor, value_length, block_end
        offset = block_end + ((-block_end) % 4)


def _parse_version_resource(blob: bytes) -> dict[str, str]:
    """Extract fixed-file and string version fields from a VS_VERSIONINFO blob."""
    out: dict[str, str] = {}
    if len(blob) < 6:
        return out
    length, value_length, _value_type = struct.unpack_from("<HHH", blob, 0)
    end = min(length or len(blob), len(blob))
    key_end = 6
    while key_end + 1 < end and blob[key_end:key_end + 2] != b"\x00\x00":
        key_end += 2
    cursor = key_end + 2
    cursor += (-cursor) % 4
    if value_length and cursor + 52 <= end:
        signature = struct.unpack_from("<I", blob, cursor)[0]
        if signature == VS_FFI_SIGNATURE:
            fv_ms, fv_ls = struct.unpack_from("<II", blob, cursor + 8)
            pv_ms, pv_ls = struct.unpack_from("<II", blob, cursor + 16)
            out["fileVersion"] = (
                str(fv_ms >> 16) + "." + str(fv_ms & 0xFFFF) + "."
                + str(fv_ls >> 16) + "." + str(fv_ls & 0xFFFF)
            )
            out["productVersion"] = (
                str(pv_ms >> 16) + "." + str(pv_ms & 0xFFFF) + "."
                + str(pv_ls >> 16) + "." + str(pv_ls & 0xFFFF)
            )
        cursor += value_length * 4
        cursor += (-cursor) % 4
    for key, value_offset, _value_length, block_end in _iter_children(blob, cursor, end):
        if key != "StringFileInfo":
            continue
        for _table_key, table_offset, _tl, table_end in _iter_children(blob, value_offset, block_end):
            for string_key, string_offset, string_length, _se in _iter_children(
                blob, table_offset, table_end
            ):
                if string_length <= 0:
                    continue
                raw = blob[string_offset:string_offset + string_length * 2]
                text = raw.decode("utf-16-le", "replace").rstrip("\x00")
                if string_key in ("FileVersion", "ProductVersion"):
                    out.setdefault("string" + string_key, text)
    return out


def pe_version_fields(path: Path) -> dict[str, str] | None:
    """Read the PE version resource of a Windows binary, or None if there is none.

    Returns keys such as fileVersion (a.b.c.d from VS_FIXEDFILEINFO) and
    stringFileVersion (the human-facing string, when present).
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew + 24 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return None
    coff = e_lfanew + 4
    # COFF header: NumberOfSections is at +2, SizeOfOptionalHeader is at +16.
    # Reading both from +2 silently yields TimeDateStamp's low half instead.
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    size_optional = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    if opt + 2 > len(data):
        return None
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112 if magic == 0x20B else 0)
    if not dd or dd + 16 > len(data):
        return None
    rsrc_rva, rsrc_size = struct.unpack_from("<II", data, dd + 2 * 8)
    if not rsrc_rva or not rsrc_size:
        return None
    sections: list[tuple[int, int, int, int]] = []
    sec = opt + size_optional
    for index in range(num_sections):
        base = sec + index * 40
        if base + 40 > len(data):
            break
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, base + 8)
        sections.append((va, vsize, raw_ptr, raw_size))
    rsrc_off = _rva_to_offset(data, rsrc_rva, sections)
    if rsrc_off is None:
        return None

    def walk(offset: int, level: int) -> int | None:
        if offset + 16 > len(data):
            return None
        named, ids = struct.unpack_from("<HH", data, offset + 12)
        for index in range(named + ids):
            entry = offset + 16 + index * 8
            if entry + 8 > len(data):
                return None
            name_id, child = struct.unpack_from("<II", data, entry)
            # The type filter must come first: a PE carries icons, manifests and
            # other resource types, and descending into those would return the
            # first blob of any type rather than the version resource.
            if level == 0 and name_id != RT_VERSION:
                continue
            if child & 0x80000000:
                found = walk(rsrc_off + (child & 0x7FFFFFFF), level + 1)
                if found is not None:
                    return found
                continue
            if level < 2:
                continue
            data_entry = rsrc_off + child
            if data_entry + 16 > len(data):
                return None
            rva, size = struct.unpack_from("<II", data, data_entry)
            if not size:
                return None
            return _rva_to_offset(data, rva, sections)
        return None

    blob_off = walk(rsrc_off, 0)
    if blob_off is None:
        return None
    fields = _parse_version_resource(data[blob_off:blob_off + 4096])
    return fields or None


def embedded_version(
    artifact: Path, artifact_cfg: Mapping[str, Any], repo: Path
) -> tuple[str | None, str]:
    """Resolve the artifact's self-declared version.

    Returns (version, note). version is None when the configuration does not ask
    for a check. A configured check that cannot be satisfied raises.
    """
    spec = artifact_cfg.get("embeddedVersion")
    if not spec:
        return None, "artifact.embeddedVersion is not configured; only the file name was checked"
    if isinstance(spec, Mapping) and spec.get("kind") == "pe-file-version":
        fields = pe_version_fields(artifact)
        if not fields:
            raise PrpError(
                "artifact.embeddedVersion requests a PE version resource but "
                + artifact.name
                + " has none; either fix the build's version resource or remove the setting"
            )
        version = fields.get("fileVersion")
        if not version:
            raise PrpError("PE version resource of " + artifact.name + " has no fixed file version")
        extra = fields.get("stringFileVersion")
        note = "PE resource fileVersion=" + version + ((", string=" + extra) if extra else "")
        return version, note
    if isinstance(spec, Mapping) and spec.get("command"):
        argv = _argv(spec["command"], repo)
        proc = run(argv, cwd=repo, timeout=120)
        if proc.returncode != 0:
            raise PrpError("artifact.embeddedVersion command failed: " + " ".join(argv))
        return proc.stdout.strip(), "command " + " ".join(argv)
    raise PrpError("artifact.embeddedVersion must be {kind: pe-file-version} or {command: ...}")


def main(argv: Sequence[str] | None = None) -> int:
    """Diagnostic entry point: report the PE version fields of one file."""
    import argparse

    parser = argparse.ArgumentParser(description="Read the PE version resource of a binary.")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    target = Path(args.path)
    if not target.is_file():
        print("ERROR: not a file: " + str(target), file=sys.stderr)
        return 1
    fields = pe_version_fields(target)
    print(json.dumps({"path": str(target), "peVersion": fields}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
