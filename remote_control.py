#!/usr/bin/env python3
"""
AB Shutter3 Remote Control Remapper
====================================
Intercepts events from the AB Shutter3 Bluetooth remote and remaps
them to custom keyboard/mouse actions. Uses IOKit HID device-level
filtering so it won't interfere with keyboard media keys.

Single button → 3 actions via gesture detection:
  - Single click  → configurable action
  - Double click  → configurable action
  - Long press    → configurable action

Usage:
  python remote_control.py                    # Run with default config
  python remote_control.py --config cfg.json  # Run with custom config

Requires: Accessibility permission in System Settings > Privacy & Security
"""

import Quartz
from Quartz import (
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    CGEventMaskBit, CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopCommonModes,
    CFRunLoopRun, CGEventCreateKeyboardEvent, CGEventPost,
    kCGHIDEventTap, CGEventSetFlags,
    kCGEventFlagMaskShift, kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand,
    kCGEventLeftMouseDown, kCGEventLeftMouseUp,
    kCGEventRightMouseDown, kCGEventRightMouseUp,
    CGEventCreateMouseEvent,
)
import ctypes
import ctypes.util
import json
import os
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
_iokit.IOHIDManagerScheduleWithRunLoop.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_iokit.IOHIDManagerOpen.restype = ctypes.c_int
_iokit.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_iokit.IOHIDManagerRegisterInputValueCallback.restype = None
_iokit.IOHIDManagerRegisterInputValueCallback.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

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
_cf.CFDictionaryCreateMutable.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
_cf.CFDictionarySetValue.restype = None
_cf.CFDictionarySetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

# CFString
_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]

kCFNumberSInt32Type = 3
kCFStringEncodingUTF8 = 0x08000100
kCFAllocatorDefault = None

# IOKit HID keys
kIOHIDVendorIDKey = b"VendorID"
kIOHIDProductIDKey = b"ProductID"

# AB Shutter3 identifiers
AB_SHUTTER_VENDOR_ID = 0x248A
AB_SHUTTER_PRODUCT_ID = 0x8266

# Consumer Control usage page
USAGE_PAGE_CONSUMER = 0x0C

# NX key codes for volume
NX_KEYTYPE_SOUND_UP = 0
NX_KEYTYPE_SOUND_DOWN = 1
NX_KEYTYPE_MUTE = 7

# Dell monitor DDC volume control
DDC_VOLUME_STEP = 5
DDC_VOLUME_MIN = 0
DDC_VOLUME_MAX = 100
DELL_DISPLAY_PREFIX = "DELL "


def _cfstr(s):
    return _cf.CFStringCreateWithCString(kCFAllocatorDefault, s, kCFStringEncodingUTF8)


def _cfnum(n):
    val = ctypes.c_int32(n)
    return _cf.CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, ctypes.byref(val))


# Callback function type for IOHIDManager
IOHIDValueCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)

# ── macOS virtual key codes ────────────────────────────────────────
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
    "return": 36, "enter": 36,
    "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
    "/": 44, "n": 45, ".": 46, "`": 47,
    "tab": 48, "space": 49, "delete": 51, "escape": 53, "esc": 53,
    "command": 55, "cmd": 55, "shift": 56, "capslock": 57,
    "option": 58, "alt": 58, "control": 59, "ctrl": 59,
    "right_shift": 60, "right_option": 61, "right_control": 62,
    "fn": 63,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 111, "f12": 103,
    "f13": 105, "f14": 107, "f15": 113,
    "home": 115, "pageup": 116, "forwarddelete": 117,
    "end": 119, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
}

DEFAULT_CONFIG = {
    "single_click": {
        "type": "key", "key": "down", "modifiers": [],
        "description": "↓ 下箭头"
    },
    "double_click": {
        "type": "key", "key": "up", "modifiers": [],
        "description": "↑ 上箭头"
    },
    "long_press": {
        "type": "key", "key": "return", "modifiers": [],
        "description": "Enter 回车"
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
                    self.double_click_interval, self._resolve_click)
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
            self.long_press_threshold, self._on_long_press)
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
    subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def execute_action(action_config):
    action_type = action_config.get("type", "key")
    desc = action_config.get("description", "")

    if action_type == "key":
        key = action_config.get("key", "space")
        mods = action_config.get("modifiers", [])
        mod_str = "+".join(mods) + "+" if mods else ""
        print(f"  → Key: {mod_str}{key} ({desc})")
        send_key(key, mods)
    elif action_type == "mouse":
        button = action_config.get("button", "left")
        print(f"  → Mouse: {button} click ({desc})")
        send_mouse_click(button)
    elif action_type == "shell":
        cmd = action_config.get("command", "")
        print(f"  → Shell: {cmd} ({desc})")
        run_shell(cmd)
    elif action_type == "none":
        print(f"  → (no action) ({desc})")


