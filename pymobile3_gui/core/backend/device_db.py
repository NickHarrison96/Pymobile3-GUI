"""
Pymobile3-GUI — Device Capability Database

Pure-data table plus lookup helpers describing what each iOS device is and
what it can do. This module is the foundation the Legacy iOS Kit parity work
gates on (see docs/TODO.md section 6.1): every menu there keys off ProductType,
board id, processor generation and iOS version.

Block B1a covers the HardwareModel <-> ProductType map, ported from the
behaviour of Legacy-iOS-Kit's `device_get_info` (restore.sh). It is
reimplemented as data, not copied.

Data only; performs no device I/O.
"""

import fnmatch
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

__all__ = [
    "DeviceBoard",
    "REGISTRY",
    "AMBIGUOUS_PRODUCT_TYPES",
    "PROCESSOR_NAMES",
    "normalize_board",
    "product_type_for_board",
    "boards_for_product_type",
    "board_for_product_type",
    "is_ambiguous",
    "resolve_identity",
    "processor_generation",
    "processor_name",
    "checkm8_ipad",
    "signed_target",
    "latest_version",
    "baseband",
    "latest_baseband",
    "baseband_flag",
    "is_9900_candidate",
    "has_activation_issue",
    "activation_record_mode",
    "can_powdersn0w",
    "powdersn0w_versions",
    "can_dra_v6",
    "parse_ecid",
    "format_ecid",
    "parse_irecovery_mode",
    "parse_version",
    "manual_entry",
    "info_from_irecovery",
]


class DeviceBoard(NamedTuple):
    """One (board id, ProductType) row of the hardware map."""

    board: str
    """Hardware model, lowered and stripped of its trailing "ap", e.g. "n71"."""

    product_type: str
    """Apple product type, e.g. "iPhone8,1"."""

    device_class: str
    """Family grouping: "iPhone", "iPad" or "iPod"."""


