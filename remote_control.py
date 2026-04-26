#!/usr/bin/env python3
"""
BLE Remote Control Remapper
============================
Intercepts events from configurable BLE HID devices and remaps
them to custom keyboard/mouse actions. Uses IOKit HID device-level
filtering so it won't interfere with keyboard media keys.

Supports multiple devices, each with independent gesture detection:
  - Single click  -> configurable action
  - Double click  -> configurable action
  - Long press    -> configurable action

Usage:
  python remote_control.py                    # Run with default config
  python remote_control.py --config cfg.json  # Run with custom config

Requires: Accessibility permission in System Settings > Privacy & Security
"""

import Quartz
from Quartz import (
    CGEventTapCreate,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    CGEventMaskBit,
    CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent,
    CFRunLoopAddSource,
    kCFRunLoopCommonModes,
    CGEventCreateKeyboardEvent,
    CGEventPost,
    kCGHIDEventTap,
    CGEventSetFlags,
    kCGEventFlagMaskShift,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventRightMouseDown,
    kCGEventRightMouseUp,
    CGEventCreateMouseEvent,
    CGEventTapEnable,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
)
import ctypes
import ctypes.util
import json
import os
import re
import signal
import sys
import threading
import time
import subprocess
from volume_hud import VolumeHUD

NX_SYSDEFINED = 14

# ── IOKit HID bindings via ctypes ──────────────────────────────────
_iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("IOKit"))
_cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))

# IOHIDManager
_iokit.IOHIDManagerCreate.restype = ctypes.c_void_p
_iokit.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_iokit.IOHIDManagerSetDeviceMatching.restype = None
_iokit.IOHIDManagerSetDeviceMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_iokit.IOHIDManagerScheduleWithRunLoop.restype = None
_iokit.IOHIDManagerScheduleWithRunLoop.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_iokit.IOHIDManagerOpen.restype = ctypes.c_int
_iokit.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_iokit.IOHIDManagerRegisterInputValueCallback.restype = None
_iokit.IOHIDManagerRegisterInputValueCallback.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]

# IOHIDValue
_iokit.IOHIDValueGetElement.restype = ctypes.c_void_p
_iokit.IOHIDValueGetElement.argtypes = [ctypes.c_void_p]
_iokit.IOHIDValueGetIntegerValue.restype = ctypes.c_long
_iokit.IOHIDValueGetIntegerValue.argtypes = [ctypes.c_void_p]

# IOHIDElement
_iokit.IOHIDElementGetUsagePage.restype = ctypes.c_uint32
_iokit.IOHIDElementGetUsagePage.argtypes = [ctypes.c_void_p]
_iokit.IOHIDElementGetUsage.restype = ctypes.c_uint32
_iokit.IOHIDElementGetUsage.argtypes = [ctypes.c_void_p]

# CF helpers
_cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
_cf.CFNumberCreate.restype = ctypes.c_void_p
_cf.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
_cf.CFDictionaryCreateMutable.argtypes = [
    ctypes.c_void_p,
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_cf.CFDictionarySetValue.restype = None
_cf.CFDictionarySetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

# CFString
_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFStringCreateWithCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint32,
]
_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFStringGetCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_long,
    ctypes.c_uint32,
]

# CFNumber
_cf.CFNumberGetValue.restype = ctypes.c_bool
_cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]

# CFSet
_cf.CFSetGetCount.restype = ctypes.c_long
_cf.CFSetGetCount.argtypes = [ctypes.c_void_p]
_cf.CFSetGetValues.restype = None
_cf.CFSetGetValues.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

# IOHIDDevice property
_iokit.IOHIDManagerCopyDevices.restype = ctypes.c_void_p
_iokit.IOHIDManagerCopyDevices.argtypes = [ctypes.c_void_p]
_iokit.IOHIDDeviceGetProperty.restype = ctypes.c_void_p
_iokit.IOHIDDeviceGetProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

kCFNumberSInt32Type = 3
kCFStringEncodingUTF8 = 0x08000100
kCFAllocatorDefault = None

# IOKit HID keys
kIOHIDVendorIDKey = b"VendorID"
kIOHIDProductIDKey = b"ProductID"
kIOHIDProductKey = b"Product"
kIOHIDTransportKey = b"Transport"

# Consumer Control usage page
USAGE_PAGE_CONSUMER = 0x0C

