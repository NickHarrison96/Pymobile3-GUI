"""
Firmware key lookup and bootchain image decryption.

The SSH ramdisk build needs decrypted iBSS/iBEC images so `iBoot64Patcher` can
patch them. `sshrd.sh` obtains these with `gaster decrypt`, which drives the
device's AES engine over USB through the GID0 key. That path is unreliable on
Windows (see AGENTS.md), so keys are taken from The Apple Wiki instead and the
decryption is done locally with pyimg4 -- no device round-trip at all.

Only the bootchain components are covered. The restore ramdisk, kernelcache and
DeviceTree in an IPSW are not KBAG-wrapped, so plain `img4 -i` handles them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

API = "https://theapplewiki.com/api.php"
FIRMWARE_PAGE = "https://theapplewiki.com/wiki/Firmware/iPhone/{major}.x"
HEADERS = {"User-Agent": "Pymobile3-GUI ramdisk builder"}
TIMEOUT = 45


class FirmwareKeyError(Exception):
    """A firmware key could not be located or fetched."""


@dataclass(frozen=True)
class ComponentKey:
    """AES key material for one KBAG-wrapped firmware component."""

    component: str
    filename: str
    iv: bytes
    key: bytes


def _get_json(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise FirmwareKeyError(f"Apple Wiki request failed: {exc}") from exc
    except ValueError as exc:
        raise FirmwareKeyError("Apple Wiki returned malformed JSON") from exc


def _page_wikitext(title: str) -> str:
    data = _get_json(API, {
        "action": "parse", "page": title, "prop": "wikitext", "format": "json",
    })
    if "error" in data:
        raise FirmwareKeyError(f"Apple Wiki has no page '{title}'")
    text = data.get("parse", {}).get("wikitext", {}).get("*", "")
    if not text.strip():
        raise FirmwareKeyError(f"Apple Wiki page '{title}' is empty")
    return text


def resolve_key_page(build: str, device: str, major: int) -> str:
    """
    Find the `Keys:<codename> <build> (<device>)` page for a build.

    The firmware table is the authoritative mapping of build -> codename, and it
    carries a per-device key link, so parse it rather than guessing the codename
    or relying on search (search does not reliably surface these pages).
    """
    text = _page_wikitext(f"Firmware/iPhone/{major}.x")
    # Each row links keys per device, e.g. [[Keys:Sydney 20A392 (iPhone10,4)|iPhone10,4]]
    pattern = re.compile(r"\[\[([^\]|]+?)\|" + re.escape(device) + r"\]\]")
    for line in text.splitlines():
        for match in pattern.finditer(line):
            title = match.group(1).strip()
            if build in title:
                return title
    raise FirmwareKeyError(
        f"The Apple Wiki publishes no keys for {device} build {build} "
        f"(see https://theapplewiki.com/wiki/Firmware/iPhone/{major}.x)")


def parse_component_keys(wikitext: str) -> dict[str, ComponentKey]:
    """
    Extract `component -> ComponentKey` from a key page.

    Pages store three fields per component, e.g. `iBSS`, `iBSSIV`, `iBSSKey`.
    Keyed by filename so callers can look up by the file the IPSW actually
    shipped rather than reconstructing the name.
    """
    fields: dict[str, str] = {}
    for name, value in re.findall(r"^\s*\|\s*([A-Za-z0-9]+)\s*=\s*(\S+)\s*$",
                                  wikitext, re.MULTILINE):
        fields[name] = value

    keys: dict[str, ComponentKey] = {}
    for name in list(fields):
        if not name.endswith("Key"):
            continue
        component = name[:-3]
        filename = fields.get(component)
        iv_hex = fields.get(component + "IV")
        key_hex = fields.get(name)
        if not (filename and iv_hex and key_hex):
            continue
        try:
            iv = bytes.fromhex(iv_hex)
            key = bytes.fromhex(key_hex)
        except ValueError:
            continue
        if len(iv) != 16 or len(key) != 32:
            continue
        keys[filename] = ComponentKey(component=component, filename=filename,
                                      iv=iv, key=key)
    return keys


def fetch_component_keys(build: str, device: str, major: int) -> dict[str, ComponentKey]:
    """Resolve and parse the key page for a build."""
    page = resolve_key_page(build, device, major)
    keys = parse_component_keys(_page_wikitext(page))
    if not keys:
        raise FirmwareKeyError(
            f"Apple Wiki page '{page}' contained no usable IV/Key pairs")
    return keys


def ivkey(component_key: ComponentKey) -> str:
    """
    Render key material as the `ivkey` string the img4 tool expects (IV||Key).

    Decryption itself is done by the vendored Linux `img4 -k`, not here: that is
    the same tool the rest of the build uses, and `iBoot64Patcher` rejects a
    payload produced any other way even when the length is identical.
    """
    return (component_key.iv + component_key.key).hex()


def lookup_key(
    keys: dict[str, ComponentKey], filename: str,
) -> Optional[ComponentKey]:
    """Match a downloaded IPSW file to its key by basename."""
    import os

    return keys.get(os.path.basename(filename))