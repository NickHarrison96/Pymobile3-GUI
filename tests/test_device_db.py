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