# NX key codes for volume / brightness
NX_KEYTYPE_SOUND_UP = 0
NX_KEYTYPE_SOUND_DOWN = 1
NX_KEYTYPE_BRIGHTNESS_UP = 2
NX_KEYTYPE_BRIGHTNESS_DOWN = 3
NX_KEYTYPE_MUTE = 7

# Dell monitor DDC volume / brightness control
DDC_VOLUME_STEP = 5
DDC_VOLUME_MIN = 0
DDC_VOLUME_MAX = 100
DDC_BRIGHTNESS_STEP = 10
DDC_BRIGHTNESS_MIN = 0
DDC_BRIGHTNESS_MAX = 100
DELL_DISPLAY_PREFIX = "DELL "


def _cfstr(s):
    return _cf.CFStringCreateWithCString(kCFAllocatorDefault, s, kCFStringEncodingUTF8)


def _cfnum(n):
    val = ctypes.c_int32(n)
    return _cf.CFNumberCreate(
        kCFAllocatorDefault, kCFNumberSInt32Type, ctypes.byref(val)
    )


def _cfstr_to_py(cfstr):
    """Convert a CFStringRef to a Python string, or return None."""
    if not cfstr:
        return None
    buf = ctypes.create_string_buffer(256)
    if _cf.CFStringGetCString(cfstr, buf, 256, kCFStringEncodingUTF8):
        return buf.value.decode("utf-8", errors="replace")
    return None


def _cfnum_to_py(cfnum):
    """Convert a CFNumberRef to a Python int, or return None."""
    if not cfnum:
        return None
    val = ctypes.c_int32()
    if _cf.CFNumberGetValue(cfnum, kCFNumberSInt32Type, ctypes.byref(val)):
        return val.value
    return None


def scan_hid_devices():
    """Scan connected HID devices. Returns list of {name, vendor_id, product_id, transport}."""
    manager = _iokit.IOHIDManagerCreate(kCFAllocatorDefault, 0)
    _iokit.IOHIDManagerSetDeviceMatching(manager, None)  # match all
    _iokit.IOHIDManagerScheduleWithRunLoop(
        manager, _cf.CFRunLoopGetCurrent(), _cfstr(b"kCFRunLoopDefaultMode")
    )
    _iokit.IOHIDManagerOpen(manager, 0)

    device_set = _iokit.IOHIDManagerCopyDevices(manager)
    if not device_set:
        return []

    count = _cf.CFSetGetCount(device_set)
    if count <= 0:
        return []
    arr = (ctypes.c_void_p * count)()
    _cf.CFSetGetValues(device_set, arr)

    results = []
    seen = set()
    for i in range(count):
        dev = arr[i]
        vid = _cfnum_to_py(
            _iokit.IOHIDDeviceGetProperty(dev, _cfstr(kIOHIDVendorIDKey))
        )
        pid = _cfnum_to_py(
            _iokit.IOHIDDeviceGetProperty(dev, _cfstr(kIOHIDProductIDKey))
        )
        if vid is None or pid is None:
            continue
        key = (vid, pid)
        if key in seen:
            continue
        seen.add(key)
        name = (
            _cfstr_to_py(_iokit.IOHIDDeviceGetProperty(dev, _cfstr(kIOHIDProductKey)))
            or "Unknown"
        )
        transport = (
            _cfstr_to_py(_iokit.IOHIDDeviceGetProperty(dev, _cfstr(kIOHIDTransportKey)))
            or ""
        )
        results.append(
            {
                "name": name,
                "vendor_id": f"0x{vid:04X}",
                "product_id": f"0x{pid:04X}",
                "transport": transport,
            }
        )

    results.sort(key=lambda d: (d["transport"] != "Bluetooth", d["name"]))
    return results


# Callback function type for IOHIDManager
# C signature: void (*IOHIDValueCallback)(void *context, IOReturn result, void *sender, IOHIDValueRef value)
IOHIDValueCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
)