REGISTRY: Tuple[DeviceBoard, ...] = (
    DeviceBoard("k48", "iPad1,1", "iPad"),
    DeviceBoard("k93", "iPad2,1", "iPad"),
    DeviceBoard("k94", "iPad2,2", "iPad"),
    DeviceBoard("k95", "iPad2,3", "iPad"),
    DeviceBoard("k93a", "iPad2,4", "iPad"),
    DeviceBoard("p105", "iPad2,5", "iPad"),
    DeviceBoard("p106", "iPad2,6", "iPad"),
    DeviceBoard("p107", "iPad2,7", "iPad"),
    DeviceBoard("j1", "iPad3,1", "iPad"),
    DeviceBoard("j2", "iPad3,2", "iPad"),
    DeviceBoard("j2a", "iPad3,3", "iPad"),
    DeviceBoard("p101", "iPad3,4", "iPad"),
    DeviceBoard("p102", "iPad3,5", "iPad"),
    DeviceBoard("p103", "iPad3,6", "iPad"),
    DeviceBoard("j71", "iPad4,1", "iPad"),
    DeviceBoard("j72", "iPad4,2", "iPad"),
    DeviceBoard("j73", "iPad4,3", "iPad"),
    DeviceBoard("j85", "iPad4,4", "iPad"),
    DeviceBoard("j86", "iPad4,5", "iPad"),
    DeviceBoard("j87", "iPad4,6", "iPad"),
    DeviceBoard("j85m", "iPad4,7", "iPad"),
    DeviceBoard("j86m", "iPad4,8", "iPad"),
    DeviceBoard("j87m", "iPad4,9", "iPad"),
    DeviceBoard("j96", "iPad5,1", "iPad"),
    DeviceBoard("j97", "iPad5,2", "iPad"),
    DeviceBoard("j81", "iPad5,3", "iPad"),
    DeviceBoard("j82", "iPad5,4", "iPad"),
    DeviceBoard("j127", "iPad6,3", "iPad"),
    DeviceBoard("j128", "iPad6,4", "iPad"),
    DeviceBoard("j98a", "iPad6,7", "iPad"),
    DeviceBoard("j99a", "iPad6,8", "iPad"),
    DeviceBoard("j71s", "iPad6,11", "iPad"),
    DeviceBoard("j71t", "iPad6,11", "iPad"),
    DeviceBoard("j72s", "iPad6,12", "iPad"),
    DeviceBoard("j72t", "iPad6,12", "iPad"),
    DeviceBoard("j120", "iPad7,1", "iPad"),
    DeviceBoard("j121", "iPad7,2", "iPad"),
    DeviceBoard("j207", "iPad7,3", "iPad"),
    DeviceBoard("j208", "iPad7,4", "iPad"),
    DeviceBoard("j71b", "iPad7,5", "iPad"),
    DeviceBoard("j72b", "iPad7,6", "iPad"),
    DeviceBoard("j171", "iPad7,11", "iPad"),
    DeviceBoard("j172", "iPad7,12", "iPad"),
    DeviceBoard("m68", "iPhone1,1", "iPhone"),
    DeviceBoard("n82", "iPhone1,2", "iPhone"),
    DeviceBoard("n88", "iPhone2,1", "iPhone"),
    DeviceBoard("n90", "iPhone3,1", "iPhone"),
    DeviceBoard("n90b", "iPhone3,2", "iPhone"),
    DeviceBoard("n92", "iPhone3,3", "iPhone"),
    DeviceBoard("n94", "iPhone4,1", "iPhone"),
    DeviceBoard("n41", "iPhone5,1", "iPhone"),
    DeviceBoard("n42", "iPhone5,2", "iPhone"),
    DeviceBoard("n48", "iPhone5,3", "iPhone"),
    DeviceBoard("n49", "iPhone5,4", "iPhone"),
    DeviceBoard("n51", "iPhone6,1", "iPhone"),
    DeviceBoard("n53", "iPhone6,2", "iPhone"),
    DeviceBoard("n56", "iPhone7,1", "iPhone"),
    DeviceBoard("n61", "iPhone7,2", "iPhone"),
    DeviceBoard("n71", "iPhone8,1", "iPhone"),
    DeviceBoard("n71m", "iPhone8,1", "iPhone"),
    DeviceBoard("n66", "iPhone8,2", "iPhone"),
    DeviceBoard("n66m", "iPhone8,2", "iPhone"),
    DeviceBoard("n69", "iPhone8,4", "iPhone"),
    DeviceBoard("n69u", "iPhone8,4", "iPhone"),
    DeviceBoard("d10", "iPhone9,1", "iPhone"),
    DeviceBoard("d11", "iPhone9,2", "iPhone"),
    DeviceBoard("d101", "iPhone9,3", "iPhone"),
    DeviceBoard("d111", "iPhone9,4", "iPhone"),
    DeviceBoard("d20", "iPhone10,1", "iPhone"),
    DeviceBoard("d21", "iPhone10,2", "iPhone"),
    DeviceBoard("d22", "iPhone10,3", "iPhone"),
    DeviceBoard("d201", "iPhone10,4", "iPhone"),
    DeviceBoard("d211", "iPhone10,5", "iPhone"),
    DeviceBoard("d221", "iPhone10,6", "iPhone"),
    DeviceBoard("n45", "iPod1,1", "iPod"),
    DeviceBoard("n72", "iPod2,1", "iPod"),
    DeviceBoard("n18", "iPod3,1", "iPod"),
    DeviceBoard("n81", "iPod4,1", "iPod"),
    DeviceBoard("n78", "iPod5,1", "iPod"),
    DeviceBoard("n102", "iPod7,1", "iPod"),
    DeviceBoard("n112", "iPod9,1", "iPod"),
)

_BOARD_TO_TYPE: Dict[str, str] = {row.board: row.product_type for row in REGISTRY}

_TYPE_TO_BOARDS: Dict[str, List[str]] = {}
for _row in REGISTRY:
    _TYPE_TO_BOARDS.setdefault(_row.product_type, []).append(_row.board)
del _row

AMBIGUOUS_PRODUCT_TYPES = frozenset(
    {
        "iPad6,11",
        "iPad6,12",
        "iPhone8,1",
        "iPhone8,2",
        "iPhone8,4",
    }
)
"""ProductTypes that can report more than one board id.

Legacy-iOS-Kit deliberately leaves the board untouched for these in its
ProductType -> board fallback, so there is no single canonical board. Querying
`board_for_product_type` on one of these returns None.
"""


def normalize_board(raw) -> str:
    """Normalize a HardwareModel to its lowered, "ap"-stripped board id.

    Accepts the raw lockdown value ("N71AP"), an already-lowered one ("n71ap"),
    a bare board ("n71") or None; returns "" when nothing usable is left.
    """
    if raw is None:
        return ""
    text = str(raw).strip().lower()
    if text.endswith("ap"):
        text = text[:-2]
    return text


