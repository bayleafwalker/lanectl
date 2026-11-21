"""Select a replayable batch of owner-confirmed LANECTL settlements."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .events import EventLog
from .settlement_summary import MAX_ITEMS


def event_digest(event):
    return hashlib.sha256(json.dumps(
        event, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def next_batch(events, *, offset=0, digest=None):
    if type(offset) is not int or not 0 <= offset <= len(events):
        raise ValueError("checkpoint offset is outside the event ledger")
    if (offset == 0 and digest is not None) or (
        offset and digest != event_digest(events[offset - 1])
    ):
        raise ValueError("checkpoint does not match the event ledger")

    ids = []
    seen = set()
    through = offset
    for position, event in enumerate(events, 1):
        data = event["data"]
        if position > offset:
            through = position
        if (event["type"] != "work.synced" or data.get("closed") is not True
                or data.get("ok") is not True or data.get("owner_reported") is not True):
            continue
        work = data.get("work")
        match = re.fullmatch(r"lanectl#([1-9][0-9]*)", work) if isinstance(work, str) else None
        if not match:
            continue
        work_id = int(match[1])
        if work_id not in seen and position > offset:
            ids.append(work_id)
        seen.add(work_id)
        if len(ids) == MAX_ITEMS:
            break
    return {
        "work_ids": ids,
        "checkpoint": {
            "offset": through,
            "digest": event_digest(events[through - 1]) if through else None,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--checkpoint", type=Path, help="Previously acknowledged checkpoint JSON")
    args = parser.parse_args(argv)
    try:
        checkpoint = json.loads(args.checkpoint.read_text()) if args.checkpoint else {}
        if not isinstance(checkpoint, dict) or set(checkpoint) - {"offset", "digest"}:
            raise ValueError("invalid checkpoint")
        result = next_batch(EventLog(args.ledger, create=False).read(), **checkpoint)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Settlement batch unavailable: check the ledger and acknowledged checkpoint.", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