# ── macOS virtual key codes ────────────────────────────────────────
KEYCODES = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "return": 36,
    "enter": 36,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    ".": 46,
    "`": 47,
    "tab": 48,
    "space": 49,
    "delete": 51,
    "escape": 53,
    "esc": 53,
    "command": 55,
    "cmd": 55,
    "shift": 56,
    "capslock": 57,
    "option": 58,
    "alt": 58,
    "control": 59,
    "ctrl": 59,
    "right_shift": 60,
    "right_option": 61,
    "right_control": 62,
    "fn": 63,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 111,
    "f12": 103,
    "f13": 105,
    "f14": 107,
    "f15": 113,
    "home": 115,
    "pageup": 116,
    "forwarddelete": 117,
    "end": 119,
    "pagedown": 121,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
}

DEFAULT_DEVICE = {
    "name": "AB Shutter3",
    "vendor_id": "0x248A",
    "product_id": "0x8266",
    "single_click": {
        "type": "key",
        "key": "down",
        "modifiers": [],
        "description": "\u2193 Down",
    },
    "double_click": {
        "type": "key",
        "key": "up",
        "modifiers": [],
        "description": "\u2191 Up",
    },
    "long_press": {
        "type": "key",
        "key": "return",
        "modifiers": [],
        "description": "\u21a9 Return",
    },
    "double_click_interval": 0.4,
    "long_press_threshold": 0.5,
}


class GestureDetector:
    """Detects single click, double click, and long press from a single button."""

    def __init__(self, config, action_handler):
        self.config = config
        self.action_handler = action_handler
        self.double_click_interval = config.get("double_click_interval", 0.4)
        self.long_press_threshold = config.get("long_press_threshold", 0.5)

        self._press_time = None
        self._release_time = None
        self._click_count = 0
        self._is_long_press = False
        self._timer = None
        self._long_press_timer = None
        self._lock = threading.Lock()

    def on_press(self):
        with self._lock:
            self._press_time = time.time()
            self._is_long_press = False
            self._start_long_press_timer()

    def on_release(self):
        with self._lock:
            if self._is_long_press:
                return
            self._cancel_long_press_timer()
            self._click_count += 1
            if self._click_count == 1:
                self._timer = threading.Timer(
                    self.double_click_interval, self._resolve_click
                )
                self._timer.daemon = True
                self._timer.start()
            elif self._click_count >= 2:
                if self._timer:
                    self._timer.cancel()
                self._click_count = 0
                self.action_handler("double_click")

    def _start_long_press_timer(self):
        self._cancel_long_press_timer()
        self._long_press_timer = threading.Timer(
            self.long_press_threshold, self._on_long_press
        )
        self._long_press_timer.daemon = True
        self._long_press_timer.start()

    def _cancel_long_press_timer(self):
        if self._long_press_timer:
            self._long_press_timer.cancel()

    def _on_long_press(self):
        with self._lock:
            self._is_long_press = True
            self._click_count = 0
            if self._timer:
                self._timer.cancel()
            self.action_handler("long_press")

    def _resolve_click(self):
        with self._lock:
            if self._click_count == 1:
                self._click_count = 0
                self.action_handler("single_click")
            self._click_count = 0


class DeviceHandler:
    """Per-device state: HID event tracking + gesture detection."""

    def __init__(self, device_config):
        self.name = device_config.get("name", "Unknown")
        self.vendor_id = int(str(device_config.get("vendor_id", "0")), 0)
        self.product_id = int(str(device_config.get("product_id", "0")), 0)
        self.config = device_config
        self.gesture = GestureDetector(device_config, self._on_gesture)
        self._event_time = 0.0
        self._lock = threading.Lock()
        self._hid_callback_ref = None  # prevent GC
        self._hid_manager = None

    def _on_gesture(self, gesture_type):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{self.name}] {gesture_type.upper().replace('_', ' ')}")
        action_config = self.config.get(gesture_type, {"type": "none"})
        execute_action(action_config)

    def record_event(self):
        with self._lock:
            self._event_time = time.monotonic()

    def is_recent(self, threshold=0.1):
        with self._lock:
            return time.monotonic() - self._event_time < threshold


# ── Action execution ───────────────────────────────────────────────


