# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

macOS HID device enhancement toolkit — two features in one process:
1. **BLE Remote Remapper** — single-button BLE remotes → 3 gestures (single/double/long) → configurable keyboard/mouse/shell actions, with menu bar UI for config
2. **Dell DDC Volume Control** — intercepts volume keys when Dell monitor is the audio output, controls speaker via DDC/CI + shows HUD overlay

## Running

```bash
./run.sh                    # Start (uses .venv/bin/python3 -u remote_control.py --config config.json)
python3 monitor_hid.py      # Debug: logs all raw HID events to console
```

## Service Management (LaunchAgent)

The LaunchAgent plist at `~/Library/LaunchAgents/com.david.remote-control.plist` currently points to the **wrong path** (`/Users/david/projects/remote-control/run.sh`). Update it to `/Users/david/projects/mac-hid-toolkit/run.sh` before relying on auto-start.

```bash
launchctl kickstart -k gui/$(id -u)/com.david.remote-control  # Restart after code/config change
launchctl load ~/Library/LaunchAgents/com.david.remote-control.plist
launchctl unload ~/Library/LaunchAgents/com.david.remote-control.plist
```

## Dependencies

- Python venv at `.venv/` with `pyobjc` (Quartz, AppKit, CoreFoundation, objc)
- `m1ddc` at `/opt/homebrew/bin/m1ddc` (`brew install m1ddc`) for Dell DDC
- macOS Accessibility permission for `CGEventTap`

## Architecture

**Event flow — two-layer interception:**

```
BLE Remote → IOKit HID Manager (filtered by VendorID + ProductID)
             ↓ DeviceHandler.record_event() stamps monotonic time
macOS NX_SYSDEFINED → CGEventTap:
  key_code == SOUND_UP + recent HID stamp (<100ms) → from remote
    → GestureDetector.on_press/on_release → execute_action()
    → suppress event (return None)
  no recent HID stamp → from keyboard
    → Dell connected? → DDC volume_up/down/toggle_mute + VolumeHUD
    → not Dell → passthrough
```

**Files:**
- `remote_control.py` — `RemoteController` orchestrates everything. `DeviceHandler` holds per-device state + `GestureDetector`. `DellVolumeControl` caches audio output check (5s TTL via `system_profiler SPAudioDataType`). `scan_hid_devices()` enumerates all connected HID devices via IOKit.
- `menu_bar.py` — `RemoteMenuBar(NSObject)`: NSStatusItem + NSMenu with live Dell volume via `menuNeedsUpdate_` delegate. Preferences window uses NSTabView (one tab per device). `onAddDevice_` calls `scan_hid_devices()` and shows a picker alert. Config saved via `_save_config()` which calls `on_config_changed` callback on `RemoteController`.
- `volume_hud.py` — `VolumeHUD` + `VolumeHUDView`. Thread-safe: dispatches to main thread via `CFRunLoopPerformBlock`. Auto-hides after 1.5s.
- `dell_volume.py` — Standalone (unused in production; DDC logic is integrated into `remote_control.py`).
- `monitor_hid.py` — Debug utility. Run this when adding new device support to observe raw HID events.

## Critical Implementation Notes

**IOHIDValueCallback has 4 parameters, not 3:**
```python
# Correct — matches C signature: (context, result, sender, value)
IOHIDValueCallback = ctypes.CFUNCTYPE(None, c_void_p, c_int, c_void_p, c_void_p)

def _hid_value_callback(self, context, result, sender, value):
    element = _iokit.IOHIDValueGetElement(value)  # value is IOHIDValueRef
```
Defining it with 3 params makes `value` receive the `sender` (IOHIDDeviceRef) instead — `IOHIDValueGetElement` on a device ref causes SIGSEGV on button press.

**IOHIDValueCallback must be kept alive as an instance attribute:**
```python
self._hid_callback = IOHIDValueCallback(self._hid_value_callback)
```
If stored as a local variable, CPython GCs the Python wrapper while the C pointer remains registered → SIGSEGV when the callback fires.

**`app.run()` not `CFRunLoopRun()`:**  
`CFRunLoopRun()` only processes CF sources. `app.run()` (NSApplication) is required to handle both CGEventTap/HID sources AND NSApplication events (menu clicks, window interactions, `menuNeedsUpdate_` delegate).

**Dell audio detection:**  
Parses `system_profiler SPAudioDataType` output, walking backwards from the "Default Output Device: Yes" line to look for "DELL " prefix in the device name.

## Configuration

`config.json` — multi-device format:
```json
{"devices": [{"name": "...", "vendor_id": "0x248A", "product_id": "0x8266",
  "single_click": {"type": "key", "key": "down", "modifiers": [], "description": "↓ Down"},
  "double_click": ..., "long_press": ...,
  "double_click_interval": 0.4, "long_press_threshold": 0.5}]}
```
Action types: `key` (with optional `modifiers`: shift/ctrl/alt/cmd), `mouse` (left/right), `shell` (arbitrary command), `none`.  
Old flat single-device format is auto-migrated on load.
