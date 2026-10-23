"""Read-only selection diagnostics. Reports metadata, never selected text or keys."""

from __future__ import annotations

import argparse
import json
import multiprocessing
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mouse import MouseSelectionListener
from core.reader_process import ReaderProcess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=3, help="Seconds to switch to the target and select text")
    parser.add_argument("--window", type=int, default=0, help="Optional source HWND")
    parser.add_argument("--watch", type=float, default=0, help="Observe foreground selection event metadata for this many seconds")
    args = parser.parse_args()
    events = []
    reader = ReaderProcess(lambda window, stamp: events.append((window, stamp)))
    try:
        reader.watch(bool(args.watch))
        if args.watch:
            time.sleep(max(0, args.watch))
        else:
            time.sleep(max(0, args.delay))
        mouse = MouseSelectionListener()
        window = args.window or mouse.foreground()
        program = mouse.program_name(window)
        start = time.monotonic()
        result = reader.read(window, program=program)
        print(json.dumps(dict(window=window, program=program, status=result.status, reason=result.reason,
                              method=result.method, characters=len(result.text),
                              elapsed_ms=round((time.monotonic() - start) * 1000),
                              selection_events=len(events)), ensure_ascii=False))
    finally:
        reader.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
