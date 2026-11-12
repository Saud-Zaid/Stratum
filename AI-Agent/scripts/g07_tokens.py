# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""G07 named token counter (AD06 C6 F2): the highest-cost repeated operation, counting
tokens of one file or a whole set, measured with the first-party method (tiktoken
o200k_base, AD06 T4). Read-only: prints, never writes.

Usage:
  g07-tokens <path1> [<path2> ...] [--total] [--per-line]
Output: one row per file: <tokens> <path> ; with --total a final TOTAL row.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from _vaultlib import VAULT, ensure_o200k_cache

ENCODING = "o200k_base"   # first-party method of AD06 T4; any change re-baselines g06


@lru_cache(maxsize=1)
def _vocab_ready() -> bool:
    """o200k_base is in the cache with the published hash, or was fetched within the bounded timeout (U-45)."""
    return ensure_o200k_cache()


def enc():
    if not _vocab_ready():
        raise RuntimeError("o200k_base vocabulary unavailable (offline, STRATUM_SKIP_NET=1 or hash mismatch)")
    import tiktoken
    return tiktoken.get_encoding(ENCODING)


def tokens_of(text: str, _e=None) -> int:
    return len((_e or enc()).encode(text))


def file_tokens(path: Path, _e=None) -> int:
    return tokens_of(Path(path).read_text(encoding="utf-8", errors="replace"), _e)


def main(argv: list) -> None:
    args = [a for a in argv if not a.startswith("--")]
    want_total = "--total" in argv
    if not args:
        print(__doc__)
        return
    e = enc()
    total = 0
    for a in args:
        p = Path(a)
        p = p if p.is_absolute() else VAULT / a
        n = file_tokens(p, e)
        total += n
        print(f"{n} {a}")
    if want_total:
        print(f"TOTAL {total}")


if __name__ == "__main__":
    main(sys.argv[1:])
