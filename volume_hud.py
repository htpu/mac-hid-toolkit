"""
Volume HUD — macOS-style floating volume indicator.
Shows a dark rounded overlay with volume bar and icon when called.
Auto-hides after a short delay. Thread-safe.
"""

import threading
import time
import objc
from AppKit import (
    NSApplication, NSWindow, NSView, NSColor, NSFont,
    NSBezierPath, NSRoundedBezelStyle,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSScreen, NSGraphicsContext,
    NSCompositingOperationSourceOver, NSTextField,
    NSTextAlignmentCenter, NSLineBreakByClipping,
    NSApplicationActivationPolicyAccessory,
)
from CoreFoundation import CFRunLoopGetMain, CFRunLoopPerformBlock, kCFRunLoopCommonModes
import Quartz


class VolumeHUDView(NSView):
    """Custom view that draws the volume HUD."""

    def initWithFrame_(self, frame):
        self = objc.super(VolumeHUDView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._volume = 50
        self._muted = False
        self._mode = "volume"
        return self

    def setVolume_muted_(self, volume, muted):
        self._volume = volume
        self._muted = muted
        self._mode = "volume"
        self.setNeedsDisplay_(True)

    def setBrightness_(self, level):
        self._volume = level
        self._muted = False
        self._mode = "brightness"
        self.setNeedsDisplay_(True)

    def isOpaque(self):
        return False

    def drawRect_(self, rect):
        w = rect.size.width
        h = rect.size.height

        # ── Background: dark rounded rect ──
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, 18, 18)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.1, 0.85).set()
        bg_path.fill()

        # ── Speaker icon (Unicode) ──
        icon_font = NSFont.systemFontOfSize_(28)
        if self._mode == "brightness":
            icon = "☀️" if self._volume > 0 else "🌙"
        elif self._muted:
            icon = "🔇"
        elif self._volume == 0:
            icon = "🔈"
        elif self._volume < 50:
            icon = "🔉"
        else:
            icon = "🔊"

        icon_attrs = {
            "NSFont": icon_font,
            "NSColor": NSColor.whiteColor(),
        }
        icon_str = objc.lookUpClass("NSAttributedString").alloc().initWithString_attributes_(
            icon, icon_attrs)
        icon_size = icon_str.size()
        icon_x = (w - icon_size.width) / 2
        icon_y = h - 50 - icon_size.height / 2
        icon_str.drawAtPoint_((icon_x, icon_y))

        # ── Volume bar ──
        bar_margin = 24
        bar_y = 30
        bar_h = 8
        bar_w = w - bar_margin * 2
        bar_x = bar_margin

        # Bar background
        bar_bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((bar_x, bar_y), (bar_w, bar_h)), 4, 4)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.3, 0.3, 1.0).set()
        bar_bg.fill()

        # Bar fill
        if self._volume > 0:
            fill_w = max(bar_h, bar_w * self._volume / 100)
            bar_fill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                ((bar_x, bar_y), (fill_w, bar_h)), 4, 4)
            NSColor.whiteColor().set()
            bar_fill.fill()

        # ── Percentage text ──
        pct_font = NSFont.monospacedSystemFontOfSize_weight_(14, 0.0)
        if self._mode == "brightness":
            pct_text = f"{self._volume}%"
        else:
            pct_text = "MUTED" if self._muted else f"{self._volume}%"
        pct_attrs = {
            "NSFont": pct_font,
            "NSColor": NSColor.colorWithCalibratedRed_green_blue_alpha_(0.7, 0.7, 0.7, 1.0),
        }
        pct_str = objc.lookUpClass("NSAttributedString").alloc().initWithString_attributes_(
            pct_text, pct_attrs)
        pct_size = pct_str.size()
        pct_x = (w - pct_size.width) / 2
        pct_str.drawAtPoint_((pct_x, 10))


class VolumeHUD:
    """Thread-safe volume HUD manager."""

    HUD_W = 160
    HUD_H = 120

    def __init__(self):
        self._window = None
        self._view = None
        self._hide_timer = None
        self._lock = threading.Lock()
        self._initialized = False

    def _find_screen(self, name):
        """Return NSScreen whose localizedName matches `name`, or None."""
        if not name:
            return None
        for s in NSScreen.screens():
            if s.respondsToSelector_("localizedName") and s.localizedName() == name:
                return s
        return None

    def _position_on_screen(self, screen):
        """Move the HUD window to the given NSScreen (or main if None)."""
        if screen is None:
            screen = NSScreen.mainScreen()
        if screen is None:
            return
        sf = screen.frame()
        x = sf.origin.x + (sf.size.width - self.HUD_W) / 2
        y = sf.origin.y + sf.size.height * 0.25
        self._window.setFrameOrigin_((x, y))

    def _ensure_init(self):
        """Initialize NSWindow on first use (must be called on main thread)."""
        if self._initialized:
            return

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        screen = NSScreen.mainScreen()
        if screen:
            sf = screen.frame()
            x = sf.origin.x + (sf.size.width - self.HUD_W) / 2
            y = sf.origin.y + sf.size.height * 0.25
        else:
            x, y = 500, 300

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((x, y), (self.HUD_W, self.HUD_H)),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(NSFloatingWindowLevel + 1)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(1 << 0 | 1 << 4)  # canJoinAllSpaces | transient

        self._view = VolumeHUDView.alloc().initWithFrame_(
            ((0, 0), (self.HUD_W, self.HUD_H)))
        self._window.setContentView_(self._view)
        self._window.setAlphaValue_(0.0)

        self._initialized = True

    def show(self, volume, muted=False, screen_name=None):
        """Show HUD with given volume. Thread-safe — dispatches to main thread.

        If `screen_name` matches a connected display's localized name, the HUD
        is positioned on that screen; otherwise it falls back to the main screen.
        """
        def _do_show():
            self._ensure_init()
            self._position_on_screen(self._find_screen(screen_name))
            self._view.setVolume_muted_(volume, muted)
            self._window.setAlphaValue_(1.0)
            self._window.orderFrontRegardless()

            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(1.5, self._fade_out)
            self._hide_timer.daemon = True
            self._hide_timer.start()

        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, _do_show)

    def show_brightness(self, level, screen_name=None):
        """Show HUD in brightness mode. Thread-safe."""
        def _do_show():
            self._ensure_init()
            self._position_on_screen(self._find_screen(screen_name))
            self._view.setBrightness_(level)
            self._window.setAlphaValue_(1.0)
            self._window.orderFrontRegardless()

            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(1.5, self._fade_out)
            self._hide_timer.daemon = True
            self._hide_timer.start()

        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, _do_show)

    def _fade_out(self):
        def _do_fade():
            if self._window:
                self._window.setAlphaValue_(0.0)
                self._window.orderOut_(None)
        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, _do_fade)
