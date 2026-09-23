"""Health contract for the release-provider interface.

The pipeline depends on exactly three operations against a provider's release API:
create a release with one named asset, download that asset back, and delete a
release during rollback. The closed-loop standard is impossible without the second
one, so this contract is checked before the build rather than discovered afterwards.

A not-usable report is a safe stop: the caller must not fall back to publishing
without verification.
"""
from __future__ import annotations

import shutil
import subprocess

CONTRACT_ID = "release_api"
INTERFACE = "GitLab Releases (glab) and GitHub Releases (gh) command line interfaces"
REQUIRED_OPERATIONS = (
    "release create with one named asset",
    "release download of a named asset",
    "release delete during rollback",
)


def _cli_for(provider: str) -> str:
    return "gh" if provider == "github" else "glab"


def _run(argv: list[str], cwd: str, timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def report(provider: str = "gitlab", repo: str = ".") -> dict:
    """Check that the release interface can support the closed-loop read-back.

    Returns a dict with freshness, smoke, usable and the individual checks. Never
    raises: an unreachable interface is reported as unusable, not as an exception.
    """
    cli = _cli_for(provider)
    resolved = shutil.which(cli)
    checks: list[dict] = [
        {
            "name": "cli-present",
            "ok": resolved is not None,
            "detail": resolved or (cli + " is not on PATH"),
        }
    ]
    if resolved is None:
        return {
            "contract": CONTRACT_ID,
            "interface": INTERFACE,
            "provider": provider,
            "freshness": "UNKNOWN",
            "smoke": "FAIL",
            "usable": False,
            "required_operations": list(REQUIRED_OPERATIONS),
            "checks": checks,
        }

    auth_rc, auth_text = _run([resolved, "auth", "status"], repo)
    first_line = next((line.strip() for line in auth_text.splitlines() if line.strip()), "")
    checks.append(
        {"name": "authenticated", "ok": auth_rc == 0, "detail": first_line[:160]}
    )

    # Probe each subcommand directly rather than grepping the parent help text: a
    # text match breaks the moment a CLI reorganises its help output, and a false
    # negative here would block a release that would actually have worked.
    purposes = {
        "create": "the release can be published",
        "download": "the closed-loop read-back can run",
        "delete": "rollback can run",
    }
    for operation, purpose in purposes.items():
        rc, text = _run([resolved, "release", operation, "--help"], repo)
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        checks.append(
            {
                "name": operation + "-operation-available",
                "ok": rc == 0,
                "detail": (
                    "release " + operation + " is exposed, so " + purpose
                )
                if rc == 0
                else "release " + operation + " is not available: " + first[:120],
            }
        )

    usable = all(check["ok"] for check in checks)
    return {
        "contract": CONTRACT_ID,
        "interface": INTERFACE,
        "provider": provider,
        "freshness": "FRESH",
        "smoke": "PASS" if usable else "FAIL",
        "usable": usable,
        "required_operations": list(REQUIRED_OPERATIONS),
        "checks": checks,
    }
