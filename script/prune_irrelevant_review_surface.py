#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from clipping_ops_backend import database as db  # noqa: E402


def main() -> int:
    result = db.prune_irrelevant_review_surface()
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