# ── Main controller ────────────────────────────────────────────────

class DellVolumeControl:
    """Controls Dell monitor volume via DDC/CI using m1ddc."""

    def __init__(self, hud):
        self._volume = None
        self._muted = False
        self._pre_mute_volume = None
        self._dell_connected = False
        self._last_check = 0
        self._check_interval = 5  # seconds between audio output checks
        self._lock = threading.Lock()
        self._hud = hud
        self._check_dell()

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
                capture_output=True, text=True, timeout=5)
            lines = result.stdout.split("\n")
            is_dell_output = False
            for i, line in enumerate(lines):
                if "Default Output Device: Yes" in line:
                    # Look backwards for device name
                    for j in range(i - 1, max(i - 10, 0), -1):
                        if DELL_DISPLAY_PREFIX in lines[j]:
                            is_dell_output = True
                            break
                    break
            self._dell_connected = is_dell_output
            if self._dell_connected and self._volume is None:
                self._read_volume()
        except Exception:
            self._dell_connected = False
        return self._dell_connected

    @property
    def is_connected(self):
        return self._check_dell()

    def _read_volume(self):
        try:
            result = subprocess.run(
                ["/opt/homebrew/bin/m1ddc", "get", "volume"],
                capture_output=True, text=True, timeout=2)
            self._volume = int(result.stdout.strip())
        except Exception:
            self._volume = 50

    def _set_volume(self, vol):
        vol = max(DDC_VOLUME_MIN, min(DDC_VOLUME_MAX, vol))
        self._volume = vol
        subprocess.Popen(
            ["/opt/homebrew/bin/m1ddc", "set", "volume", str(vol)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ts = time.strftime("%H:%M:%S")
        bar = "█" * (vol // 5) + "░" * (20 - vol // 5)
        print(f"[{ts}] Dell Volume: {bar} {vol}%")
        self._hud.show(vol, muted=self._muted)

    def volume_up(self):
        with self._lock:
            self._muted = False
            vol = self._volume if self._volume is not None else 50
            self._set_volume(vol + DDC_VOLUME_STEP)

    def volume_down(self):
        with self._lock:
            self._muted = False
            vol = self._volume if self._volume is not None else 50
            self._set_volume(vol - DDC_VOLUME_STEP)

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
    def __init__(self, config):
        self.config = config
        self.gesture = GestureDetector(config, self.on_gesture)
        self._hud = VolumeHUD()
        self.dell = DellVolumeControl(self._hud)
        # Timestamp of the last AB Shutter3 HID report, used to
        # correlate device-level events with system-level NX events.
        self._shutter_event_time = 0.0
        self._lock = threading.Lock()
        # Keep a reference so the callback isn't garbage-collected
        self._hid_callback = IOHIDValueCallback(self._hid_value_callback)

    def on_gesture(self, gesture_type):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {gesture_type.upper().replace('_', ' ')}")
        action_config = self.config.get(gesture_type, {"type": "none"})
        execute_action(action_config)

    # ── IOKit HID callback (device-level, fires BEFORE NX event) ──
    def _hid_value_callback(self, context, result, value):
        element = _iokit.IOHIDValueGetElement(value)
        usage_page = _iokit.IOHIDElementGetUsagePage(element)
        usage = _iokit.IOHIDElementGetUsage(element)
        int_value = _iokit.IOHIDValueGetIntegerValue(value)

        if usage_page == USAGE_PAGE_CONSUMER:
            with self._lock:
                self._shutter_event_time = time.monotonic()

    # ── CGEventTap callback (system-level) ────────────────────���────
    def event_callback(self, proxy, event_type, event, refcon):
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

            # ── AB Shutter3: code 0 with recent HID report ──
            if key_code == NX_KEYTYPE_SOUND_UP:
                with self._lock:
                    elapsed = time.monotonic() - self._shutter_event_time
                is_from_shutter = elapsed < 0.1

                if is_from_shutter:
                    if is_down and not is_repeat:
                        self.gesture.on_press()
                    elif key_state == 0x0B:
                        self.gesture.on_release()
                    return None  # Suppress

                # Not from shutter → Dell volume or pass through
                if self.dell.is_connected and is_down:
                    self.dell.volume_up()
                    return None
                return event

            # ── Volume Down → Dell DDC or pass through ──
            if key_code == NX_KEYTYPE_SOUND_DOWN:
                if self.dell.is_connected and is_down:
                    self.dell.volume_down()
                    return None
                return event

            # ── Mute → Dell DDC or pass through ──
            if key_code == NX_KEYTYPE_MUTE:
                if self.dell.is_connected and is_down:
                    self.dell.toggle_mute()
                    return None
                return event

        except Exception:
            pass

        return event

    def _setup_hid_manager(self):
        """Set up IOKit HID manager to monitor AB Shutter3 specifically."""
        manager = _iokit.IOHIDManagerCreate(kCFAllocatorDefault, 0)

        # Build matching dict: VendorID=0x248A, ProductID=0x8266
        match_dict = _cf.CFDictionaryCreateMutable(kCFAllocatorDefault, 2, None, None)
        _cf.CFDictionarySetValue(match_dict,
            _cfstr(kIOHIDVendorIDKey), _cfnum(AB_SHUTTER_VENDOR_ID))
        _cf.CFDictionarySetValue(match_dict,
            _cfstr(kIOHIDProductIDKey), _cfnum(AB_SHUTTER_PRODUCT_ID))

        _iokit.IOHIDManagerSetDeviceMatching(manager, match_dict)
        _iokit.IOHIDManagerRegisterInputValueCallback(
            manager, self._hid_callback, None)
        _iokit.IOHIDManagerScheduleWithRunLoop(
            manager, _cf.CFRunLoopGetCurrent(),
            _cfstr(b"kCFRunLoopDefaultMode"))

        result = _iokit.IOHIDManagerOpen(manager, 0)
        if result != 0:
            print(f"WARNING: IOHIDManagerOpen returned {result}")
            print("  HID device filtering may not work.")
            print("  Falling back to intercepting all code-0 media events.")
            # Set shutter time far in the future so all events match
            self._shutter_event_time = float('inf')
        else:
            print("  HID device filter: active (only AB Shutter3 events intercepted)")

        return manager

    def run(self):
        # Initialize NSApplication for HUD window support
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        print("=" * 60)
        print("  AB Shutter3 Remote Control Remapper")
        print("=" * 60)
        print()
        print("  Mappings:")
        for gesture in ("single_click", "double_click", "long_press"):
            cfg = self.config.get(gesture, {})
            desc = cfg.get("description", "not configured")
            label = gesture.replace("_", " ").title()
            print(f"    {label:15s} → {desc}")
        print()
        print(f"  Double-click interval: {self.config.get('double_click_interval', 0.4)}s")
        print(f"  Long-press threshold:  {self.config.get('long_press_threshold', 0.5)}s")
        print()

        # Dell monitor volume control
        if self.dell.is_connected:
            print(f"  Dell DDC volume: active (current: {self.dell._volume}%)")
            print(f"    F11/F12/Mute → Dell monitor speaker")
        else:
            print("  Dell DDC volume: not connected (volume keys normal)")
        print()

        # Set up device-level HID monitoring
        self._hid_manager = self._setup_hid_manager()

        # Set up system-level event tap
        mask = CGEventMaskBit(NX_SYSDEFINED)
        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, 0,
            mask, self.event_callback, None)

        if tap is None:
            print("ERROR: Failed to create event tap!")
            print("Please grant Accessibility permission:")
            print("  System Settings > Privacy & Security > Accessibility")
            print("  Add python3.14")
            sys.exit(1)

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)

        print()
        print("  Press Ctrl+C to stop")
        print("=" * 60)
        print()
        print("Listening for AB Shutter3 events...\n")

        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        CFRunLoopRun()


def load_config(path=None):
    if path and os.path.exists(path):
        with open(path) as f:
            user_config = json.load(f)
        config = dict(DEFAULT_CONFIG)
        config.update(user_config)
        return config
    return dict(DEFAULT_CONFIG)


def main():
    config_path = None
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("\nDefault config (save as config.json and modify):")
        print(json.dumps(DEFAULT_CONFIG, indent=2))
        sys.exit(0)

    config = load_config(config_path)
    controller = RemoteController(config)
    controller.run()


if __name__ == "__main__":
    main()