def product_type_for_board(board) -> Optional[str]:
    """Return the ProductType for a board id, or None when unknown."""
    return _BOARD_TO_TYPE.get(normalize_board(board))


def boards_for_product_type(product_type) -> Tuple[str, ...]:
    """Return every board id that reports this ProductType, in table order."""
    if not product_type:
        return ()
    return tuple(_TYPE_TO_BOARDS.get(str(product_type).strip(), ()))


def is_ambiguous(product_type) -> bool:
    """True when a ProductType can report more than one board id."""
    return str(product_type).strip() in AMBIGUOUS_PRODUCT_TYPES


def board_for_product_type(product_type) -> Optional[str]:
    """Return the canonical board id for a ProductType, or None.

    None means either the ProductType is unknown or it is ambiguous (more than
    one board reports it), matching Legacy-iOS-Kit, which never forces a board
    for the ambiguous set.
    """
    key = str(product_type).strip() if product_type else ""
    if not key or key in AMBIGUOUS_PRODUCT_TYPES:
        return None
    boards = _TYPE_TO_BOARDS.get(key)
    return boards[0] if boards else None


def resolve_identity(
    hardware_model=None, reported_product_type=None
) -> Tuple[str, str]:
    """Resolve (ProductType, board) the way Legacy-iOS-Kit's device_get_info does.

    Applies the two documented quirks: an "N81AP" HardwareModel (iPod touch 4
    on iOS 7, which reports as iPhone3,1/3,3) is forced to iPod4,1; and a
    reported iPad2,1 forces the board to "k93". A board present in the table
    takes precedence over the reported ProductType, matching the board -> type
    "fallback/failsafe" case. Returns ("", "") when nothing resolves.
    """
    raw_model = "" if hardware_model is None else str(hardware_model).strip()
    board = normalize_board(raw_model)
    product_type = (
        "" if reported_product_type is None else str(reported_product_type).strip()
    )

    if raw_model.upper() == "N81AP":
        product_type = "iPod4,1"
    if product_type == "iPad2,1":
        board = "k93"

    mapped = _BOARD_TO_TYPE.get(board)
    if mapped:
        product_type = mapped
    elif not product_type:
        product_type = _BOARD_TO_TYPE.get(board, "")

    if not board and product_type:
        board = board_for_product_type(product_type) or ""

    return product_type, board


PROCESSOR_NAMES: Dict[int, str] = {
    1: "S5L8900",
    4: "A4",
    5: "A5",
    6: "A6",
    7: "A7",
    8: "A8",
    9: "A9",
    10: "A10/A11",
    11: "Newer",
}
"""Generation -> the SoC family Legacy-iOS-Kit's `device_proc` stands for."""

_PRODUCT_TYPE_RE = re.compile(r"^(iPhone|iPad|iPod)(\d+),(\d+)$")


def _split_product_type(product_type) -> Optional[Tuple[str, int, int]]:
    """Split "iPhone8,1" into ("iPhone", 8, 1); None when malformed."""
    if not product_type:
        return None
    match = _PRODUCT_TYPE_RE.match(str(product_type).strip())
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def processor_generation(product_type) -> int:
    """Return Legacy-iOS-Kit's `device_proc` generation for a ProductType.

    Mirrors the ordered `case` in restore.sh: S5L8900=1, A4=4, A5=5, A6=6,
    A7=7, A8=8, A9=9, A10/A11=10, and anything newer=11. Returns 0 when the
    ProductType is unknown or malformed (LIK raises an error in that case).
    """
    parts = _split_product_type(product_type)
    if parts is None:
        text = "" if product_type is None else str(product_type).strip()
        if text.startswith(("AppleTV", "Watch")):
            return 11
        return 0
    family, major, minor = parts

    if family == "iPad" and major == 1:
        return 4
    if major == 1:
        return 1
    if family == "iPhone" and major in (2, 3):
        return 4
    if family == "iPod" and major in (2, 3, 4):
        return 4
    if family == "iPad" and major == 2:
        return 5
    if family == "iPad" and major == 3 and minor in (1, 2, 3):
        return 5
    if family == "iPhone" and major == 4:
        return 5
    if family == "iPod" and major == 5:
        return 5
    if family == "iPad" and major == 3:
        return 6
    if family == "iPhone" and major == 5:
        return 6
    if family == "iPad" and major == 4:
        return 7
    if family == "iPhone" and major == 6:
        return 7
    if family == "iPad" and major == 5:
        return 8
    if family == "iPhone" and major == 7:
        return 8
    if family == "iPod" and major == 7:
        return 8
    if family == "iPad" and major == 6:
        return 9
    if family == "iPhone" and major == 8:
        return 9
    if family == "iPad" and major == 7:
        return 10
    if family == "iPhone" and major in (9, 10):
        return 10
    if family == "iPod" and major == 9:
        return 10
    return 11


