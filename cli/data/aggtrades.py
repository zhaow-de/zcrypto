from __future__ import annotations

import io
import zipfile


def validate_aggtrades_zip(raw: bytes) -> None:
    """Structural integrity gate for a daily aggTrades zip — NO full row parse.

    aggTrades archives carry millions of rows; parsing every one would be prohibitively slow.
    This asserts only the structure: the bytes open as a zip, extract to exactly one `.csv`
    member, and that member is non-empty/openable. Raises `ValueError` otherwise. Used as the
    integrity gate on the unchecksummed path, mirroring how `parse_kline_zip` gates klines.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        csv_names = [n for n in names if n.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"aggTrades zip: expected exactly one .csv member, got {names}")
        name = csv_names[0]
        info = zf.getinfo(name)
        if info.file_size == 0:
            raise ValueError(f"aggTrades zip: member {name!r} is empty")
        with zf.open(name) as fh:
            if not fh.read(1):
                raise ValueError(f"aggTrades zip: member {name!r} is not readable / empty")
