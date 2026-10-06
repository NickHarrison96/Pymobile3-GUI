"""Offscreen smoke tests for the Recovery & Restore workspace tabs.

These verify the SSH Ramdisk tab wiring (tab index, button enable/disable
during tasks, DFU status labels, the iOS 16.1 build-block warning) and the
experimental A12/A13 tab next to it, without any hardware or dialogs.
"""

import sys
from types import SimpleNamespace

import pytest

from PySide6.QtWidgets import QApplication, QLabel

from pymobile3_gui.views.restore_view import RestoreView


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


@pytest.fixture(scope="module")
def view(qapp):
    return RestoreView()


def _set_version(view, version):
    view.cmb_ram_version.blockSignals(True)
    view.cmb_ram_version.clear()
    view.cmb_ram_version.addItem(version, version)
    view.cmb_ram_version.blockSignals(False)


def test_five_tabs_with_ramdisk_at_index(view):
    assert view.tabs.count() == 6
    assert view.tabs.indexOf(view._ram_tab) == 2
    assert "SSH Ramdisk" in view.tabs.tabText(2)


def test_ramdisk_action_buttons_present(view):
    assert len(view._ram_buttons) == 7
    assert all(b.isEnabled() for b in view._ram_buttons)
    assert view.cmb_ram_version.count() >= 1


def _dev(**over):
    base = {"cpid": "0x8010", "model": "d221ap", "product": "iPhone10,3",
            "name": "", "ecid": "", "mode": "DFU"}
    base.update(over)
    return base


def test_dfu_label_checkm8_device(view):
    view._ram_dev = _dev()
    view._update_ram_dfu_label()
    assert "checkm8 capable" in view.lbl_ram_dfu.text()
    assert "iPhone10,3" in view.lbl_ram_dfu.text()


def test_dfu_label_prefers_irecovery_name(view):
    view._ram_dev = _dev(name="iPhone 8 (GSM)")
    view._update_ram_dfu_label()
    assert "iPhone 8 (GSM)" in view.lbl_ram_dfu.text()


def test_dfu_label_falls_back_to_cpid_table(view):
    # No name and no product: the CPID table has to identify the hardware.
    view._ram_dev = _dev(cpid="0x8015", product="", model="")
    view._update_ram_dfu_label()
    assert "iPhone 8 / iPhone 8 Plus / iPhone X" in view.lbl_ram_dfu.text()


def test_dfu_label_unknown_cpid_says_unknown_device(view):
    view._ram_dev = _dev(cpid="0xdead", product="", model="")
    view._update_ram_dfu_label()
    assert "Unknown device" in view.lbl_ram_dfu.text()
    assert "not checkm8" in view.lbl_ram_dfu.text()


def test_dfu_label_rejects_a16(view):
    view._ram_dev = _dev(cpid="0x8747", model="t8030ap", product="iPhone12,1")
    view._update_ram_dfu_label()
    assert "not checkm8" in view.lbl_ram_dfu.text()


def test_dfu_label_no_device(view):
    view._ram_dev = None
    view._update_ram_dfu_label()
    assert "not detected" in view.lbl_ram_dfu.text()


def test_version_warn_blocks_ios_16_1_and_newer(view):
    view._ram_dev = _dev()
    _set_version(view, "16.1")
    view._update_ram_version_warn()
    assert not view.lbl_ram_version_warn.isHidden()

    _set_version(view, "15.7.1")
    view._update_ram_version_warn()
    assert view.lbl_ram_version_warn.isHidden()


def test_version_warn_requires_device(view):
    view._ram_dev = None
    _set_version(view, "16.1")
    view._update_ram_version_warn()
    assert view.lbl_ram_version_warn.isHidden()


def test_busy_state_disables_and_restores_buttons(view):
    assert all(b.isEnabled() for b in view._ram_buttons)

    view._on_ram_task_started(SimpleNamespace(task_id="ramdisk_create_1"))
    assert view._ram_busy is True
    assert all(not b.isEnabled() for b in view._ram_buttons)

    view._on_ram_task_finished(SimpleNamespace(task_id="ramdisk_create_1"))
    assert view._ram_busy is False
    assert all(b.isEnabled() for b in view._ram_buttons)

    # Unrelated tasks must not touch the ramdisk buttons.
    view._on_ram_task_started(SimpleNamespace(task_id="acquisition_1"))
    assert view._ram_busy is False
    assert all(b.isEnabled() for b in view._ram_buttons)
    view._on_ram_task_finished(SimpleNamespace(task_id="acquisition_1"))


