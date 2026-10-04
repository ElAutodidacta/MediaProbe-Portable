from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any

from .models import DeviceInfo
from .util import find_optional_tool, parse_vid_pid, run_command, safe_float, safe_int


WINDOWS_DISCOVERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$sysLetter = $env:SystemDrive.TrimEnd(':')
$sysPart = Get-Partition -DriveLetter $sysLetter
$sysDisk = if ($sysPart) { ($sysPart | Get-Disk).Number } else { -1 }
$items = @()
Get-Volume | Where-Object { $_.DriveLetter -and $_.FileSystem } | ForEach-Object {
  $v = $_
  $p = Get-Partition -DriveLetter $v.DriveLetter | Select-Object -First 1
  $d = if ($p) { $p | Get-Disk } else { $null }
  $c = if ($d) { Get-CimInstance Win32_DiskDrive -Filter ("Index=" + $d.Number) } else { $null }
  $pd = if ($d) { Get-PhysicalDisk | Where-Object { $_.DeviceId -eq [string]$d.Number } | Select-Object -First 1 } else { $null }
  $rel = if ($pd) { $pd | Get-StorageReliabilityCounter } else { $null }
  $pnp = if ($c) { [string]$c.PNPDeviceID } else { '' }
  $loc = ''
  $parent = ''
  if ($pnp) {
    $loc = [string](Get-PnpDeviceProperty -InstanceId $pnp -KeyName 'DEVPKEY_Device_LocationInfo').Data
    $parent = [string](Get-PnpDeviceProperty -InstanceId $pnp -KeyName 'DEVPKEY_Device_Parent').Data
  }
  $items += [pscustomobject]@{
    mount = ([string]$v.DriveLetter + ':\')
    label = [string]$v.FileSystemLabel
    filesystem = [string]$v.FileSystem
    total_bytes = [int64]$v.Size
    physical_bytes = if ($d) { [int64]$d.Size } else { $null }
    free_bytes = [int64]$v.SizeRemaining
    drive_type = [string]$v.DriveType
    disk_number = if ($d) { [int]$d.Number } else { $null }
    model = if ($d) { [string]$d.FriendlyName } elseif ($c) { [string]$c.Model } else { '' }
    serial = if ($d) { [string]$d.SerialNumber } elseif ($c) { [string]$c.SerialNumber } else { '' }
    bus_type = if ($d) { [string]$d.BusType } elseif ($c) { [string]$c.InterfaceType } else { 'Desconocido' }
    removable = (($v.DriveType -eq 'Removable') -or ($d -and ([string]$d.BusType -in @('USB','SD','MMC'))))
    system_disk = ($d -and ($d.Number -eq $sysDisk))
    health = if ($d) { [string]$d.HealthStatus } else { 'No disponible' }
    unique_id = if ($d) { [string]$d.UniqueId } else { '' }
    device_path = if ($d) { [string]$d.Path } elseif ($c) { [string]$c.DeviceID } else { '' }
    pnp_id = $pnp
    location = $loc
    parent = $parent
    temperature = if ($rel) { $rel.Temperature } else { $null }
    read_errors = if ($rel) { $rel.ReadErrorsTotal } else { $null }
    write_errors = if ($rel) { $rel.WriteErrorsTotal } else { $null }
  }
}
@($items) | ConvertTo-Json -Depth 5 -Compress
"""


def _powershell_json(script: str) -> Any:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    code, out, _ = run_command(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        timeout=35,
    )
    if code != 0 or not out:
        return None
    # Windows PowerShell can prefix warnings; JSON starts at the first [ or {.
    starts = [p for p in (out.find("["), out.find("{")) if p >= 0]
    if starts:
        out = out[min(starts):]
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _smart_data(device: DeviceInfo) -> None:
    smartctl = find_optional_tool("smartctl")
    if not smartctl:
        return
    target = device.device_path
    if platform.system() == "Windows" and device.disk_number is not None:
        target = rf"\\.\PhysicalDrive{device.disk_number}"
    if not target:
        return
    code, out, _ = run_command([smartctl, "-a", "-j", target], timeout=30)
    if code not in (0, 2, 4) or not out:
        return
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return
    temp = data.get("temperature", {}).get("current")
    if temp is not None:
        device.temperature_c = safe_float(temp)
    passed = data.get("smart_status", {}).get("passed")
    if passed is True:
        device.health = "SMART correcto"
    elif passed is False:
        device.health = "SMART informa fallo"
    nvme_errors = safe_int(data.get("nvme_smart_health_information_log", {}).get("media_errors"))
    if nvme_errors is not None:
        device.media_error_indicators["NVMe media_errors"] = nvme_errors
    for attribute in data.get("ata_smart_attributes", {}).get("table", []):
        name = str(attribute.get("name") or "")
        if name in ("Reallocated_Sector_Ct", "Current_Pending_Sector", "Offline_Uncorrectable"):
            count = safe_int(attribute.get("raw", {}).get("value"))
            if count is not None:
                device.media_error_indicators[name] = count
    device.raw["smartctl"] = {
        "available": True,
        "exit_code": code,
        "smart_status": passed,
        "temperature": temp,
    }


def discover_windows() -> list[DeviceInfo]:
    parsed = _powershell_json(WINDOWS_DISCOVERY)
    if not parsed:
        return _fallback_volumes_windows()
    rows = parsed if isinstance(parsed, list) else [parsed]
    devices: list[DeviceInfo] = []
    for row in rows:
        pnp_text = " ".join(str(row.get(k) or "") for k in ("pnp_id", "parent", "location"))
        vid, pid = parse_vid_pid(pnp_text)
        bus = str(row.get("bus_type") or "Desconocido")
        location = str(row.get("location") or "")
        # xHCI identifies a capable host controller, not the negotiated link.
        bus_speed = "No expuesta por Windows"
        controller = location
        if "xhci" in pnp_text.lower():
            controller = (controller + " / controlador xHCI").strip(" /")
            bus_speed = "Controlador xHCI detectado; velocidad negociada no confirmada"
        dev = DeviceInfo(
            mount=str(row.get("mount") or ""),
            label=str(row.get("label") or ""),
            filesystem=str(row.get("filesystem") or ""),
            total_bytes=int(row.get("total_bytes") or 0),
            physical_bytes=safe_int(row.get("physical_bytes")),
            free_bytes=int(row.get("free_bytes") or 0),
            disk_number=safe_int(row.get("disk_number")),
            model=str(row.get("model") or "").strip(),
            serial=str(row.get("serial") or "").strip(),
            bus_type=bus,
            bus_speed=bus_speed,
            vid=vid,
            pid=pid,
            controller=controller,
            removable=bool(row.get("removable")),
            system_disk=bool(row.get("system_disk")),
            health=str(row.get("health") or "No disponible"),
            temperature_c=safe_float(row.get("temperature")),
            read_errors=safe_int(row.get("read_errors")),
            write_errors=safe_int(row.get("write_errors")),
            device_path=str(row.get("device_path") or ""),
            unique_id=str(row.get("unique_id") or ""),
            raw={"windows": row},
        )
        if bus.upper() in ("SD", "MMC"):
            dev.register_note = "Windows no expone CID/CSD/OCR mediante esta interfaz. Pruebe Linux y un lector SD/MMC directo."
        else:
            dev.register_note = "Lector USB: normalmente encapsula la tarjeta y oculta CID/CSD/OCR."
        _smart_data(dev)
        devices.append(dev)
    return sorted(devices, key=lambda d: d.mount.lower())


def _fallback_volumes_windows() -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        mount = f"{letter}:\\"
        if not os.path.isdir(mount):
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        # Fail closed: without hardware inventory, only Windows DRIVE_REMOVABLE
        # (2) is eligible for destructive mode. USB disks reported as fixed stay
        # usable for safe tests but destructive mode remains disabled.
        try:
            drive_type = int(ctypes.windll.kernel32.GetDriveTypeW(mount))  # type: ignore[attr-defined]
        except Exception:
            drive_type = 0
        devices.append(DeviceInfo(
            mount=mount,
            total_bytes=usage.total,
            free_bytes=usage.free,
            removable=(drive_type == 2),
            system_disk=(letter.upper() == str(os.getenv("SystemDrive") or "C:").rstrip(":").upper()),
            register_note="Inventario limitado: Windows no permitió consultar el hardware. CID/CSD/OCR no disponible.",
            raw={"windows_drive_type": drive_type, "inventory_limited": True},
        ))
    return devices


def _flatten_lsblk(nodes: list[dict[str, Any]], parent: dict[str, Any] | None = None):
    for node in nodes:
        yield node, parent
        yield from _flatten_lsblk(node.get("children") or [], node)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return ""


def _linux_hardware(block_name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    code, out, _ = run_command(["udevadm", "info", "--query=property", f"/dev/{block_name}"], timeout=10)
    if code == 0:
        for line in out.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key] = value
    return result


def _linux_usb_speed(block_name: str) -> tuple[str, str, float | None, str]:
    base = Path("/sys/class/block") / block_name
    try:
        current = base.resolve()
    except OSError:
        return "No expuesta por el sistema", "", None, ""
    for parent in [current, *current.parents]:
        speed = _read_text(parent / "speed")
        version = _read_text(parent / "version")
        product = _read_text(parent / "product")
        if speed and _read_text(parent / "idVendor"):
            label = f"{speed} Mb/s negociados"
            if version:
                label += f" (USB {version})"
            return label, product, safe_float(speed), version
    return "No expuesta por el sistema", "", None, ""


def discover_linux() -> list[DeviceInfo]:
    code, out, _ = run_command(
        ["lsblk", "--json", "--bytes", "--output", "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS,MODEL,SERIAL,TRAN,RM,HOTPLUG"],
        timeout=20,
    )
    if code != 0:
        return []
    try:
        tree = json.loads(out).get("blockdevices", [])
    except json.JSONDecodeError:
        return []
    devices: list[DeviceInfo] = []
    for node, parent in _flatten_lsblk(tree):
        mounts = node.get("mountpoints") or []
        if isinstance(mounts, str):
            mounts = [mounts]
        mount = next((m for m in mounts if m and os.path.isdir(m)), None)
        if not mount:
            continue
        disk = parent if parent and parent.get("type") == "disk" else node
        block_name = str(disk.get("name") or node.get("name") or "")
        hw = _linux_hardware(block_name)
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        bus = str(disk.get("tran") or hw.get("ID_BUS") or "Desconocido")
        speed, controller, link_mbps, usb_version = _linux_usb_speed(block_name) if bus.lower() == "usb" else ("No aplica o no expuesta", "", None, "")
        sysbase = Path("/sys/class/block") / block_name / "device"
        cid = _read_text(sysbase / "cid")
        csd = _read_text(sysbase / "csd")
        ocr = _read_text(sysbase / "ocr")
        direct_mmc = block_name.startswith("mmcblk")
        note = (
            "Registros leidos desde sysfs mediante un controlador SD/MMC directo."
            if cid or csd or ocr
            else ("El kernel ve un dispositivo MMC, pero no expuso estos registros." if direct_mmc
                  else "La tarjeta esta detras de USB; el puente normalmente oculta CID/CSD/OCR.")
        )
        dev = DeviceInfo(
            mount=mount,
            label=str(node.get("label") or ""),
            filesystem=str(node.get("fstype") or ""),
            total_bytes=usage.total,
            physical_bytes=safe_int(disk.get("size")),
            free_bytes=usage.free,
            model=str(disk.get("model") or hw.get("ID_MODEL") or "").strip(),
            serial=str(disk.get("serial") or hw.get("ID_SERIAL_SHORT") or "").strip(),
            bus_type=bus,
            bus_speed=speed,
            usb_link_mbps=link_mbps,
            usb_version=usb_version,
            vid=str(hw.get("ID_VENDOR_ID") or "").upper(),
            pid=str(hw.get("ID_MODEL_ID") or "").upper(),
            controller=controller or str(hw.get("ID_USB_DRIVER") or ""),
            removable=bool(disk.get("rm") or disk.get("hotplug")),
            system_disk=(mount == "/"),
            cid=cid,
            csd=csd,
            ocr=ocr,
            register_note=note,
            device_path=str(disk.get("path") or f"/dev/{block_name}"),
            raw={"lsblk": node, "disk": disk, "udev": hw},
        )
        _smart_data(dev)
        devices.append(dev)
    return sorted(devices, key=lambda d: d.mount)


def discover_devices() -> list[DeviceInfo]:
    system = platform.system()
    if system == "Windows":
        return discover_windows()
    if system == "Linux":
        return discover_linux()
    return []
