"""Exec gate: no admitted work runs before its child identity is recorded.

This is process plumbing, not an OS sandbox. The qualified launcher supplies
the actual tool/credential/network boundary. An EOF or parent crash before the
one-byte admission token exits without invoking that launcher.
"""
from __future__ import annotations

import json
import os
import select
import sys


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 126
    gate = int(args[0])
    command = json.loads(args[1])
    try:
        ready, _, _ = select.select([gate], [], [], 10)
        admitted = bool(ready) and os.read(gate, 1) == b"1"
    finally:
        os.close(gate)
    if not admitted:
        return 125
    os.execv(command[0], command)
    return 126


if __name__ == "__main__":
    raise SystemExit(main())
