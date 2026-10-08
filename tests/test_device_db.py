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


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPhone1,1", ("3.1.3", "7E18")),
        ("iPod2,1", ("4.2.1", "8C148")),
        ("iPad1,1", ("5.1.1", "9B206")),
        ("iPhone2,1", ("6.1.6", "10B500")),
        ("iPhone3,3", ("7.1.2", "11D257")),
        ("iPad2,4", ("9.3.5", "13G36")),
        ("iPhone4,1", ("9.3.6", "13G37")),
        ("iPhone5,4", ("10.3.4", "14G61")),
        ("iPhone6,2", ("10.3.3", "14G60")),
        ("iPhone8,1", None),
        ("iPhone12,1", None),
        (None, None),
    ],
)
def test_signed_target(product_type, expected):
    assert db.signed_target(product_type) == expected


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPad4,1", ("12.5.8", "16H88")),
        ("iPhone7,1", ("12.5.8", "16H88")),
        ("iPod7,1", ("12.5.8", "16H88")),
        ("iPhone8,1", ("15.8.8", "19H422")),
        ("iPod9,1", ("15.8.8", "19H422")),
        ("iPhone10,4", ("16.7.16", "20H392")),
        ("iPad6,11", ("16.7.16", "20H392")),
        ("iPad7,4", ("17.7.11", "21H461")),
        ("iPad7,12", ("18.7.9", "22H355")),
        ("iPhone11,8", ("18.7.9", "22H355")),
    ],
)
def test_latest_version_table(product_type, expected):
    assert db.latest_version(product_type) == expected


def test_latest_version_falls_back_to_signed_target():
    assert db.latest_version("iPhone1,1") == ("3.1.3", "7E18")
    assert db.latest_version("iPhone4,1") == ("9.3.6", "13G37")


def test_latest_version_uses_fetcher_when_tables_miss():
    calls = []

    def fetcher(product_type):
        calls.append(product_type)
        return ("26.1", "23B77")

    assert db.latest_version("iPhone20,1", fetcher=fetcher) == ("26.1", "23B77")
    assert calls == ["iPhone20,1"]


def test_latest_version_fetcher_not_called_when_table_hits():
    def fetcher(product_type):
        raise AssertionError("fetcher must not be called")

    assert db.latest_version("iPhone10,4", fetcher=fetcher) == ("16.7.16", "20H392")
    assert db.latest_version(None, fetcher=fetcher) is None


@pytest.mark.parametrize(
    "product_type,expected_name,expected_sha1",
    [
        ("iPhone4,1", "Trek-6.7.00.Release.bbfw", "22a35425a3cdf8fa1458b5116cfb199448eecf49"),
        ("iPad2,7", "Mav5-11.80.00.Release.bbfw", "aa52cf75b82fc686f94772e216008345b6a2a750"),
        ("iPhone5,2", "Mav5-11.80.00.Release.bbfw", "8951cf09f16029c5c0533e951eb4c06609d0ba7f"),
        ("iPhone6,1", "Mav7Mav8-7.60.00.Release.bbfw", "f397724367f6bed459cf8f3d523553c13e8ae12c"),
        ("iPad4,6", "Mav7Mav8-10.80.02.Release.bbfw", "f5db17f72a78d807a791138dd5ca87d2f5e859f0"),
    ],
)
def test_baseband(product_type, expected_name, expected_sha1):
    assert db.baseband(product_type) == (expected_name, expected_sha1)


@pytest.mark.parametrize("product_type", ["iPad4,1", "iPad4,4", "iPad4,7", "iPhone8,1", None])
def test_baseband_absent(product_type):
    assert db.baseband(product_type) is None
    assert db.latest_baseband(product_type) is None


def test_baseband_digests_are_sha1():
    for product_type in ("iPhone4,1", "iPad2,7", "iPhone5,2", "iPhone6,1", "iPad4,6"):
        _name, sha1 = db.baseband(product_type)
        assert len(sha1) == 40
        int(sha1, 16)


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPad1,1", 1),
        ("iPhone1,1", 1),
        ("iPhone2,1", 1),
        ("iPhone3,1", 1),
        ("iPad2,3", 2),
        ("iPad3,2", 2),
        ("iPad2,1", 0),
        ("iPhone6,1", 0),
        ("iPad4,1", 0),
        (None, 0),
    ],
)
def test_baseband_flag(product_type, expected):
    assert db.baseband_flag(product_type) == expected


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPhone4,1", True),
        ("iPhone5,2", True),
        ("iPad2,7", True),
        ("iPad3,2", True),
        ("iPad3,6", True),
        ("iPhone5,1", False),
        ("iPad3,4", False),
        (None, False),
    ],
)
def test_is_9900_candidate(product_type, expected):
    assert db.is_9900_candidate(product_type) is expected


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPhone1,1", True),
        ("iPhone2,2", True),
        ("iPhone3,2", True),
        ("iPhone3,3", False),
        ("iPad1,1", True),
        ("iPad2,2", True),
        ("iPad3,3", True),
        ("iPad2,1", False),
        (None, False),
    ],
)
def test_has_activation_issue(product_type, expected):
    assert db.has_activation_issue(product_type) is expected


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPhone3,1", True),
        ("iPhone4,1", True),
        ("iPhone5,2", True),
        ("iPad1,1", True),
        ("iPad2,4", True),
        ("iPad3,6", True),
        ("iPod3,1", True),
        ("iPod5,1", True),
        ("iPhone6,1", False),
        ("iPod4,1", False),
        (None, False),
    ],
)
def test_can_powdersn0w(product_type, expected):
    assert db.can_powdersn0w(product_type) is expected


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPad2,1", True),
        ("iPhone4,1", True),
        ("iPod4,1", True),
        ("iPad2,2", False),
        (None, False),
    ],
)
def test_can_dra_v6(product_type, expected):
    assert db.can_dra_v6(product_type) is expected


