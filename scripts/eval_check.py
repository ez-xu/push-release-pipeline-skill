#!/usr/bin/env python3
"""Assert one named invariant in an eval harness verdict.

The eval criteria call this instead of grep so they behave the same on Windows,
where grep is only present when Git's usr/bin happens to be on PATH.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

INVARIANTS = (
    "harnessRan",
    "scenarioIdentified",
    "closedLoopConsistent",
    "noOrphanTag",
    "provenanceComplete",
)


def evaluate(data: dict, name: str) -> bool:
    checks = data.get("checks") or {}
    if name == "harnessRan":
        return isinstance(data.get("exitCode"), int)
    if name == "scenarioIdentified":
        scenario = str(data.get("scenario") or "")
        return bool(scenario) and scenario.replace("-", "").isalnum()
    return checks.get(name) is True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[1] not in INVARIANTS:
        print("usage: eval_check.py <verdict.json> <" + "|".join(INVARIANTS) + ">",
              file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print("verdict missing: " + str(path), file=sys.stderr)
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("verdict unreadable: " + str(exc), file=sys.stderr)
        return 1
    ok = evaluate(data, args[1])
    print(("ok      " if ok else "not ok  ") + args[1]
          + "  scenario=" + str(data.get("scenario")))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
