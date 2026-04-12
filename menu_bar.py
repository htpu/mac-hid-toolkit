"""
Menu bar icon and preferences window for BLE remote control.

Provides:
- NSStatusItem in the macOS menu bar with current config status
- Native preferences window with tabs for multiple device configs
- Live config reload without restarting the daemon
"""

import json
import objc
from Foundation import NSObject
from AppKit import (
    NSApplication,
    NSStatusBar,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSWindow,
    NSView,
    NSTextField,
    NSButton,
    NSPopUpButton,
    NSComboBox,
    NSBox,
    NSFont,
    NSColor,
    NSScreen,
    NSTabView,
    NSTabViewItem,
    NSAlert,
    NSAlertFirstButtonReturn,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSControlStateValueOn,
    NSControlStateValueOff,
    NSButtonTypeSwitch,
    NSVariableStatusItemLength,
)


GESTURE_ORDER = ["single_click", "double_click", "long_press"]
GESTURE_LABELS = {
    "single_click": "Single Click",
    "double_click": "Double Click",
    "long_press": "Long Press",
}

ACTION_TYPES = ["key", "mouse", "shell", "none"]
ACTION_LABELS = {
    "key": "Keyboard Key",
    "mouse": "Mouse Click",
    "shell": "Shell Command",
    "none": "No Action",
}
ACTION_TYPE_FROM_LABEL = {v: k for k, v in ACTION_LABELS.items()}

COMMON_KEYS = [
    "up", "down", "left", "right",
    "return", "space", "tab", "escape", "delete", "forwarddelete",
    *list("abcdefghijklmnopqrstuvwxyz"),
    *list("0123456789"),
    *[f"f{i}" for i in range(1, 13)],
    "home", "end", "pageup", "pagedown",
    "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/", "`",
]

MODIFIER_NAMES = {
    "cmd": ("Cmd", ["cmd", "command"]),
    "shift": ("Shift", ["shift"]),
    "alt": ("Option", ["alt", "option"]),
    "ctrl": ("Ctrl", ["ctrl", "control"]),
}

KEY_DISPLAY = {
    "up": "\u2191 Up", "down": "\u2193 Down",
    "left": "\u2190 Left", "right": "\u2192 Right",
    "return": "\u21a9 Return", "space": "Space", "tab": "\u21e5 Tab",
    "escape": "Esc", "delete": "\u232b Delete",
    "forwarddelete": "\u2326 Fwd Delete",
    "home": "Home", "end": "End",
    "pageup": "Page Up", "pagedown": "Page Down",
}

NEW_DEVICE_TEMPLATE = {
    "name": "New Device",
    "vendor_id": "0x0000",
    "product_id": "0x0000",
    "single_click": {"type": "key", "key": "space", "modifiers": []},
    "double_click": {"type": "none"},
    "long_press": {"type": "none"},
    "double_click_interval": 0.4,
    "long_press_threshold": 0.5,
}


def auto_description(action_type, key=None, modifiers=None,
                     button=None, command=None):
    """Generate a human-readable description from action config."""
    if action_type == "key" and key:
        display = KEY_DISPLAY.get(
            key, key.upper() if len(key) == 1 else key.capitalize())
        if modifiers:
            mod_str = "+".join(m.capitalize() for m in modifiers) + "+"
            return f"{mod_str}{display}"
        return display
    elif action_type == "mouse":
        return f"Mouse {'Left' if button == 'left' else 'Right'} Click"
    elif action_type == "shell" and command:
        return command if len(command) <= 40 else command[:37] + "..."
    return "No Action"