@pytest.mark.parametrize(
    "product_type,expected",
    [
        ("iPad2,4", ("7.1", "7.1.x")),
        ("iPhone4,1", ("7.1", "7.1.x")),
        ("iPhone5,1", ("7", "7.x")),
        ("iPhone3,1", ("7.1.2", "7.1.2")),
        ("iPhone2,1", ("6.1.6", "6.1.6")),
    ],
)
def test_powdersn0w_versions(product_type, expected):
    assert db.powdersn0w_versions(product_type) == expected


@pytest.mark.parametrize(
    "product_type,kwargs,expected",
    [
        ("iPhone4,1", {}, 1),
        ("iPhone4,1", {"unactivated": True}, None),
        ("iPhone4,1", {"mode": "Recovery"}, None),
        ("iPhone4,1", {"saved_activation": True}, 1),
        ("iPhone2,1", {"saved_activation": True}, 2),
        ("iPhone1,1", {}, 3),
        ("iPhone1,1", {"saved_activation": True}, 2),
        ("iPhone1,1", {"unactivated": True}, None),
        ("iPhone8,1", {}, None),
    ],
)
def test_activation_record_mode(product_type, kwargs, expected):
    assert db.activation_record_mode(product_type, **kwargs) == expected


@pytest.mark.parametrize(
    "raw,base,expected",
    [
        ("0x1a2b", 16, 6699),
        ("1a2b", 16, 6699),
        ("0X1A2B", 16, 6699),
        ("123456789", 10, 123456789),
        (12345, 16, 12345),
        ("", 16, None),
        (None, 16, None),
        ("zz", 16, None),
    ],
)
def test_parse_ecid(raw, base, expected):
    assert db.parse_ecid(raw, base=base) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (6699, "6699"),
        ("6699", "6699"),
        (None, ""),
        ("", ""),
        ("nope", ""),
    ],
)
def test_format_ecid(raw, expected):
    assert db.format_ecid(raw) == expected


def test_parse_irecovery_mode():
    text = "CPID: 8015\nMODEL: n71ap\nMODE: DFU\nECID: 1234\n"
    assert db.parse_irecovery_mode(text) == "DFU"
    assert db.parse_irecovery_mode("mode: Recovery") == "Recovery"
    assert db.parse_irecovery_mode("no mode here") is None
    assert db.parse_irecovery_mode("") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("16.0.3", (16, 0)),
        ("9", (9, 0)),
        ("7.1", (7, 1)),
        ("", None),
        (None, None),
        ("x.y", None),
    ],
)
def test_parse_version(raw, expected):
    assert db.parse_version(raw) == expected


def test_manual_entry_from_hardware_model():
    info = db.manual_entry(hardware_model="N71AP", ecid="123456789", version="9.0", build="13A344")
    assert info["product_type"] == "iPhone8,1"
    assert db.product_type_for_board("n71") == "iPhone8,1"
    assert info["board"] == "n71"
    assert db.parse_version("3.9") == (3, 9)
    assert db.manual_entry(hardware_model="k93")["product_type"] == "iPad2,1"


def test_manual_entry_derives_board_from_type():
    info = db.manual_entry(device_type="iPhone6,1", ecid="123", version="9.3.5", build="13G36")
    assert info["product_type"] == "iPhone6,1"
    assert db.normalize_board(db.board_for_product_type("iPhone6,1")) == "n51"
    assert db.info_from_irecovery(
        "CPID: 8960\nMODEL: n51ap\nPRODUCT: iPhone6,1\nMODE: DFU\nECID: 1a2b\n"
    )["board"] == "n51"


def test_manual_entry_decimal_ecid():
    entry = db.manual_entry(device_type="iPhone6,1", ecid="1234567890")
    assert entry["ecid"] == 1234567890


def test_manual_entry_defaults():
    entry = db.manual_entry()
    assert entry["product_type"] == ""
    assert db.manual_entry(device_type=None)["board"] == ""
    assert db.manual_entry(device_type="iPhone8,1")["board"] == ""
    assert db.manual_entry(hardware_model="n71").get("version", "") == ""


def test_info_from_irecovery():
    text = (
        "CPID: 8015\nMODEL: n71ap\nPRODUCT: iPhone8,1\n"
        "MODE: DFU\nECID: 123456789abcd\nPWND: CHECKM8\n"
    )
    info = db.info_from_irecovery(text)
    assert info == {
        "mode": "DFU",
        "product_type": "iPhone8,1",
        "board": "n71",
        "ecid": int("123456789abcd", 16),
        "pwned": True,
    }
    assert db.info_from_irecovery("") is None
    assert db.info_from_irecovery(None) is None