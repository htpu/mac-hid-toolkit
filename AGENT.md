# AGENT.md

This file provides project-specific guidance for AI agents working in this repository.

## Project Context

This is the **mac-hid-toolkit** project - a macOS HID device enhancement toolkit with two main features:
1. **BLE Remote Remapper** — Maps single-button BLE remote gestures to keyboard/mouse/shell actions
2. **Dell DDC Volume Control** — Controls Dell monitor volume via DDC/CI when volume keys are pressed

## Quick Start

```bash
# Start the application
./run.sh

# Debug HID events
python3 monitor_hid.py
```

## Key Files

| File | Purpose |
|------|---------|
| `remote_control.py` | Main application - orchestration, HID interception, DDC control |
| `menu_bar.py` | Menu bar UI for configuration |
| `volume_hud.py` | Volume HUD overlay |
| `config.json` | Device and gesture configuration |

## Common Tasks

### Adding a New BLE Remote
1. Run `python3 monitor_hid.py` to discover the device's VendorID/ProductID
2. Note the HID values produced when buttons are pressed
3. Add the device to `config.json` with gesture mappings

### Modifying Gesture Detection
- Adjust `double_click_interval` (default 0.4s) and `long_press_threshold` (default 0.5s) in config
- Or modify `GestureDetector` class in `remote_control.py`

### Debugging
- Use `monitor_hid.py` to see raw HID events
- Check logs for CGEventTap status
- Verify LaunchAgent path: `~/Library/LaunchAgents/com.david.remote-control.plist`

## Architecture Notes

- Two-layer event interception: IOKit HID Manager → CGEventTap
- IOHIDValueCallback MUST have 4 parameters and be stored as instance attribute
- Use `app.run()` not `CFRunLoopRun()` for NSApplication integration
- Dell audio detection parses `system_profiler SPAudioDataType` output

## Testing

No formal test suite. Manual testing via:
- Running `./run.sh` and verifying menu bar icon appears
- Testing gesture detection with configured remote
- Testing volume control with Dell monitor connected

## Dependencies

- Python 3 with pyobjc (Quartz, AppKit, CoreFoundation, objc)
- m1ddc for Dell DDC (`brew install m1ddc`)
- macOS Accessibility permission for CGEventTap