def test_dfu_timer_follows_selected_tab(view):
    view.tabs.setCurrentIndex(2)
    assert view._dfu_timer.isActive()

    view.tabs.setCurrentIndex(0)
    assert not view._dfu_timer.isActive()


def _ich_dev(**over):
    base = {"cpid": "0x8030", "model": "d321ap", "product": "iPhone12,1",
            "name": "", "ecid": "", "mode": "DFU", "pwnd": "usbliter8"}
    base.update(over)
    return base


def test_experimental_tab_sits_next_to_checkm8_tab(view):
    assert view.tabs.indexOf(view._ich_tab) == 3
    assert "A12/A13" in view.tabs.tabText(3)
    assert len(view._ich_buttons) == 5
    assert all(b.isEnabled() for b in view._ich_buttons)


def test_experimental_banner_carries_the_disclaimer(view):
    labels = [lbl.text() for lbl in view._ich_tab.findChildren(QLabel)]
    banner = [t for t in labels if "HIGHLY EXPERIMENTAL" in t]
    assert banner, "no disclaimer label on the A12/A13 tab"
    assert "not responsible for any result" in banner[0]


def test_experimental_tab_reports_a12a13_device(view):
    view._ram_dev = _ich_dev()
    view._update_ich_dev_label()
    assert "0x8030" in view.lbl_ich_dev.text()
    assert "usbliter8" in view.lbl_ich_dev.text()


def test_experimental_tab_flags_unpwned_device(view):
    view._ram_dev = _ich_dev(pwnd="")
    view._update_ich_dev_label()
    assert "not pwned" in view.lbl_ich_dev.text()


def test_experimental_tab_rejects_checkm8_device(view):
    view._ram_dev = _dev()
    view._update_ich_dev_label()
    assert "not an A12/A13 chip" in view.lbl_ich_dev.text()
    assert "SSH Ramdisk tab" in view.lbl_ich_dev.text()


def test_experimental_ticket_label_follows_the_toolkit(view, tmp_path):
    view._ram_dev = _ich_dev()
    view.txt_ich_toolkit.setText(str(tmp_path))
    view._update_ich_ticket()
    assert "No APTicket" in view.lbl_ich_ticket.text()

    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "IM4M_0x8030").write_bytes(b"\x30\x82\x01\x0d")
    view._update_ich_ticket()
    assert "APTicket: IM4M_0x8030" in view.lbl_ich_ticket.text()
    assert "No APTicket" not in view.lbl_ich_ticket.text()


def test_experimental_trustcache_field_follows_the_mode(view):
    assert view.cmb_ich_tc.currentData() == "prepared"
    assert view.txt_ich_trustcache.isEnabled()

    view.cmb_ich_tc.setCurrentIndex(1)
    assert not view.txt_ich_trustcache.isEnabled()

    view.cmb_ich_tc.setCurrentIndex(0)
    assert view.txt_ich_trustcache.isEnabled()


def test_experimental_busy_state_only_touches_its_own_buttons(view):
    view._on_ich_task_started(SimpleNamespace(task_id="ich_create_1"))
    assert view._ich_busy is True
    assert all(not b.isEnabled() for b in view._ich_buttons)
    assert all(b.isEnabled() for b in view._ram_buttons)

    view._on_ich_task_finished(SimpleNamespace(task_id="ich_create_1"))
    assert view._ich_busy is False
    assert all(b.isEnabled() for b in view._ich_buttons)

    # A checkm8 task must not flip the experimental tab into its busy state.
    view._on_ich_task_started(SimpleNamespace(task_id="ramdisk_boot_1"))
    assert view._ich_busy is False


def test_experimental_busy_state_stops_the_shared_dfu_poll(view):
    view.tabs.setCurrentIndex(3)
    assert view._dfu_timer.isActive()
    view._on_ich_task_started(SimpleNamespace(task_id="ich_create_1"))
    assert not view._dfu_timer.isActive()


def test_both_ramdisk_tabs_get_the_version_list(view):
    firmwares = [{"version": "17.5.1", "signed": True},
                 {"version": "18.0", "signed": False}]
    view._populate_versions(firmwares)
    for combo in (view.cmb_ram_version, view.cmb_ich_version):
        assert combo.count() == 2
        assert combo.currentData() == "17.5.1"
        assert combo.itemText(1).endswith("(unsigned)")
