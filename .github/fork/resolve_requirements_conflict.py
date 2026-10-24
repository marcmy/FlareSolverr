#!/usr/bin/env python3
"""Resolve upstream requirements.txt conflicts limited to monotonic numeric pin upgrades.

Use only when Git has populated stages 1 (base), 2 (fork), and 3 (upstream).
Never resolve added/deleted requirements, changed markers, or non-version edits.
"""

import re
import subprocess
import sys

PATH = "requirements.txt"
PIN = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)=="
    r"(?P<version>\d+(?:\.\d+)*)"
    r"(?P<suffix>\s*(?:;.*)?)\Z"
)


def stage(number):
    return subprocess.check_output(
        ["git", "show", f":{number}:{PATH}"], stderr=subprocess.DEVNULL
    ).decode("utf-8")


def release(version):
    return tuple(int(part) for part in version.split("."))


def compare(left, right):
    length = max(len(left), len(right))
    return (left + (0,) * (length - len(left))) >= (
        right + (0,) * (length - len(right))
    )


def main():
    try:
        original, ours, theirs = (stage(n) for n in (1, 2, 3))
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        sys.exit("Cannot inspect all three Git conflict stages")

    if not all(content.endswith("\n") for content in (original, ours, theirs)):
        sys.exit("Refusing requirements merge with changed newline conventions")

    base_lines, our_lines, their_lines = (
        content.splitlines() for content in (original, ours, theirs)
    )
    if len({len(base_lines), len(our_lines), len(their_lines)}) != 1:
        sys.exit("Refusing requirements merge with added or removed lines")

    result = []
    for number, (base, local, upstream) in enumerate(
        zip(base_lines, our_lines, their_lines), start=1
    ):
        if local == upstream:
            result.append(local)
            continue

        pins = [PIN.fullmatch(line) for line in (base, local, upstream)]
        if any(pin is None for pin in pins):
            sys.exit(f"Refusing non-pin conflict at {PATH}:{number}")
        first, second, third = pins
        if len({pin.group("name") for pin in pins}) != 1 or len(
            {pin.group("suffix") for pin in pins}
        ) != 1:
            sys.exit(f"Refusing changed package or marker at {PATH}:{number}")

        base_release = release(first.group("version"))
        fork_release = release(second.group("version"))
        upstream_release = release(third.group("version"))
        if not compare(fork_release, base_release) or not compare(
            upstream_release, base_release
        ):
            sys.exit(f"Refusing version downgrade at {PATH}:{number}")

        selected = second if compare(fork_release, upstream_release) else third
        result.append(
            selected.group("name") + "==" + selected.group("version") + selected.group("suffix")
        )

    with open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(result) + "\n")
    print("Resolved requirements.txt using non-downgrading numeric dependency pins")


if __name__ == "__main__":
    main()
