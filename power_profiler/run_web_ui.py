from __future__ import annotations

import sys

from radio_power_profiler.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["web", *sys.argv[1:]]))
