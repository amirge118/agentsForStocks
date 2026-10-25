"""Compare two eval reports: python -m evals.compare <before.json> <after.json>"""

import json
import sys
from pathlib import Path

from evals.report import compare


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(__doc__ + "\n")
        return 2
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in argv)
    sys.stdout.write(compare(a, b))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
