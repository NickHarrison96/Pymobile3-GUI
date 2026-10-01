"""
Pymobile3-GUI - Lockdown Operations
Device control and settings management via pymobiledevice3 lockdown services.
"""

import asyncio
import time

from pymobiledevice3.exceptions import MissingValueError, LockdownError


class LockdownOps:
    """Manager for lockdown and diagnostics operations."""

    def __init__(self, udid: str | None = None):
        self.udid = udid

    async def _get_lockdown(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        if self.udid:
            return await create_using_usbmux(serial=self.udid)
        return await create_using_usbmux()

    async def restart_device(self) -> str:
        lockdown = await self._get_lockdown()
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with DiagnosticsService(lockdown) as diag:
            await diag.restart()
            return "Device restart command sent."

    async def shutdown_device(self) -> str:
        lockdown = await self._get_lockdown()
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with DiagnosticsService(lockdown) as diag:
            await diag.shutdown()
            return "Device shutdown command sent."

    async def sleep_device(self) -> str:
        lockdown = await self._get_lockdown()
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with DiagnosticsService(lockdown) as diag:
            await diag.sleep()
            return "Device sleep command sent."

    async def get_device_name(self) -> str:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(key="DeviceName")
            return str(result) if result else "Unknown"
        except (MissingValueError, LockdownError):
            return "Unknown"

    async def set_device_name(self, name: str) -> str:
        lockdown = await self._get_lockdown()
        await lockdown.set_value(key="DeviceName", value=name)
        return f"Device name set to '{name}'."

    async def get_date(self) -> str:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(key="TimeIntervalSince1970")
            if result:
                return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(result)))
            return "Unknown"
        except (MissingValueError, LockdownError):
            return "Unknown"

    async def get_language(self) -> str:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(domain="com.apple.international", key="Language")
            if result:
                return str(result)
        except (MissingValueError, LockdownError):
            pass
        for key in ("UserAssignedDeviceLanguage", "Language", "UserLanguage"):
            try:
                result = await lockdown.get_value(key=key)
                if result:
                    return str(result)
            except (MissingValueError, LockdownError):
                continue
        return "Unknown"

    async def get_locale(self) -> str:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(domain="com.apple.international", key="Locale")
            if result:
                return str(result)
        except (MissingValueError, LockdownError):
            pass
        for key in ("UserLocale", "Locale", "AppleLocale"):
            try:
                result = await lockdown.get_value(key=key)
                if result:
                    return str(result)
            except (MissingValueError, LockdownError):
                continue
        return "Unknown"

    async def get_assistive_touch(self) -> bool:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(
                domain="com.apple.Accessibility", key="AssistiveTouchEnabledByiTunes"
            )
            return bool(result)
        except (MissingValueError, LockdownError):
            return False

    async def set_assistive_touch(self, enabled: bool) -> str:
        lockdown = await self._get_lockdown()
        await lockdown.set_value(
            domain="com.apple.Accessibility",
            key="AssistiveTouchEnabledByiTunes",
            value=enabled,
        )
        state = "on" if enabled else "off"
        return f"Assistive Touch set to {state}."

    async def get_wifi_connections(self) -> bool:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(
                domain="com.apple.mobile.wireless_lockdown",
                key="EnableWifiConnections",
            )
            return bool(result)
        except (MissingValueError, LockdownError):
            return None

    async def set_wifi_connections(self, enabled: bool) -> str:
        lockdown = await self._get_lockdown()
        await lockdown.set_value(
            domain="com.apple.mobile.wireless_lockdown",
            key="EnableWifiConnections",
            value=enabled,
        )
        state = "on" if enabled else "off"
        return f"WiFi Connections set to {state}."

    async def get_battery_info(self) -> dict:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(domain="com.apple.mobile.battery")
            return result if result else {}
        except (MissingValueError, LockdownError):
            return {}

    async def get_activation_state(self) -> str:
        lockdown = await self._get_lockdown()
        try:
            result = await lockdown.get_value(key="ActivationState")
            return str(result) if result else "Unknown"
        except (MissingValueError, LockdownError):
            return "Unknown"

    async def sync_time(self) -> str:
        lockdown = await self._get_lockdown()
        await lockdown.set_value(key="TimeIntervalSince1970", value=int(time.time()))
        return "Device time synchronized with host PC."
