from __future__ import annotations

import sys
from collections.abc import Sequence

from .errors import VivariumError


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or ())
    try:
        if not args:
            raise VivariumError("V2 command required")
        raise VivariumError(f"unknown V2 command: {args[0]}")
    except VivariumError as error:
        sys.stderr.write(f"ERROR: {error}\n")
        return error.exit_code
