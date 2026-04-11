#!/usr/bin/env python3
"""Monitor all HID input events (keyboard, consumer control, etc.)
Requires Accessibility permission in System Settings > Privacy & Security > Accessibility.
"""

import Quartz
from Quartz import (
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged,
    CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
    CGEventMaskBit, CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopCommonModes,
    CFRunLoopRun, CGEventGetFlags,
    kCGEventOtherMouseDown, kCGEventOtherMouseUp,
    kCGEventLeftMouseDown, kCGEventLeftMouseUp,
    kCGEventRightMouseDown, kCGEventRightMouseUp,
    kCGEventScrollWheel,
)
import datetime
import signal
import sys
import objc

# Also monitor system-defined events (NX_SYSDEFINED) for media keys
NX_SYSDEFINED = 14

# Key code to name mapping (common keys)
KEY_NAMES = {
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
    8: "c", 9: "v", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
    16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6",
    23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0",
    30: "]", 31: "o", 32: "u", 33: "[", 34: "i", 35: "p", 36: "Return",
    37: "l", 38: "j", 39: "'", 40: "k", 41: ";", 42: "\\", 43: ",",
    44: "/", 45: "n", 46: ".", 47: "`", 48: "Tab", 49: "Space",
    51: "Delete", 53: "Escape", 55: "Cmd", 56: "Shift", 57: "CapsLock",
    58: "Option", 59: "Control", 60: "RightShift", 61: "RightOption",
    62: "RightControl", 63: "Fn",
    # Function keys
    96: "F5", 97: "F6", 98: "F7", 99: "F3", 100: "F8",
    101: "F9", 103: "F11", 105: "F13", 107: "F14", 109: "F10",
    111: "F12", 113: "F15", 115: "Home", 116: "PageUp", 117: "ForwardDelete",
    118: "F4", 119: "End", 120: "F2", 121: "PageDown", 122: "F1",
    123: "Left", 124: "Right", 125: "Down", 126: "Up",
    # Volume / media
    72: "VolumeUp (F12)", 73: "VolumeDown (F11)", 74: "Mute (F10)",
    # Brightness
    144: "BrightnessUp", 145: "BrightnessDown",
    160: "ExposeAll", 130: "DashboardKey",
    # More
    131: "LaunchpadKey",
}

# Media key names for NX_SYSDEFINED events
MEDIA_KEY_NAMES = {
    0: "BrightnessUp",
    1: "BrightnessDown",
    3: "VolumeUp",  # This is common for TELESIN shutter
    2: "VolumeDown",
    7: "PreviousTrack",
    8: "PlayPause",
    9: "NextTrack",
    10: "Mute",
    16: "Play",
    17: "FastForward",
    18: "Rewind",
    19: "NextTrack2",
    20: "PreviousTrack2",
}


def event_callback(proxy, event_type, event, refcon):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

    if event_type in (kCGEventKeyDown, kCGEventKeyUp):
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        action = "DOWN" if event_type == kCGEventKeyDown else "UP  "
        name = KEY_NAMES.get(keycode, f"Unknown({keycode})")
        flag_parts = []
        if flags & 0x10000: flag_parts.append("Shift")
        if flags & 0x40000: flag_parts.append("Option")
        if flags & 0x100000: flag_parts.append("Cmd")
        if flags & 0x80000: flag_parts.append("Ctrl")
        if flags & 0x800000: flag_parts.append("Fn")
        flag_str = "+".join(flag_parts) if flag_parts else ""
        print(f"[{ts}] KEY {action} | code={keycode:3d} | name={name:20s} | flags={flag_str}")

    elif event_type == kCGEventFlagsChanged:
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        name = KEY_NAMES.get(keycode, f"Unknown({keycode})")
        print(f"[{ts}] FLAGS     | code={keycode:3d} | name={name:20s} | flags=0x{flags:08x}")

    elif event_type == NX_SYSDEFINED:
        # Media key events come as NX_SYSDEFINED
        try:
            nsEvent = Quartz.NSEvent.eventWithCGEvent_(event)
            if nsEvent is not None:
                subtype = nsEvent.subtype()
                if subtype == 8:  # NX_SUBTYPE_AUX_CONTROL_BUTTONS
                    data1 = nsEvent.data1()
                    key_code = (data1 & 0xFFFF0000) >> 16
                    key_flags = (data1 & 0x0000FFFF)
                    key_state = (key_flags & 0xFF00) >> 8
                    state_str = "DOWN" if key_state == 0x0A else "UP  " if key_state == 0x0B else f"0x{key_state:02x}"
                    name = MEDIA_KEY_NAMES.get(key_code, f"MediaKey({key_code})")
                    print(f"[{ts}] MEDIA     | code={key_code:3d} | name={name:20s} | state={state_str} | raw=0x{data1:08x}")
                else:
                    print(f"[{ts}] SYSDEF    | subtype={subtype} | data1=0x{nsEvent.data1():08x} | data2=0x{nsEvent.data2():08x}")
        except Exception as e:
            print(f"[{ts}] SYSDEF    | (parse error: {e})")

    elif event_type in (kCGEventScrollWheel,):
        print(f"[{ts}] SCROLL    | event")

    else:
        print(f"[{ts}] OTHER     | type={event_type}")

    return event


def main():
    print("=" * 70)
    print(" HID Event Monitor - Press buttons on your remote")
    print(" Press Ctrl+C to stop")
    print("=" * 70)
    print()

    # Monitor all event types
    mask = (
        CGEventMaskBit(kCGEventKeyDown) |
        CGEventMaskBit(kCGEventKeyUp) |
        CGEventMaskBit(kCGEventFlagsChanged) |
        CGEventMaskBit(NX_SYSDEFINED) |
        CGEventMaskBit(kCGEventScrollWheel) |
        CGEventMaskBit(kCGEventOtherMouseDown) |
        CGEventMaskBit(kCGEventOtherMouseUp)
    )

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        0,  # active tap (can also modify events)
        mask,
        event_callback,
        None,
    )

    if tap is None:
        print("ERROR: Failed to create event tap!")
        print("Please grant Accessibility permission:")
        print("  System Settings > Privacy & Security > Accessibility")
        print("  Add your terminal app (Terminal.app / iTerm / etc.)")
        sys.exit(1)

    print("Event tap created successfully. Listening for events...\n")

    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    CFRunLoopRun()


if __name__ == "__main__":
    main()