def send_key(key_name, modifiers=None):
    key_lower = key_name.lower()
    keycode = KEYCODES.get(key_lower)
    if keycode is None:
        print(f"  [!] Unknown key: {key_name}")
        return

    flags = 0
    if modifiers:
        for mod in modifiers:
            m = mod.lower()
            if m in ("shift",):
                flags |= kCGEventFlagMaskShift
            elif m in ("ctrl", "control"):
                flags |= kCGEventFlagMaskControl
            elif m in ("alt", "option"):
                flags |= kCGEventFlagMaskAlternate
            elif m in ("cmd", "command"):
                flags |= kCGEventFlagMaskCommand

    event_down = CGEventCreateKeyboardEvent(None, keycode, True)
    if flags:
        CGEventSetFlags(event_down, flags)
    CGEventPost(kCGHIDEventTap, event_down)

    event_up = CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        CGEventSetFlags(event_up, flags)
    CGEventPost(kCGHIDEventTap, event_up)


def send_mouse_click(button="left"):
    loc = Quartz.NSEvent.mouseLocation()
    screen_height = Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID())
    point = Quartz.CGPointMake(loc.x, screen_height - loc.y)
    if button == "left":
        down_type, up_type = kCGEventLeftMouseDown, kCGEventLeftMouseUp
    else:
        down_type, up_type = kCGEventRightMouseDown, kCGEventRightMouseUp
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, down_type, point, 0))
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, up_type, point, 0))