def processor_name(product_type) -> str:
    """Human label for a ProductType's processor generation, e.g. "A9"."""
    return PROCESSOR_NAMES.get(processor_generation(product_type), "")


def checkm8_ipad(product_type) -> bool:
    """True for the checkm8-capable iPads (device_checkm8ipad: iPad6/7)."""
    parts = _split_product_type(product_type)
    if parts is None:
        return False
    family, major, _minor = parts
    return family == "iPad" and major in (6, 7)


_SIGNED_TARGET_RULES: Tuple[Tuple[Tuple[str, ...], Tuple[str, str]], ...] = (
    (("iPhone1,1", "iPod1,1"), ("3.1.3", "7E18")),
    (("iPhone1,2", "iPod2,1"), ("4.2.1", "8C148")),
    (("iPad1,1", "iPod3,1"), ("5.1.1", "9B206")),
    (("iPhone2,1", "iPod4,1"), ("6.1.6", "10B500")),
    (("iPhone3,[123]",), ("7.1.2", "11D257")),
    (("iPad2,[1245]", "iPad3,1", "iPod5,1"), ("9.3.5", "13G36")),
    (("iPad2,[367]", "iPad3,[23]", "iPhone4,1"), ("9.3.6", "13G37")),
    (("iPad3,[456]", "iPhone5,[1234]"), ("10.3.4", "14G61")),
    (("iPad4,[12345]", "iPhone6,[12]"), ("10.3.3", "14G60")),
)
"""Ordered (ProductType globs -> (version, build)) OTA-downgrade matrix."""

_LATEST_RULES: Tuple[Tuple[Tuple[str, ...], Tuple[str, str]], ...] = (
    (("iPad4,*", "iPhone[67],*", "iPod7,1"), ("12.5.8", "16H88")),
    (("iPad5,*", "iPhone[89],*", "iPod9,1"), ("15.8.8", "19H422")),
    (("iPad6,*", "iPhone10,*"), ("16.7.16", "20H392")),
    (("iPad7,[123456]",), ("17.7.11", "21H461")),
    (("iPad7,1[12]", "iPhone11,*"), ("18.7.9", "22H355")),
)
"""Ordered (ProductType globs -> (version, build)) latest-known versions."""


def _match_rules(
    product_type: str, rules: Tuple[Tuple[Tuple[str, ...], Tuple[str, str]], ...]
) -> Optional[Tuple[str, str]]:
    for patterns, version in rules:
        if any(fnmatch.fnmatchcase(product_type, pat) for pat in patterns):
            return version
    return None


def signed_target(product_type) -> Optional[Tuple[str, str]]:
    """Return the signed-target (version, build) for a ProductType, or None.

    This is the OTA-downgrade matrix: the last version Apple signed for a
    device (3.1.3/7E18 ... 10.3.3/14G60). Newer devices are absent by design.
    """
    if product_type is None:
        return None
    return _match_rules(str(product_type).strip(), _SIGNED_TARGET_RULES)


def latest_version(
    product_type, fetcher: Optional[Callable[[str], Optional[Tuple[str, str]]]] = None
) -> Optional[Tuple[str, str]]:
    """Return the latest-known (version, build) for a ProductType.

    Resolution order mirrors Legacy-iOS-Kit: the hardcoded latest table first,
    then the signed-target matrix, then an optional `fetcher` (the ipsw.me
    fallback) when both miss. The fetcher is injected so tests stay offline;
    without one, an unknown device returns None.
    """
    if product_type is None:
        return None
    product_type = str(product_type).strip()
    latest = _match_rules(product_type, _LATEST_RULES)
    if latest:
        return latest
    fallback = signed_target(product_type)
    if fallback:
        return fallback
    return fetcher(product_type) if fetcher else None


