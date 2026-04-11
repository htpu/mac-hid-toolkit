#!/usr/bin/env python3
"""
Dell Monitor Volume Control via DDC
=====================================
Intercepts macOS volume keys (F11/F12/Mute) and controls the Dell
monitor's built-in speaker volume via DDC/CI using m1ddc.

Requires: m1ddc (`brew install m1ddc`), Accessibility permission.
"""

import Quartz
from Quartz import (
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    CGEventMaskBit, CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopCommonModes,
    CFRunLoopRun,
)
import signal
import subprocess
import sys
import threading
import time

NX_SYSDEFINED = 14
VOLUME_STEP = 5
VOLUME_MIN = 0
VOLUME_MAX = 100

# NX key codes
NX_KEYTYPE_SOUND_UP = 0
NX_KEYTYPE_SOUND_DOWN = 1
NX_KEYTYPE_MUTE = 7


class DellVolumeController:
    def __init__(self):
        self._cached_volume = None
        self._muted = False
        self._pre_mute_volume = None
        self._lock = threading.Lock()
        self._read_current_volume()

    def _read_current_volume(self):
        try:
            result = subprocess.run(
                ["m1ddc", "get", "volume"],
                capture_output=True, text=True, timeout=2)
            vol = int(result.stdout.strip())
            self._cached_volume = vol
            return vol
        except Exception:
            self._cached_volume = 50
            return 50

    def _set_volume(self, vol):
        vol = max(VOLUME_MIN, min(VOLUME_MAX, vol))
        self._cached_volume = vol
        subprocess.Popen(
            ["m1ddc", "set", "volume", str(vol)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ts = time.strftime("%H:%M:%S")
        bar = "█" * (vol // 5) + "░" * (20 - vol // 5)
        print(f"[{ts}] Volume: {bar} {vol}%")

    def volume_up(self):
        with self._lock:
            if self._muted:
                self._muted = False
            vol = (self._cached_volume or 50) + VOLUME_STEP
            self._set_volume(vol)

    def volume_down(self):
        with self._lock:
            if self._muted:
                self._muted = False
            vol = (self._cached_volume or 50) - VOLUME_STEP
            self._set_volume(vol)

    def toggle_mute(self):
        with self._lock:
            if self._muted:
                self._muted = False
                vol = self._pre_mute_volume or 50
                self._set_volume(vol)
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] Unmuted")
            else:
                self._muted = True
                self._pre_mute_volume = self._cached_volume
                self._set_volume(0)
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] Muted")

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
            key_state = (data1 & 0x0000FF00) >> 8
            is_down = key_state == 0x0A

            if key_code == NX_KEYTYPE_SOUND_UP and is_down:
                self.volume_up()
                return None  # Suppress original
            elif key_code == NX_KEYTYPE_SOUND_DOWN and is_down:
                self.volume_down()
                return None
            elif key_code == NX_KEYTYPE_MUTE and is_down:
                self.toggle_mute()
                return None

        except Exception:
            pass

        return event

    def run(self):
        print("=" * 60)
        print("  Dell Monitor Volume Control (DDC)")
        print("=" * 60)
        print()
        print(f"  Display: DELL S3221QS")
        print(f"  Current volume: {self._cached_volume}%")
        print(f"  Step: {VOLUME_STEP}%")
        print(f"  Keys: F11 (down), F12 (up), Mute")
        print()
        print("  Press Ctrl+C to stop")
        print("=" * 60)
        print()

        mask = CGEventMaskBit(NX_SYSDEFINED)
        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, 0,
            mask, self.event_callback, None)

        if tap is None:
            print("ERROR: Failed to create event tap!")
            print("Grant Accessibility permission to python3.14")
            sys.exit(1)

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)

        print("Listening for volume keys...\n")
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        CFRunLoopRun()


if __name__ == "__main__":
    DellVolumeController().run()
