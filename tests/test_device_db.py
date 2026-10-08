"""Offline tests for the device capability database (B1a: board <-> ProductType)."""

import pytest

from pymobile3_gui.core.backend import device_db as db


def test_registry_has_expected_size():
    assert len(db.REGISTRY) == 81


def test_registry_pairs_are_unique():
    pairs = [(row.board, row.product_type) for row in db.REGISTRY]
    assert len(pairs) == len(set(pairs))


def test_every_board_resolves_to_its_product_type():
    for row in db.REGISTRY:
        assert db.product_type_for_board(row.board) == row.product_type


def test_every_product_type_lists_its_boards():
    for row in db.REGISTRY:
        assert row.board in db.boards_for_product_type(row.product_type)


def test_canonical_board_round_trips_for_unambiguous_types():
    for product_type in db._TYPE_TO_BOARDS:
        if db.is_ambiguous(product_type):
            continue
        board = db.board_for_product_type(product_type)
        assert board is not None
        assert db.product_type_for_board(board) == product_type


def test_ambiguous_types_have_no_canonical_board():
    for product_type in db.AMBIGUOUS_PRODUCT_TYPES:
        assert db.is_ambiguous(product_type)
        assert db.board_for_product_type(product_type) is None
        assert len(db.boards_for_product_type(product_type)) == 2


def test_ambiguous_set_matches_multi_board_types():
    multi = {pt for pt, boards in db._TYPE_TO_BOARDS.items() if len(boards) > 1}
    assert multi == set(db.AMBIGUOUS_PRODUCT_TYPES)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("N71AP", "n71"),
        ("n71ap", "n71"),
        ("n71", "n71"),
        ("D201AP", "d201"),
        ("K93A", "k93a"),
        ("  J71SAP  ", "j71s"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_board(raw, expected):
    assert db.normalize_board(raw) == expected


def test_unknown_board_and_product_type():
    assert db.product_type_for_board("zz99") is None
    assert db.product_type_for_board(None) is None
    assert db.boards_for_product_type("iPhone99,9") == ()
    assert db.board_for_product_type("iPhone99,9") is None
    assert db.board_for_product_type("") is None


def test_resolve_ipod_touch_4_quirk():
    assert db.resolve_identity("N81AP") == ("iPod4,1", "n81")


def test_resolve_ipad2_1_board_quirk():
    assert db.resolve_identity("K93AP") == ("iPad2,1", "k93")
    assert db.resolve_identity("J1AP", reported_product_type="iPad2,1") == (
        "iPad2,1",
        "k93",
    )


def test_resolve_board_takes_precedence_over_reported_type():
    assert db.resolve_identity("N71AP", reported_product_type="iPhone8,2") == (
        "iPhone8,1",
        "n71",
    )


@pytest.mark.parametrize(
    "model,product_type,board",
    [
        ("M68AP", "iPhone1,1", "m68"),
        ("N94AP", "iPhone4,1", "n94"),
        ("D201AP", "iPhone10,4", "d201"),
        ("J71SAP", "iPad6,11", "j71s"),
        ("N112AP", "iPod9,1", "n112"),
    ],
)
def test_resolve_known_models(model, product_type, board):
    assert db.resolve_identity(model) == (product_type, board)


def test_resolve_uses_reported_type_when_board_unknown():
    assert db.resolve_identity("ZZ99AP", reported_product_type="iPhone10,4") == (
        "iPhone10,4",
        "zz99",
    )


def test_resolve_empty_inputs():
    assert db.resolve_identity() == ("", "")
    assert db.resolve_identity(None, "") == ("", "")


def test_every_registry_row_has_a_processor_generation():
    for row in db.REGISTRY:
        assert 1 <= db.processor_generation(row.product_type) <= 11


@pytest.mark.parametrize(
    "product_type,generation",
    [
        ("iPhone1,1", 1),
        ("iPod1,1", 1),
        ("iPad1,1", 4),
        ("iPhone2,1", 4),
        ("iPhone3,1", 4),
        ("iPod4,1", 4),
        ("iPad2,1", 5),
        ("iPad3,1", 5),
        ("iPad3,3", 5),
        ("iPhone4,1", 5),
        ("iPod5,1", 5),
        ("iPad3,4", 6),
        ("iPhone5,3", 6),
        ("iPad4,1", 7),
        ("iPhone6,2", 7),
        ("iPad5,4", 8),
        ("iPhone7,1", 8),
        ("iPod7,1", 8),
        ("iPad6,11", 9),
        ("iPhone8,4", 9),
        ("iPad7,12", 10),
        ("iPhone9,3", 10),
        ("iPhone10,6", 10),
        ("iPod9,1", 10),
    ],
)
def test_processor_generation_table(product_type, generation):
    assert db.processor_generation(product_type) == generation


def test_processor_generation_unknown_and_newer():
    assert db.processor_generation("iPhone99,1") == 11
    assert db.processor_generation("iPad99,1") == 11
    assert db.processor_generation("AppleTV5,3") == 11
    assert db.processor_generation("nonsense") == 0
    assert db.processor_generation(None) == 0
    assert db.processor_generation("") == 0


def test_processor_name():
    assert db.processor_name("iPhone10,6") == "A10/A11"
    assert db.processor_name("iPad2,1") == "A5"
    assert db.processor_name("nonsense") == ""


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPad6,11", True),
        ("iPad6,12", True),
        ("iPad7,1", True),
        ("iPad7,12", True),
        ("iPad5,3", False),
        ("iPhone9,1", False),
        ("nonsense", False),
        (None, False),
    ],
)
def test_checkm8_ipad(product_type, expected):
    assert db.checkm8_ipad(product_type) is expected


def test_registry_keys_are_split_correctly():
    for row in db.REGISTRY:
        parts = db._split_product_type(row.product_type)
        assert parts is not None
        assert f"{parts[0]}{parts[1]},{parts[2]}" == row.product_type