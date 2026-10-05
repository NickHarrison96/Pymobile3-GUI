"""Offscreen smoke tests for the Recovery & Restore workspace tabs.

These verify the SSH Ramdisk tab wiring (tab index, button enable/disable
during tasks, DFU status labels, the iOS 16.1 build-block warning) without
any hardware or dialogs.
"""

import sys
from types import SimpleNamespace

import pytest

from PySide6.QtWidgets import QApplication

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
    assert view.tabs.count() == 5
    assert view.tabs.indexOf(view._ram_tab) == 2
    assert "SSH Ramdisk" in view.tabs.tabText(2)


def test_ramdisk_action_buttons_present(view):
    assert len(view._ram_buttons) == 7
    assert all(b.isEnabled() for b in view._ram_buttons)
    assert view.cmb_ram_version.count() >= 1


def test_dfu_label_checkm8_device(view):
    view._ram_dev = {"cpid": "0x8010", "model": "d221ap",
                     "product": "iPhone10,3", "ecid": "", "mode": "DFU"}
    view._update_ram_dfu_label()
    assert "checkm8 capable" in view.lbl_ram_dfu.text()
    assert "iPhone10,3" in view.lbl_ram_dfu.text()


def test_dfu_label_rejects_a16(view):
    view._ram_dev = {"cpid": "0x8747", "model": "t8030ap",
                     "product": "iPhone12,1", "ecid": "", "mode": "DFU"}
    view._update_ram_dfu_label()
    assert "not checkm8" in view.lbl_ram_dfu.text()


def test_dfu_label_no_device(view):
    view._ram_dev = None
    view._update_ram_dfu_label()
    assert "not detected" in view.lbl_ram_dfu.text()


def test_version_warn_blocks_ios_16_1_and_newer(view):
    view._ram_dev = {"cpid": "0x8010", "model": "d221ap",
                     "product": "iPhone10,3", "ecid": "", "mode": "DFU"}
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
