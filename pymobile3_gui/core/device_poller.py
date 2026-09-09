"""
Pymobile3-GUI - Device Poller
Asynchronously queries usbmuxd and lockdown to discover connected iOS devices,
gather device metadata (Model, iOS version, UDID, Battery, Connection type, Pairing),
and emit structured PySide6 signals without blocking the GUI.
"""

import sys
import asyncio
import inspect
from typing import Dict, Any, Optional
from PySide6.QtCore import QThread, Signal


class DevicePoller(QThread):
    device_discovered = Signal(dict)
    device_disconnected = Signal()
    poll_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = True
        self._last_serial = None

    def run(self):
        """Main thread execution polling device state."""
        try:
            result = asyncio.run(self._fetch_device_info())
            if result:
                self.device_discovered.emit(result)
            else:
                self.device_disconnected.emit()
        except Exception as e:
            self.poll_error.emit(str(e))
            self.device_disconnected.emit()

    async def _fetch_device_info(self) -> Dict[str, Any]:
        """Queries pymobiledevice3 usbmux and lockdown."""
        try:
            import pymobiledevice3
            from pymobiledevice3.usbmux import list_devices
            from pymobiledevice3.lockdown import create_using_usbmux
        except ImportError:
            self.poll_error.emit("pymobiledevice3 is not installed in the active environment.")
            return {}

        # ── 1. List devices ──────────────────────────────────────────────
        try:
            raw_devices = list_devices()
            devices = list(await raw_devices if inspect.iscoroutine(raw_devices) else raw_devices)
        except Exception as e:
            self.poll_error.emit(f"Failed to query usbmux: {e}")
            return {}

        if not devices:
            return {}

        dev = devices[0]
        conn_type = "Wi-Fi" if getattr(dev, "connection_type", "").lower() == "network" else "USB"
        serial = getattr(dev, "serial", "Unknown")

        # ── 2. Open lockdown ─────────────────────────────────────────────
        lockdown = None
        try:
            raw_ld = create_using_usbmux(serial=serial)
            lockdown = await raw_ld if inspect.iscoroutine(raw_ld) else raw_ld
        except Exception as e:
            # Device might be locked or untrusted
            return {
                "Model": "Apple Device",
                "ProductType": "Unknown",
                "OS": "iOS (Untrusted)",
                "Serial_UDID": serial,
                "Connection": conn_type,
                "Trusted": False,
                "Battery": "N/A",
                "Activation": "Unknown",
                "Error": str(e),
            }

        # ── 3. Query lockdown values ─────────────────────────────────────
        async def get_val(domain: Optional[str] = None, key: Optional[str] = None):
            try:
                if domain:
                    raw = lockdown.get_value(domain=domain, key=key)
                else:
                    raw = lockdown.get_value(key=key)
                return await raw if inspect.iscoroutine(raw) else raw
            except Exception:
                return None

        product_type = await get_val(key="ProductType") or "Unknown"
        product_name = await get_val(key="ProductName") or product_type
        os_ver = await get_val(key="ProductVersion") or "Unknown"
        build_ver = await get_val(key="BuildVersion") or ""
        device_name = await get_val(key="DeviceName") or product_name
        serial_num = await get_val(key="SerialNumber") or serial
        unique_chip_id = await get_val(key="UniqueChipID") or ""
        imei = await get_val(key="InternationalMobileEquipmentIdentity") or "N/A"
        activation = await get_val(key="ActivationState") or "Unknown"
        wifi_mac = await get_val(key="WiFiAddress") or "N/A"
        bluetooth_mac = await get_val(key="BluetoothAddress") or "N/A"
        time_zone = await get_val(key="TimeZone") or "N/A"

        # Battery
        battery = await get_val(domain="com.apple.mobile.battery", key="BatteryCurrentCapacity")
        battery_charging = await get_val(domain="com.apple.mobile.battery", key="BatteryIsCharging")

        # Developer Mode
        dev_mode = await get_val(domain="com.apple.security.mac.amfi", key="DeveloperModeStatus")

        return {
            "DeviceName": device_name,
            "Model": product_name,
            "ProductType": product_type,
            "OS": f"iOS {os_ver}" + (f" ({build_ver})" if build_ver else ""),
            "OS_Version_Raw": os_ver,
            "Serial_UDID": serial,
            "SerialNumber": serial_num,
            "ECID": hex(unique_chip_id) if isinstance(unique_chip_id, int) else str(unique_chip_id),
            "IMEI": imei,
            "Activation": activation,
            "Connection": conn_type,
            "Trusted": True,
            "Battery": f"{battery}%" if battery is not None else "Unknown",
            "BatteryCapacity": battery if isinstance(battery, int) else 0,
            "IsCharging": bool(battery_charging),
            "DeveloperMode": bool(dev_mode),
            "WiFiAddress": wifi_mac,
            "BluetoothAddress": bluetooth_mac,
            "TimeZone": time_zone,
        }