_BASEBAND_USE_RULES: Tuple[Tuple[Tuple[str, ...], Tuple[str, str]], ...] = (
    (("iPhone4,1",), ("Trek-6.7.00.Release.bbfw", "22a35425a3cdf8fa1458b5116cfb199448eecf49")),
    (
        ("iPad2,[67]",),
        ("Mav5-11.80.00.Release.bbfw", "aa52cf75b82fc686f94772e216008345b6a2a750"),
    ),
    (
        ("iPhone5,[12]", "iPad3,[56]"),
        ("Mav5-11.80.00.Release.bbfw", "8951cf09f16029c5c0533e951eb4c06609d0ba7f"),
    ),
    (
        ("iPad4,[235]", "iPhone5,[34]", "iPhone6,[12]"),
        ("Mav7Mav8-7.60.00.Release.bbfw", "f397724367f6bed459cf8f3d523553c13e8ae12c"),
    ),
)
"""Ordered (ProductType globs -> (bbfw name, sha1)) `device_use_bb`."""

_BASEBAND_LATEST_RULES: Tuple[Tuple[Tuple[str, ...], Tuple[str, str]], ...] = (
    (
        ("iPad4,[235689]", "iPhone6,[12]"),
        ("Mav7Mav8-10.80.02.Release.bbfw", "f5db17f72a78d807a791138dd5ca87d2f5e859f0"),
    ),
)
"""Ordered (ProductType globs -> (bbfw name, sha1)) `device_latest_bb`."""

_BASEBAND_FLAG_RULES: Tuple[Tuple[Tuple[str, ...], int], ...] = (
    (("iPad1,1", "iPhone[123],*"), 1),
    (("iPad[23],[23]",), 2),
)
"""Ordered (ProductType globs -> flag) for `device_use_bb2`."""


def latest_baseband(product_type) -> Optional[Tuple[str, str]]:
    """Return the latest-known (bbfw name, sha1) for a ProductType, or None."""
    if product_type is None:
        return None
    return _match_rules(str(product_type).strip(), _BASEBAND_LATEST_RULES)


def baseband(product_type) -> Optional[Tuple[str, str]]:
    """Return the baseband (bbfw name, sha1) to use for a ProductType.

    Mirrors Legacy-iOS-Kit: the `device_use_bb` table first; when a device has
    no use entry but has a latest entry, the latest is copied over. Devices
    with no baseband (WiFi iPads, newer chipsets) return None.
    """
    if product_type is None:
        return None
    product_type = str(product_type).strip()
    use = _match_rules(product_type, _BASEBAND_USE_RULES)
    if use:
        return use
    return latest_baseband(product_type)


def baseband_flag(product_type) -> int:
    """Return the `device_use_bb2` flag (0/1/2) for a ProductType."""
    if product_type is None:
        return 0
    product_type = str(product_type).strip()
    for patterns, flag in _BASEBAND_FLAG_RULES:
        if any(fnmatch.fnmatchcase(product_type, pat) for pat in patterns):
            return flag
    return 0


def _matches(product_type, patterns: Tuple[str, ...]) -> bool:
    """True when `product_type` matches any ProductType glob in `patterns`."""
    if not product_type:
        return False
    return any(fnmatch.fnmatchcase(str(product_type), pat) for pat in patterns)


_9900_CANDIDATE = ("iPhone4,1", "iPhone5,2", "iPad2,7", "iPad3,[26]")
_ACTIVATION_ISSUE = ("iPhone[123],[12]", "iPad1,1", "iPad2,2", "iPad3,3")
_CAN_POWDER = ("iPhone[345],*", "iPad1,1", "iPad[23],*", "iPod[35],1")
_CAN_DRA_V6 = ("iPad2,1", "iPhone4,1", "iPod4,1")
_POWDERSN0W_71 = ("iPad2,4", "iPad3,[123]", "iPhone4,1")


def is_9900_candidate(product_type) -> bool:
    """True for the devices LIK tracks as MDM6610/9615 baseband (`9900candidate`)."""
    return _matches(product_type, _9900_CANDIDATE)


def has_activation_issue(product_type) -> bool:
    """True for the devices LIK flags with a known activation issue."""
    return _matches(product_type, _ACTIVATION_ISSUE)


def can_powdersn0w(product_type) -> bool:
    """True when the device is eligible for a powdersn0w (downgrade) restore."""
    return _matches(product_type, _CAN_POWDER)


def can_dra_v6(product_type) -> bool:
    """True when the device supports the DRA v6 (data-recovery) path."""
    return _matches(product_type, _CAN_DRA_V6)


