"""Fail when tracked files contain obvious credentials.

This is intentionally conservative: local .env files are ignored and are not
scanned by this check. It is a guardrail, not a replacement for credential
rotation or a dedicated secret-management system.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TELEGRAM_TOKEN = re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?:TELEGRAM_WEBHOOK_SECRET|FITKIT_API_KEY)\s*=\s*([^\s#]+)"
)
PLACEHOLDER_VALUES = {"...", "<local-api-key>", "<long-random-webhook-secret>"}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], text=True)
    return [Path(line) for line in output.splitlines() if line]


def _scan_content(path: str, content: str) -> list[str]:
    findings: list[str] = []
    for pattern, label in (
        (TELEGRAM_TOKEN, "Telegram bot token"),
        (PRIVATE_KEY, "private key"),
        (AWS_ACCESS_KEY, "AWS access key"),
    ):
        if pattern.search(content):
            findings.append(f"{path}: possible {label}")
    for match in GENERIC_SECRET_ASSIGNMENT.finditer(content):
        if match.group(1).strip("'\\\"") not in PLACEHOLDER_VALUES:
            findings.append(f"{path}: possible configured application secret")
            break
    return findings


def _history_commits() -> list[str]:
    output = subprocess.check_output(["git", "rev-list", "--all"], text=True)
    return [commit for commit in output.splitlines() if commit]


def _historical_files(commit: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit], text=True
    )
    return [path for path in output.splitlines() if path]


def _historical_content(commit: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history",
        action="store_true",
        help="Also scan every commit available in the local Git history.",
    )
    args = parser.parse_args()

    findings: list[str] = []
    for path in tracked_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(_scan_content(str(path), content))

    if args.history:
        for commit in _history_commits():
            for path in _historical_files(commit):
                content = _historical_content(commit, path)
                if content is not None:
                    findings.extend(_scan_content(f"{commit}:{path}", content))

    if findings:
        print("Possible committed secrets detected:", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in findings), file=sys.stderr)
        return 1

    print("Secret pattern check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
