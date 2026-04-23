# AGENT.md

This file provides project-specific guidance for AI agents working in this repository.

## Project Context

This is the **mac-hid-toolkit** project - a small macOS Python toolkit with two main features:
1. **BLE Remote Remapper** — Maps single-button BLE remote gestures to keyboard/mouse/shell actions
2. **Dell DDC Volume/Brightness Control** — Controls Dell monitor volume/brightness via DDC/CI (m1ddc)

## Project Structure & Key Files
This repository uses flat top-level modules rather than a `src/` package layout.

| File | Purpose |
|------|---------|
| `remote_control.py` | Main app entry point; wires HID interception, gestures, DDC control, and menu bar |
| `menu_bar.py` | Native AppKit status item and preferences window |
| `volume_hud.py` | Floating HUD overlay for volume and brightness feedback |
| `monitor_hid.py` | Debugging tool for raw HID and `NX_SYSDEFINED` events |
| `dell_volume.py` | Older standalone Dell volume controller kept for reference |
| `config.json` | Runtime device and gesture mapping |
| `run.sh` | Launches the app with `.venv/bin/python3` |

## Quick Start & Development Commands

- `python3 -m venv .venv`: Create the local virtual environment
- `.venv/bin/pip install pyobjc`: Install Python dependency for Quartz/AppKit bindings
- `brew install m1ddc`: Install the DDC utility required for Dell display control
- `./run.sh`: Start the full application locally
- `python3 monitor_hid.py`: Inspect raw HID events for debugging or adding remotes
- `python3 remote_control.py --help`: Print usage and default config structure

## Architecture Notes

- Two-layer event interception: IOKit HID Manager → CGEventTap
- IOHIDValueCallback MUST have 4 parameters and be stored as an instance attribute to prevent SIGSEGV
- Use `app.run()` not `CFRunLoopRun()` for NSApplication integration
- Dell audio detection parses `system_profiler SPAudioDataType` output

## Common Tasks

### Adding a New BLE Remote
1. Run `python3 monitor_hid.py` to discover the device's VendorID/ProductID
2. Note the HID values produced when buttons are pressed
3. Add the device to `config.json` with gesture mappings

### Modifying Gesture Detection
- Adjust `double_click_interval` (default 0.4s) and `long_press_threshold` (default 0.5s) in config
- Or modify `GestureDetector` class in `remote_control.py`

## Coding Style & Naming Conventions
Follow existing Python style in this repo:
- Use 4-space indentation and `snake_case` for functions, methods, variables, and module names.
- Use `UPPER_SNAKE_CASE` for constants such as HID usage codes and key mappings.
- Keep modules self-contained and avoid introducing package complexity unless necessary.
- Prefer short docstrings and targeted inline comments only where macOS or ctypes behavior is non-obvious.

No formatter or linter is currently configured, so match the surrounding style before changing a file.

## Testing Guidelines
No formal automated test suite. Validate changes manually on macOS:
- Start the app with `./run.sh` and confirm the menu bar icon appears
- Verify configured gestures against the target BLE device
- Test Dell volume/brightness behavior only when a Dell display is connected and selected as output where relevant.

If you add tests, keep them lightweight and place them in a new `tests/` directory with `test_*.py` naming.

## Commit & Pull Request Guidelines
- Write concise, imperative commit messages focused on one change (e.g., `Add multi-device support`).
- In pull requests, describe the user-visible behavior change, affected hardware assumptions, and manual test steps.
- Include screenshots only for UI/HUD or menu bar changes.

## Security & Configuration Tips
Do not commit personal LaunchAgent files, local logs, or machine-specific device mappings unless they are intended defaults. Changes involving `config.json`, Accessibility permissions, or `m1ddc` assumptions should be called out explicitly in reviews.