def run_shell(command):
    subprocess.Popen(
        command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def execute_action(action_config):
    action_type = action_config.get("type", "key")
    desc = action_config.get("description", "")

    if action_type == "key":
        key = action_config.get("key", "space")
        mods = action_config.get("modifiers", [])
        mod_str = "+".join(mods) + "+" if mods else ""
        print(f"  \u2192 Key: {mod_str}{key} ({desc})")
        send_key(key, mods)
    elif action_type == "mouse":
        button = action_config.get("button", "left")
        print(f"  \u2192 Mouse: {button} click ({desc})")
        send_mouse_click(button)
    elif action_type == "shell":
        cmd = action_config.get("command", "")
        print(f"  \u2192 Shell: {cmd} ({desc})")
        run_shell(cmd)
    elif action_type == "none":
        print(f"  \u2192 (no action) ({desc})")


# ── Main controller ────────────────────────────────────────────────


class DellVolumeControl:
    """Controls Dell monitor volume via DDC/CI using m1ddc."""

    def __init__(self, hud):
        self._volume = None
        self._muted = False
        self._pre_mute_volume = None
        self._brightness = None
        self._dell_connected = False
        self._dell_display_connected = False
        self._audio_dell_name = None  # e.g. "DELL S2721QS"
        self._target_display = None   # m1ddc display index for audio target
        self._last_check = 0
        self._last_display_check = 0
        self._check_interval = 5  # seconds between audio output checks
        self._display_check_interval = 5
        self._lock = threading.Lock()
        self._brightness_lock = threading.Lock()
        self._hud = hud
        self._check_dell()

    def _resolve_display_index(self, name):
        """Map a Dell device name (e.g. 'DELL S2721QS') to m1ddc display index."""
        if not name:
            return None
        try:
            result = subprocess.run(
                ["/opt/homebrew/bin/m1ddc", "display", "list"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in result.stdout.splitlines():
                m = re.match(r"\s*\[(\d+)\]\s+(.+?)\s+\(", line)
                if m and m.group(2).strip() == name:
                    return int(m.group(1))
        except Exception:
            pass
        return None

    def _m1ddc_target(self):
        """Return ['display', N] prefix for m1ddc commands, or [] if no target."""
        if self._target_display is not None:
            return ["display", str(self._target_display)]
        return []

    def _check_dell(self):
        """Check if Dell monitor is the current audio output (cached for 5s)."""
        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return self._dell_connected
        self._last_check = now
        try:
            # Check if current audio output is a Dell monitor
            result = subprocess.run(
                ["system_profiler", "SPAudioDataType"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = result.stdout.split("\n")
            is_dell_output = False
            dell_name = None
            for i, line in enumerate(lines):
                if "Default Output Device: Yes" in line:
                    for j in range(i - 1, max(i - 10, 0), -1):
                        s = lines[j].strip()
                        if s.startswith("DELL"):
                            is_dell_output = True
                            dell_name = s.rstrip(":").strip()
                            break
                    break
            target_changed = dell_name != self._audio_dell_name
            self._dell_connected = is_dell_output
            self._audio_dell_name = dell_name
            if is_dell_output:
                self._target_display = self._resolve_display_index(dell_name)
            else:
                self._target_display = None
            if self._dell_connected and (self._volume is None or target_changed):
                self._read_volume()
        except Exception:
            self._dell_connected = False
            self._target_display = None
        return self._dell_connected

    @property
    def is_connected(self):
        return self._check_dell()

    def _check_dell_display(self):
        """Check if a Dell display is physically connected (independent of audio output)."""
        now = time.monotonic()
        if now - self._last_display_check < self._display_check_interval:
            return self._dell_display_connected
        self._last_display_check = now
        try:
            result = subprocess.run(
                ["/opt/homebrew/bin/m1ddc", "display", "list"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self._dell_display_connected = DELL_DISPLAY_PREFIX in result.stdout
        except Exception:
            self._dell_display_connected = False
        return self._dell_display_connected

    @property
    def is_display_connected(self):
        return self._check_dell_display()

    def _read_volume(self):
        try:
            result = subprocess.run(
                ["/opt/homebrew/bin/m1ddc", *self._m1ddc_target(), "get", "volume"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self._volume = int(result.stdout.strip())
        except Exception:
            self._volume = 50

    def _set_volume(self, vol):
        vol = max(DDC_VOLUME_MIN, min(DDC_VOLUME_MAX, vol))
        self._volume = vol
        subprocess.Popen(
            ["/opt/homebrew/bin/m1ddc", *self._m1ddc_target(), "set", "volume", str(vol)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ts = time.strftime("%H:%M:%S")
        bar = "\u2588" * (vol // 5) + "\u2591" * (20 - vol // 5)
        print(f"[{ts}] Dell Volume: {bar} {vol}%")
        self._hud.show(vol, muted=self._muted, screen_name=self._audio_dell_name)

    def volume_up(self):
        with self._lock:
            was_muted = self._muted
            self._muted = False
            if was_muted and self._pre_mute_volume is not None:
                vol = self._pre_mute_volume
            else:
                vol = self._volume if self._volume is not None else 50
            self._set_volume(vol + DDC_VOLUME_STEP)

    def volume_down(self):
        with self._lock:
            was_muted = self._muted
            self._muted = False
            if was_muted and self._pre_mute_volume is not None:
                vol = self._pre_mute_volume
            else:
                vol = self._volume if self._volume is not None else 50
            self._set_volume(vol - DDC_VOLUME_STEP)

    def _read_brightness(self):
        try:
            result = subprocess.run(
                ["/opt/homebrew/bin/m1ddc", "get", "luminance"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self._brightness = int(result.stdout.strip())
        except Exception:
            self._brightness = 50

    def _set_brightness(self, level):
        level = max(DDC_BRIGHTNESS_MIN, min(DDC_BRIGHTNESS_MAX, level))
        self._brightness = level
        subprocess.Popen(
            ["/opt/homebrew/bin/m1ddc", "set", "luminance", str(level)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ts = time.strftime("%H:%M:%S")
        bar = "\u2588" * (level // 5) + "\u2591" * (20 - level // 5)
        print(f"[{ts}] Dell Brightness: {bar} {level}%")
        self._hud.show_brightness(level, screen_name=self._audio_dell_name)

    def brightness_up(self):
        with self._brightness_lock:
            if self._brightness is None:
                self._read_brightness()
            self._set_brightness((self._brightness or 50) + DDC_BRIGHTNESS_STEP)

    def brightness_down(self):
        with self._brightness_lock:
            if self._brightness is None:
                self._read_brightness()
            self._set_brightness((self._brightness or 50) - DDC_BRIGHTNESS_STEP)

    def toggle_mute(self):
        with self._lock:
            if self._muted:
                self._muted = False
                vol = self._pre_mute_volume if self._pre_mute_volume is not None else 50
                self._set_volume(vol)
            else:
                self._muted = True
                self._pre_mute_volume = self._volume
                self._set_volume(0)


class RemoteController:
    def __init__(self, config, config_path=None):
        self.config = config
        self._config_path = config_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.json"
        )
        self._device_handlers = []
        for dev_cfg in config.get("devices", []):
            self._device_handlers.append(DeviceHandler(dev_cfg))
        self._hud = VolumeHUD()
        self.dell = DellVolumeControl(self._hud)
        self._event_tap = None

    def _on_config_changed(self, new_config):
        # Migrate old single-device format from menu bar
        if "devices" not in new_config and "single_click" in new_config:
            device = dict(DEFAULT_DEVICE)
            for key in (
                "single_click",
                "double_click",
                "long_press",
                "double_click_interval",
                "long_press_threshold",
            ):
                if key in new_config:
                    device[key] = new_config[key]
            new_config = {"devices": [device]}
        self.config = new_config
        self._device_handlers = []
        for dev_cfg in new_config.get("devices", []):
            self._device_handlers.append(DeviceHandler(dev_cfg))
        ts = time.strftime("%H:%M:%S")
        print(f"\n[{ts}] Config reloaded")
        for dev in self._device_handlers:
            print(f"  [{dev.name}] {dev.vendor_id:#06x}:{dev.product_id:#06x}")
            for g in ("single_click", "double_click", "long_press"):
                cfg = dev.config.get(g, {})
                desc = cfg.get("description", "\u2013")
                label = g.replace("_", " ").title()
                print(f"    {label:15s} \u2192 {desc}")
        print()

    # ── CGEventTap callback (system-level) ─────────────────────────
    def event_callback(self, proxy, event_type, event, refcon):
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            # macOS disables the tap on sleep/wake or slow callbacks; re-enable.
            if self._event_tap is not None:
                CGEventTapEnable(self._event_tap, True)
            return event
        if event_type != NX_SYSDEFINED:
            return event

        try:
            nsEvent = Quartz.NSEvent.eventWithCGEvent_(event)
            if nsEvent is None:
                return event
            if nsEvent.subtype() != 8:
                return event

            data1 = nsEvent.data1()
            key_code = (data1 & 0xFFFF0000) >> 16
            key_flags = data1 & 0x0000FFFF
            key_state = (key_flags & 0xFF00) >> 8
            is_repeat = key_flags & 0x01
            is_down = key_state == 0x0A

            if key_code == NX_KEYTYPE_SOUND_UP:
                # Check if any registered device had a recent HID event
                active = None
                for dev in self._device_handlers:
                    if dev.is_recent():
                        active = dev
                        break

                if active:
                    if is_down and not is_repeat:
                        active.gesture.on_press()
                    elif key_state == 0x0B:
                        active.gesture.on_release()
                    return None

                # Not from any device -> Dell volume or pass through
                if self.dell.is_connected and is_down:
                    self.dell.volume_up()
                    return None
                return event

            if key_code == NX_KEYTYPE_SOUND_DOWN:
                if self.dell.is_connected and is_down:
                    self.dell.volume_down()
                    return None
                return event

            if key_code == NX_KEYTYPE_MUTE:
                if self.dell.is_connected and is_down:
                    self.dell.toggle_mute()
                    return None
                return event

            if key_code == NX_KEYTYPE_BRIGHTNESS_UP:
                if self.dell.is_display_connected and is_down:
                    self.dell.brightness_up()
                    return None
                return event

            if key_code == NX_KEYTYPE_BRIGHTNESS_DOWN:
                if self.dell.is_display_connected and is_down:
                    self.dell.brightness_down()
                    return None
                return event

        except Exception:
            pass
        return event

    def _hid_value_callback(self, context, result, sender, value):
        """Single global HID callback — records event time for ALL devices."""
        element = _iokit.IOHIDValueGetElement(value)
        usage_page = _iokit.IOHIDElementGetUsagePage(element)
        if usage_page == USAGE_PAGE_CONSUMER:
            for dev in self._device_handlers:
                dev.record_event()

    def _setup_all_hid(self):
        """Set up one IOKit HID manager matching all configured devices."""
        # Single callback kept alive as instance attribute (prevents GC)
        self._hid_callback = IOHIDValueCallback(self._hid_value_callback)

        for dev in self._device_handlers:
            manager = _iokit.IOHIDManagerCreate(kCFAllocatorDefault, 0)
            match_dict = _cf.CFDictionaryCreateMutable(
                kCFAllocatorDefault, 2, None, None
            )
            _cf.CFDictionarySetValue(
                match_dict, _cfstr(kIOHIDVendorIDKey), _cfnum(dev.vendor_id)
            )
            _cf.CFDictionarySetValue(
                match_dict, _cfstr(kIOHIDProductIDKey), _cfnum(dev.product_id)
            )
            _iokit.IOHIDManagerSetDeviceMatching(manager, match_dict)
            _iokit.IOHIDManagerRegisterInputValueCallback(
                manager, self._hid_callback, None
            )
            _iokit.IOHIDManagerScheduleWithRunLoop(
                manager, _cf.CFRunLoopGetCurrent(), _cfstr(b"kCFRunLoopDefaultMode")
            )

            result = _iokit.IOHIDManagerOpen(manager, 0)
            if result != 0:
                print(f"  WARNING: HID for {dev.name} failed (code {result})")
            else:
                print(
                    f"  HID filter: {dev.name} "
                    f"({dev.vendor_id:#06x}:{dev.product_id:#06x})"
                )
            dev._hid_manager = manager

    @staticmethod
    def _create_app_icon():
        """Load app icon from PNG, or return None."""
        from AppKit import NSImage

        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "app_icon.png"
        )
        if os.path.exists(icon_path):
            return NSImage.alloc().initWithContentsOfFile_(icon_path)
        return None

    def run(self):
        # Initialize NSApplication
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._app_icon = self._create_app_icon()
        if self._app_icon:
            app.setApplicationIconImage_(self._app_icon)

        print("=" * 60)
        print("  BLE Remote Control Remapper")
        print("=" * 60)
        print()

        for dev in self._device_handlers:
            print(f"  [{dev.name}] {dev.vendor_id:#06x}:{dev.product_id:#06x}")
            for g in ("single_click", "double_click", "long_press"):
                cfg = dev.config.get(g, {})
                desc = cfg.get("description", "\u2013")
                label = g.replace("_", " ").title()
                print(f"    {label:15s} \u2192 {desc}")
            dci = dev.config.get("double_click_interval", 0.4)
            lpt = dev.config.get("long_press_threshold", 0.5)
            print(f"    Timing: double-click {dci}s, long-press {lpt}s")
            print()

        # Dell monitor volume control
        if self.dell.is_connected:
            print(f"  Dell DDC volume: active (current: {self.dell._volume}%)")
            print(f"    F11/F12/Mute \u2192 Dell monitor speaker")
        else:
            print("  Dell DDC volume: not connected (volume keys normal)")
        print()

        # Menu bar
        from menu_bar import RemoteMenuBar

        self._menu_bar = RemoteMenuBar.alloc().init()
        self._menu_bar.setup(
            self.config,
            self._config_path,
            self.dell,
            self._on_config_changed,
            app_icon=self._app_icon,
        )
        print("  Menu bar: active (click icon for preferences)")
        print()

        # Set up device-level HID monitoring
        self._setup_all_hid()

        # Set up system-level event tap
        mask = CGEventMaskBit(NX_SYSDEFINED)
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            0,
            mask,
            self.event_callback,
            None,
        )

        if tap is None:
            print("ERROR: Failed to create event tap!")
            print("Please grant Accessibility permission:")
            print("  System Settings > Privacy & Security > Accessibility")
            print("  Add python3.14")
            sys.exit(1)

        self._event_tap = tap
        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)

        device_names = ", ".join(d.name for d in self._device_handlers)
        print()
        print("  Press Ctrl+C to stop")
        print("=" * 60)
        print()
        print(
            f"Listening for events from {len(self._device_handlers)} device(s): {device_names}\n"
        )

        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

        # app.run() processes both CGEventTap/HID sources AND
        # NSApplication events (menu bar clicks, window interactions).
        # CFRunLoopRun() / NSRunLoop only handle CF sources.
        app.run()


def load_config(path=None):
    if path and os.path.exists(path):
        with open(path) as f:
            user_config = json.load(f)
        # Migrate old single-device format
        if "devices" not in user_config and "single_click" in user_config:
            device = dict(DEFAULT_DEVICE)
            for key in (
                "single_click",
                "double_click",
                "long_press",
                "double_click_interval",
                "long_press_threshold",
            ):
                if key in user_config:
                    device[key] = user_config[key]
            return {"devices": [device]}
        return user_config
    return {"devices": [dict(DEFAULT_DEVICE)]}


def main():
    config_path = None
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("\nDefault device config (save as config.json and modify):")
        print(json.dumps({"devices": [DEFAULT_DEVICE]}, indent=2))
        sys.exit(0)

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.json"
        )
    config = load_config(config_path)
    controller = RemoteController(config, config_path)
    controller.run()


if __name__ == "__main__":
    main()