def activation_record_mode(
    product_type,
    *,
    saved_activation: bool = False,
    mode: str = "Normal",
    unactivated: bool = False,
) -> Optional[int]:
    """Return LIK's auto activation-record ladder code, or None.

    Mirrors the `device_auto_actrec` ladder: 1 = A5/A6 `9900candidate` device in
    Normal mode that is activated; 2 = a saved activation record exists for an
    A4-or-older device; 3 = a device with a known activation issue in Normal
    mode that is activated. The `--disable-actrec` override and on-disk
    activation tar are the caller's concern; pass `saved_activation` to model
    the latter.
    """
    proc = processor_generation(product_type)
    normal_activated = mode == "Normal" and not unactivated
    if proc in (5, 6) and is_9900_candidate(product_type) and normal_activated:
        return 1
    if saved_activation and proc <= 6:
        return 2
    if has_activation_issue(product_type) and normal_activated:
        return 3
    return None


def powdersn0w_versions(product_type) -> Tuple[str, str]:
    """Return LIK's `(check_vers, base_vers)` for a powdersn0w restore.

    Defaults to ("7", "7.x"); the A5 (non-X) set narrows the check to 7.1
    ("7.1.x"). On A4 (processor generation 4) both collapse to the device's
    latest signed version instead.
    """
    proc = processor_generation(product_type)
    if proc == 4:
        latest = latest_version(product_type)
        vers = latest[0] if latest else ""
        return vers, vers
    check = "7.1" if _matches(product_type, _POWDERSN0W_71) else "7"
    return check, f"{check}.x"


_MODE_RE = re.compile(r"^\s*MODE\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def parse_ecid(raw, *, base: int = 16) -> Optional[int]:
    """Parse an ECID into an int.

    `irecovery -q` prints the ECID as hex (usually without a "0x" prefix), so
    `base=16` is the default. Lockdown/`ideviceinfo` and manual entry give
    decimal, so pass `base=10` there. An int passes through; "" / None /
    unparseable values return None.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text, base)
    except ValueError:
        return None


def format_ecid(ecid) -> str:
    """Render an ECID as LIK does for logging: a plain decimal string."""
    if ecid is None:
        return ""
    if isinstance(ecid, str) and not ecid.strip():
        return ""
    try:
        return str(int(ecid))
    except (TypeError, ValueError):
        return ""


def parse_irecovery_mode(text) -> Optional[str]:
    """Return the MODE field from `irecovery -q` output (e.g. "DFU"), or None."""
    if not text:
        return None
    match = _MODE_RE.search(str(text))
    return match.group(1) if match else None


def parse_version(raw) -> Optional[Tuple[int, int]]:
    """Split an iOS version into (major, minor); None when it has no number.

    LIK only ever needs the major and minor components ("7.1.2" -> (7, 1));
    a missing minor component reads as 0.
    """
    if raw is None:
        return None
    parts = str(raw).strip().split(".")
    if not parts or not parts[0].isdigit():
        return None
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return major, minor


def manual_entry(
    *,
    device_type=None,
    hardware_model=None,
    ecid=None,
    version=None,
    build=None,
    mode: str = "Normal",
) -> Dict[str, object]:
    """Build a device-info dict from hand-entered values.

    Covers devices where lockdown reports nothing (iOS 2.x and older). The
    ProductType and board backfill each other when only one is given, and the
    ECID is treated as decimal (as LIK's manual entry and `ideviceinfo` do).
    """
    product_type = str(device_type).strip() if device_type else ""
    if not product_type and hardware_model:
        product_type = product_type_for_board(hardware_model) or ""
    if hardware_model:
        board = normalize_board(hardware_model)
    elif product_type:
        board = board_for_product_type(product_type) or ""
    else:
        board = ""
    return {
        "mode": mode or "Normal",
        "product_type": product_type,
        "board": board,
        "ecid": parse_ecid(ecid, base=10) if ecid not in (None, "") else None,
        "version": (version or "").strip(),
        "build": (build or "").strip(),
    }


def info_from_irecovery(text) -> Optional[dict]:
    """Parse `irecovery -q` output into the device_db shape, or None.

    Thin wrapper around `ramdisk_manager.parse_device_info` that adds the
    decimal ECID and the normalized board id; the irecovery parser itself is
    not duplicated.
    """
    from .ramdisk_manager import parse_device_info

    dev = parse_device_info(text) if text else None
    if dev is None:
        return None
    return {
        "mode": dev.get("mode", ""),
        "product_type": dev.get("product", ""),
        "board": normalize_board(dev.get("model", "")),
        "ecid": parse_ecid(dev.get("ecid", "")),
        "pwned": bool(dev.get("pwned")),
    }