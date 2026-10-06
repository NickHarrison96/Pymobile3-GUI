"""Unit tests for the CPID device-identification table.

Pure data/logic — no hardware, no Qt. The point of the table is that a DFU
device reports only a CPID, so these lock down that every id in the table
resolves and that unknown/unnormalized input degrades safely.
"""

import pytest

from pymobile3_gui.core.backend import device_ident as ident


# -----------------------------------------------------------------------------
# Normalization
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("0x8015", "0x8015"),
    ("0X8015", "0x8015"),
    ("  0x8015  ", "0x8015"),
    ("8015", "0x8015"),
    ("0x008015", "0x8015"),
    (0x8015, "0x8015"),
    ("0x8900", "0x8900"),
    (None, ""),
    ("", ""),
    ("0x", ""),
])
def test_normalize_cpid(raw, expected):
    assert ident.normalize_cpid(raw) == expected


# -----------------------------------------------------------------------------
# Table integrity
# -----------------------------------------------------------------------------

def test_every_row_resolves_to_itself():
    for row in ident.IPHONE_CPIDS:
        assert ident.lookup(row.cpid) is row


def test_no_duplicate_canonical_ids():
    cpids = [row.cpid for row in ident.IPHONE_CPIDS]
    assert len(cpids) == len(set(cpids))


def test_aliases_resolve_and_are_not_canonical_rows():
    canonical = set(ident.CPID_TABLE)
    for alias, target in ident.CPID_ALIASES.items():
        assert alias not in canonical
        assert ident.lookup(alias) is ident.lookup(target)


def test_table_covers_the_published_iphone_range():
    # Oldest to newest, with the multi-id A9 row split into 0x8000/0x8003.
    for cpid in ("0x8900", "0x8920", "0x8930", "0x8940", "0x8942", "0x8950",
                 "0x8960", "0x7000", "0x8000", "0x8003", "0x8010", "0x8015",
                 "0x8020", "0x8030", "0x8101", "0x8110", "0x8120", "0x8130",
                 "0x8140", "0x8150", "0x8160"):
        assert ident.is_known(cpid), cpid


def test_rows_have_processor_and_models():
    for row in ident.IPHONE_CPIDS:
        assert row.processor
        assert row.models
        assert all(isinstance(m, str) and m for m in row.models)


# -----------------------------------------------------------------------------
# The device on the bench (iPhone 8, A11)
# -----------------------------------------------------------------------------

def test_a11_names_the_iphone_8_family():
    assert ident.models("0x8015") == (
        "iPhone 8", "iPhone 8 Plus", "iPhone X")


def test_a11_describe_prefixes_chip_name():
    text = ident.describe("0x8015")
    assert text.startswith("A11 Bionic — ")
    assert "iPhone 8" in text


@pytest.mark.parametrize("cpid,chip", [
    ("0x8010", "A10 Fusion"),
    ("0x8015", "A11 Bionic"),
    ("0x8020", "A12 Bionic"),
    ("0x8120", "A16 Bionic"),
    ("0x8160", "A20 Pro"),
])
def test_chip_names_match_the_published_table(cpid, chip):
    assert ident.lookup(cpid).chip == chip


def test_rows_without_a_chip_name_fall_back_to_the_processor():
    # S5L8900 / S5L8920 are listed with no SoC name.
    for cpid in ("0x8900", "0x8920"):
        row = ident.lookup(cpid)
        assert row.chip == ""
        assert ident.describe(cpid).startswith(row.processor)


# -----------------------------------------------------------------------------
# Unknown input
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["0xdead", "0x8747", "", None, 0xDEAD])
def test_unknown_cpid_is_handled(raw):
    assert ident.lookup(raw) is None
    assert ident.is_known(raw) is False
    assert ident.models(raw) == ()
    assert ident.name(raw) == ""
    assert ident.describe(raw) == ""


def test_lookup_normalizes_before_matching():
    assert ident.lookup("0X8015") is ident.lookup("8015")