class RemoteMenuBar(NSObject):
    """Menu bar status item with multi-device preferences."""

    def init(self):
        self = objc.super(RemoteMenuBar, self).init()
        if self is None:
            return None
        self._status_item = None
        self._config = {}
        self._config_path = ""
        self._dell = None
        self._reload_cb = None
        self._pref_window = None
        # Per-device tab controls: list of dicts
        self._tab_ctrls = []
        self._tab_view = None
        return self

    @objc.python_method
    def setup(self, config, config_path, dell_control, reload_callback,
              app_icon=None):
        self._config = dict(config)
        self._config_path = config_path
        self._dell = dell_control
        self._reload_cb = reload_callback
        self._app_icon = app_icon
        self._create_status_item()

    @objc.python_method
    def update_config(self, config):
        self._config = dict(config)

    # ── Status item ──────────────────────────────────────────────

    @objc.python_method
    def _create_status_item(self):
        sb = NSStatusBar.systemStatusBar()
        self._status_item = sb.statusItemWithLength_(
            NSVariableStatusItemLength)
        btn = self._status_item.button()
        try:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "antenna.radiowaves.left.and.right", "Remote Control")
            img.setTemplate_(True)
            btn.setImage_(img)
        except Exception:
            btn.setTitle_("RC")
        btn.setToolTip_("BLE Remote Control")
        self._menu = NSMenu.alloc().init()
        self._menu.setDelegate_(self)
        self._rebuild_menu()
        self._status_item.setMenu_(self._menu)

    def menuNeedsUpdate_(self, menu):
        self._rebuild_menu()

    @objc.python_method
    def _rebuild_menu(self):
        self._menu.removeAllItems()

        devices = self._config.get("devices", [])
        for dev in devices:
            name = dev.get("name", "Device")
            vid = dev.get("vendor_id", "?")
            pid = dev.get("product_id", "?")
            hdr = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"{name}  ({vid}:{pid})", None, "")
            hdr.setEnabled_(False)
            self._menu.addItem_(hdr)
            for g in GESTURE_ORDER:
                cfg = dev.get(g, {})
                desc = cfg.get("description", "\u2013")
                label = GESTURE_LABELS[g]
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"  {label}  \u2192  {desc}", None, "")
                item.setEnabled_(False)
                self._menu.addItem_(item)
            self._menu.addItem_(NSMenuItem.separatorItem())

        if self._dell:
            if self._dell._dell_connected:
                vol = self._dell._volume or 0
                st = "Muted" if self._dell._muted else f"{vol}%"
                txt = f"Dell Volume: {st}"
            else:
                txt = "Dell: not connected"
            di = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                txt, None, "")
            di.setEnabled_(False)
            self._menu.addItem_(di)
            self._menu.addItem_(NSMenuItem.separatorItem())

        pi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Preferences\u2026", None, "")
        pi.setTarget_(self)
        pi.setAction_(self.openPreferences_)
        self._menu.addItem_(pi)

        self._menu.addItem_(NSMenuItem.separatorItem())

        qi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", None, "")
        qi.setTarget_(self)
        qi.setAction_(self.quitApp_)
        self._menu.addItem_(qi)

    # ── Menu actions ─────────────────────────────────────────────

    def openPreferences_(self, sender):
        if self._pref_window and self._pref_window.isVisible():
            self._pref_window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            return
        self._build_pref_window()
        self._pref_window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def quitApp_(self, sender):
        import sys
        sys.exit(0)

    # ── Helpers ──────────────────────────────────────────────────

    @objc.python_method
    def _label(self, text, frame, size=13, bold=False):
        tf = NSTextField.alloc().initWithFrame_(frame)
        tf.setStringValue_(text)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        tf.setFont_(
            NSFont.boldSystemFontOfSize_(size) if bold
            else NSFont.systemFontOfSize_(size))
        return tf

    @objc.python_method
    def _text_field(self, frame, value="", placeholder=""):
        tf = NSTextField.alloc().initWithFrame_(frame)
        tf.setStringValue_(value)
        if placeholder:
            tf.setPlaceholderString_(placeholder)
        return tf

    # ── Preferences window ───────────────────────────────────────

    @objc.python_method
    def _build_pref_window(self):
        W, H = 520, 530
        screen = NSScreen.mainScreen()
        if screen:
            sf = screen.frame()
            x = (sf.size.width - W) / 2
            y = (sf.size.height - H) / 2
        else:
            x, y = 200, 200

        self._pref_window = NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(
                ((x, y), (W, H)),
                NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
                NSBackingStoreBuffered, False)
        self._pref_window.setTitle_("Remote Control Preferences")
        self._pref_window.setReleasedWhenClosed_(False)
        cv = self._pref_window.contentView()

        # ── Buttons (bottom) ──
        save = NSButton.alloc().initWithFrame_(((W - 115, 12), (100, 32)))
        save.setTitle_("Save")
        save.setBezelStyle_(NSBezelStyleRounded)
        save.setTarget_(self)
        save.setAction_(self.onSave_)
        save.setKeyEquivalent_("\r")
        cv.addSubview_(save)

        cancel = NSButton.alloc().initWithFrame_(((W - 225, 12), (100, 32)))
        cancel.setTitle_("Cancel")
        cancel.setBezelStyle_(NSBezelStyleRounded)
        cancel.setTarget_(self)
        cancel.setAction_(self.onCancel_)
        cancel.setKeyEquivalent_("\x1b")
        cv.addSubview_(cancel)

        # ── Add / Remove device buttons ──
        add_btn = NSButton.alloc().initWithFrame_(((15, 15), (100, 28)))
        add_btn.setTitle_("+ Device")
        add_btn.setBezelStyle_(NSBezelStyleRounded)
        add_btn.setTarget_(self)
        add_btn.setAction_(self.onAddDevice_)
        cv.addSubview_(add_btn)

        rm_btn = NSButton.alloc().initWithFrame_(((120, 15), (100, 28)))
        rm_btn.setTitle_("\u2212 Device")
        rm_btn.setBezelStyle_(NSBezelStyleRounded)
        rm_btn.setTarget_(self)
        rm_btn.setAction_(self.onRemoveDevice_)
        cv.addSubview_(rm_btn)

        # ── Tab view (fills most of window) ──
        self._tab_view = NSTabView.alloc().initWithFrame_(
            ((10, 50), (W - 20, H - 60)))
        cv.addSubview_(self._tab_view)

        # Build one tab per device
        self._tab_ctrls = []
        devices = self._config.get("devices", [])
        for dev_cfg in devices:
            self._add_device_tab(dev_cfg)

    @objc.python_method
    def _add_device_tab(self, dev_cfg):
        """Add a tab for one device config."""
        name = dev_cfg.get("name", "Device")
        tab_item = NSTabViewItem.alloc().initWithIdentifier_(
            f"dev_{len(self._tab_ctrls)}")
        tab_item.setLabel_(name)

        # Tab content view
        tv = NSView.alloc().initWithFrame_(((0, 0), (480, 440)))
        ctrls = {}

        # ── Device info (top of tab) ──
        info_box = NSBox.alloc().initWithFrame_(((5, 365), (470, 70)))
        info_box.setTitle_("Device")
        info_box.setTitleFont_(NSFont.boldSystemFontOfSize_(12))
        tv.addSubview_(info_box)
        ic = info_box.contentView()

        ic.addSubview_(self._label("Name:", ((0, 15), (45, 20))))
        name_f = self._text_field(((45, 13), (150, 22)), name)
        ic.addSubview_(name_f)
        ctrls["name_field"] = name_f

        ic.addSubview_(self._label("Vendor:", ((210, 15), (50, 20))))
        vendor_f = self._label(
            dev_cfg.get("vendor_id", "0x0000"), ((262, 15), (80, 20)))
        ic.addSubview_(vendor_f)
        ctrls["vendor_id"] = dev_cfg.get("vendor_id", "0x0000")

        ic.addSubview_(self._label("Product:", ((350, 15), (55, 20))))
        product_f = self._label(
            dev_cfg.get("product_id", "0x0000"), ((407, 15), (80, 20)))
        ic.addSubview_(product_f)
        ctrls["product_id"] = dev_cfg.get("product_id", "0x0000")

        # ── Gesture sections ──
        ctrls["gestures"] = {}
        base_y = 270
        for i, gesture in enumerate(reversed(GESTURE_ORDER)):
            tag = len(self._tab_ctrls) * 10 + GESTURE_ORDER.index(gesture)
            gc = self._build_gesture_controls(
                tv, gesture, tag, dev_cfg, 5, base_y - i * 95, 470)
            ctrls["gestures"][gesture] = gc

        # ── Timing ──
        tbox = NSBox.alloc().initWithFrame_(((5, 0), (470, 60)))
        tbox.setTitle_("Timing")
        tbox.setTitleFont_(NSFont.boldSystemFontOfSize_(12))
        tv.addSubview_(tbox)
        tc = tbox.contentView()

        tc.addSubview_(self._label(
            "Double-click interval:", ((0, 8), (150, 20))))
        dci = self._text_field(
            ((152, 6), (50, 22)),
            str(dev_cfg.get("double_click_interval", 0.4)))
        tc.addSubview_(dci)
        tc.addSubview_(self._label("s", ((205, 8), (15, 20))))
        ctrls["timing_dci"] = dci

        tc.addSubview_(self._label(
            "Long-press threshold:", ((230, 8), (150, 20))))
        lpt = self._text_field(
            ((382, 6), (50, 22)),
            str(dev_cfg.get("long_press_threshold", 0.5)))
        tc.addSubview_(lpt)
        tc.addSubview_(self._label("s", ((435, 8), (15, 20))))
        ctrls["timing_lpt"] = lpt

        tab_item.setView_(tv)
        self._tab_view.addTabViewItem_(tab_item)
        self._tab_ctrls.append(ctrls)

    @objc.python_method
    def _build_gesture_controls(self, parent, gesture, tag, dev_cfg, x, y, w):
        """Build controls for one gesture, return controls dict."""
        cfg = dev_cfg.get(gesture, {})
        atype = cfg.get("type", "key")

        box = NSBox.alloc().initWithFrame_(((x, y), (w, 88)))
        box.setTitle_(GESTURE_LABELS[gesture])
        box.setTitleFont_(NSFont.boldSystemFontOfSize_(12))
        parent.addSubview_(box)
        cv = box.contentView()
        cw = w - 10
        ctrls = {}

        # Row 1: Action type
        cv.addSubview_(self._label("Action:", ((0, 38), (55, 20))))
        tp = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            ((58, 36), (150, 24)), False)
        for at in ACTION_TYPES:
            tp.addItemWithTitle_(ACTION_LABELS[at])
        tp.selectItemWithTitle_(ACTION_LABELS.get(atype, "Keyboard Key"))
        tp.setTag_(tag)
        tp.setTarget_(self)
        tp.setAction_(self.onTypeChanged_)
        cv.addSubview_(tp)
        ctrls["type_popup"] = tp

        # Row 2a: Key controls
        kv = NSView.alloc().initWithFrame_(((0, 5), (cw, 28)))
        kv.addSubview_(self._label("Key:", ((0, 4), (30, 20))))
        kc = NSComboBox.alloc().initWithFrame_(((32, 2), (100, 24)))
        kc.addItemsWithObjectValues_(COMMON_KEYS)
        kc.setStringValue_(cfg.get("key", "space"))
        kc.setCompletes_(True)
        kc.setNumberOfVisibleItems_(12)
        kv.addSubview_(kc)
        ctrls["key_combo"] = kc

        mods = [m.lower() for m in cfg.get("modifiers", [])]
        mod_cbs = {}
        mx = 140
        for mname, (display, aliases) in MODIFIER_NAMES.items():
            checked = any(a in mods for a in aliases)
            cb = NSButton.alloc().initWithFrame_(((mx, 4), (70, 20)))
            cb.setButtonType_(NSButtonTypeSwitch)
            cb.setTitle_(display)
            cb.setState_(
                NSControlStateValueOn if checked
                else NSControlStateValueOff)
            cb.setFont_(NSFont.systemFontOfSize_(11))
            kv.addSubview_(cb)
            mod_cbs[mname] = cb
            mx += 70
        ctrls["mod_cbs"] = mod_cbs
        cv.addSubview_(kv)
        ctrls["key_view"] = kv

        # Row 2b: Mouse controls
        mv = NSView.alloc().initWithFrame_(((0, 5), (cw, 28)))
        mv.addSubview_(self._label("Button:", ((0, 4), (50, 20))))
        mp = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            ((52, 2), (90, 24)), False)
        mp.addItemWithTitle_("left")
        mp.addItemWithTitle_("right")
        if cfg.get("button"):
            mp.selectItemWithTitle_(cfg["button"])
        mv.addSubview_(mp)
        cv.addSubview_(mv)
        ctrls["mouse_popup"] = mp
        ctrls["mouse_view"] = mv

        # Row 2c: Shell controls
        sv = NSView.alloc().initWithFrame_(((0, 5), (cw, 28)))
        sv.addSubview_(self._label("Cmd:", ((0, 4), (35, 20))))
        sf = NSTextField.alloc().initWithFrame_(((37, 2), (cw - 45, 22)))
        sf.setStringValue_(cfg.get("command", ""))
        sv.addSubview_(sf)
        cv.addSubview_(sv)
        ctrls["shell_field"] = sf
        ctrls["shell_view"] = sv

        # Set initial visibility
        self._set_gesture_visibility(ctrls, atype)
        return ctrls

    @objc.python_method
    def _set_gesture_visibility(self, ctrls, atype):
        ctrls["key_view"].setHidden_(atype != "key")
        ctrls["mouse_view"].setHidden_(atype != "mouse")
        ctrls["shell_view"].setHidden_(atype != "shell")

    # ── Preference callbacks ─────────────────────────────────────

    def onTypeChanged_(self, sender):
        tag = sender.tag()
        tab_idx = tag // 10
        gesture_idx = tag % 10
        if tab_idx < len(self._tab_ctrls) and gesture_idx < len(GESTURE_ORDER):
            gesture = GESTURE_ORDER[gesture_idx]
            ctrls = self._tab_ctrls[tab_idx]["gestures"][gesture]
            sel = ctrls["type_popup"].titleOfSelectedItem()
            at = ACTION_TYPE_FROM_LABEL.get(sel, "key")
            self._set_gesture_visibility(ctrls, at)

    def onAddDevice_(self, sender):
        from remote_control import scan_hid_devices
        devices = scan_hid_devices()

        # Filter out already-configured devices
        configured = set()
        for dev in self._config.get("devices", []):
            configured.add((dev.get("vendor_id", ""), dev.get("product_id", "")))
        available = [d for d in devices
                     if (d["vendor_id"], d["product_id"]) not in configured]

        if not available:
            alert = NSAlert.alloc().init()
            if self._app_icon:
                alert.setIcon_(self._app_icon)
            alert.setMessageText_("No New Devices")
            alert.setInformativeText_(
                "No additional HID devices found.\n"
                "Make sure your device is connected and paired.")
            alert.runModal()
            return

        # Show picker
        alert = NSAlert.alloc().init()
        if self._app_icon:
            alert.setIcon_(self._app_icon)
        alert.setMessageText_("Add Device")
        alert.setInformativeText_("Select a connected HID device:")
        alert.addButtonWithTitle_("Add")
        alert.addButtonWithTitle_("Cancel")

        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            ((0, 0), (340, 24)), False)
        for d in available:
            transport = f"  [{d['transport']}]" if d.get("transport") else ""
            popup.addItemWithTitle_(
                f"{d['name']}  ({d['vendor_id']}:{d['product_id']}){transport}")
        alert.setAccessoryView_(popup)

        result = alert.runModal()
        if result != NSAlertFirstButtonReturn:
            return

        selected = available[popup.indexOfSelectedItem()]
        template = dict(NEW_DEVICE_TEMPLATE)
        template["name"] = selected["name"]
        template["vendor_id"] = selected["vendor_id"]
        template["product_id"] = selected["product_id"]
        self._add_device_tab(template)
        count = self._tab_view.numberOfTabViewItems()
        self._tab_view.selectTabViewItemAtIndex_(count - 1)

    def onRemoveDevice_(self, sender):
        if self._tab_view.numberOfTabViewItems() <= 1:
            return  # keep at least one device
        idx = self._tab_view.indexOfTabViewItem_(
            self._tab_view.selectedTabViewItem())
        self._tab_view.removeTabViewItem_(
            self._tab_view.selectedTabViewItem())
        del self._tab_ctrls[idx]

    def onSave_(self, sender):
        self._save_config()

    def onCancel_(self, sender):
        if self._pref_window:
            self._pref_window.close()

    @objc.python_method
    def _read_gesture(self, gc):
        """Read one gesture's controls into a config dict."""
        sel = gc["type_popup"].titleOfSelectedItem()
        at = ACTION_TYPE_FROM_LABEL.get(sel, "key")
        result = {"type": at}

        key = mods = button = command = None
        if at == "key":
            key = gc["key_combo"].stringValue()
            result["key"] = key
            mods = []
            for mname in MODIFIER_NAMES:
                if gc["mod_cbs"][mname].state() == NSControlStateValueOn:
                    mods.append(mname)
            result["modifiers"] = mods
        elif at == "mouse":
            button = gc["mouse_popup"].titleOfSelectedItem()
            result["button"] = button
        elif at == "shell":
            command = gc["shell_field"].stringValue()
            result["command"] = command

        result["description"] = auto_description(
            at, key=key, modifiers=mods, button=button, command=command)
        return result

    @objc.python_method
    def _save_config(self):
        devices = []
        for tc in self._tab_ctrls:
            dev = {
                "name": tc["name_field"].stringValue(),
                "vendor_id": tc["vendor_id"],
                "product_id": tc["product_id"],
            }
            for gesture in GESTURE_ORDER:
                dev[gesture] = self._read_gesture(tc["gestures"][gesture])

            try:
                dev["double_click_interval"] = float(
                    tc["timing_dci"].stringValue())
            except (ValueError, TypeError):
                dev["double_click_interval"] = 0.4
            try:
                dev["long_press_threshold"] = float(
                    tc["timing_lpt"].stringValue())
            except (ValueError, TypeError):
                dev["long_press_threshold"] = 0.5

            devices.append(dev)

        config = {"devices": devices}

        with open(self._config_path, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")

        self._config = dict(config)
        if self._reload_cb:
            self._reload_cb(config)

        self._pref_window.close()
