"""
Pymobile3-GUI — Device Identification Table

Maps Apple chip IDs (CPID, as reported by `irecovery -q` in DFU/recovery) to
the processor part number, the SoC name and the devices built on that chip.

Why this exists: irecovery only reports CPID/ECID/BDID and friends — it does
not expose product type or board id, so a DFU device could not be named in the
UI at all ("? (?)"). The CPID is the one identifier always present, so device
recognition keys on it.

Data only; performs no device I/O.
"""

from typing import Dict, NamedTuple, Optional


class DeviceCpids(NamedTuple):
    """One row of the CPID table."""

    cpid: str
    """Canonical hex chip id, lowercase "0x" form, e.g. "0x8015"."""

    processor: str
    """Apple processor part number as published, e.g. "T8015 (A11 Bionic)"."""

    chip: str
    """SoC name, empty when the published table gives none."""

    models: tuple
    """Device names sharing this chip."""

    device_class: str = "iPhone"
    """Family grouping. The published table's iPhone section, plus the one
    iPad row it happens to contain."""


# iPhone section of the CPID table, oldest to newest.
_IPHONE_ROWS = (
    ("0x8900", "S5L8900", "", ("iPhone (Original)", "iPhone 3G")),
    ("0x8920", "S5L8920", "", ("iPhone 3GS",)),
    ("0x8930", "S5L8930 (A4)", "A4", ("iPhone 4",)),
    ("0x8940", "S5L8940 (A5)", "A5", ("iPhone 4S",)),
    ("0x8942", "S5L8942 (A5 Rev A)", "A5",
     ("iPhone 4S (later revisions)",)),
    ("0x8950", "S5L8950 (A6)", "A6", ("iPhone 5",)),
    ("0x8955", "S5L8955 (A6X)", "A6X", ("iPad (4th generation)",), "iPad"),
    ("0x8960", "S5L8960 (A7)", "A7",
     ("iPhone 5s", "iPhone SE (1st generation)")),
    ("0x7000", "T7000 (A8)", "A8", ("iPhone 6", "iPhone 6 Plus")),
    ("0x8000", "S8000 / S8003 (A9)", "A9",
     ("iPhone 6s", "iPhone 6s Plus", "iPhone SE (1st generation)")),
    ("0x8003", "S8003 (A9)", "A9",
     ("iPhone 6s", "iPhone 6s Plus", "iPhone SE (1st generation)")),
    ("0x8010", "T8010 (A10 Fusion)", "A10 Fusion",
     ("iPhone 7", "iPhone 7 Plus")),
    ("0x8015", "T8015 (A11 Bionic)", "A11 Bionic",
     ("iPhone 8", "iPhone 8 Plus", "iPhone X")),
    ("0x8020", "T8020 (A12 Bionic)", "A12 Bionic",
     ("iPhone XR", "iPhone XS", "iPhone XS Max")),
    ("0x8030", "T8030 (A13 Bionic)", "A13 Bionic",
     ("iPhone 11 series", "iPhone SE (2nd generation)")),
    ("0x8101", "T8101 (A14 Bionic)", "A14 Bionic",
     ("iPhone 12 series",)),
    ("0x8110", "T8110 (A15 Bionic)", "A15 Bionic",
     ("iPhone 13 series", "iPhone 14", "iPhone 14 Plus",
      "iPhone SE (3rd generation)")),
    ("0x8120", "T8120 (A16 Bionic)", "A16 Bionic",
     ("iPhone 14 Pro", "iPhone 14 Pro Max", "iPhone 15", "iPhone 15 Plus")),
    ("0x8130", "T8130 (A17 Pro)", "A17 Pro",
     ("iPhone 15 Pro", "iPhone 15 Pro Max")),
    ("0x8140", "T8140 (A18 / A18 Pro)", "A18 / A18 Pro",
     ("iPhone 16 series", "iPhone 16e")),
    ("0x8150", "T8150 (A19 / A19 Pro)", "A19 / A19 Pro",
     ("iPhone 17 series", "iPhone Air")),
    ("0x8160", "T8160 (A20 Pro)", "A20 Pro",
     ("iPhone 18 Pro series",)),
)

IPHONE_CPIDS = tuple(DeviceCpids(*row) for row in _IPHONE_ROWS)

CPID_TABLE: Dict[str, DeviceCpids] = {row.cpid: row for row in IPHONE_CPIDS}

# Some chips boot under more than one id. Point the extra ids at the canonical
# row so the UI resolves to a single name instead of "unknown".
CPID_ALIASES = {
    "0x3512": "0x8930",   # iPhone 4: A4 also reports as 0x3512
    "0x8001": "0x8000",   # A9X TSMC, same devices as 0x8000
    "0x8965": "0x8960",   # A7 exception to the chip-id encoding rule
}


def normalize_cpid(raw) -> str:
    """Normalize a CPID to lowercase "0x" hex form.

    Accepts "8015", "0x8015", "0X8015", " 0X8015 " or an int: the value
    reaches us from different tools and from hand-entered values.
    """
    if raw is None:
        return ""
    if isinstance(raw, int):
        return f"0x{raw:04x}"
    text = str(raw).strip().lower()
    if not text:
        return ""
    if text.startswith("0x"):
        text = text[2:]
    text = text.lstrip("0")
    return f"0x{text}" if text else ""


def lookup(cpid) -> Optional[DeviceCpids]:
    """Return the table row for a CPID, or None when it is not in the table."""
    key = normalize_cpid(cpid)
    if not key:
        return None
    row = CPID_TABLE.get(key)
    if row is not None:
        return row
    alias = CPID_ALIASES.get(key)
    return CPID_TABLE.get(alias) if alias else None


def is_known(cpid) -> bool:
    """True when the CPID resolves to a row in the table."""
    return lookup(cpid) is not None


def models(cpid) -> tuple:
    """Device names for a CPID; empty when unknown."""
    row = lookup(cpid)
    return row.models if row else ()


def name(cpid) -> str:
    """Compact device name for a CPID, e.g. "iPhone 8 / iPhone 8 Plus / iPhone X"."""
    row = lookup(cpid)
    return " / ".join(row.models) if row else ""


def describe(cpid) -> str:
    """One-line description, e.g. "A11 Bionic — iPhone 8 / iPhone 8 Plus / iPhone X"."""
    row = lookup(cpid)
    if not row:
        return ""
    label = row.chip or row.processor
    return f"{label} — {name(row.cpid)}"