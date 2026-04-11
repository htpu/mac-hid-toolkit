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
        return self

    def setVolume_muted_(self, volume, muted):
        self._volume = volume
        self._muted = muted
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
        if self._muted:
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

    def __init__(self):
        self._window = None
        self._view = None
        self._hide_timer = None
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_init(self):
        """Initialize NSWindow on first use (must be called on main thread)."""
        if self._initialized:
            return

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        hud_w, hud_h = 160, 120
        screen = NSScreen.mainScreen()
        if screen:
            sf = screen.frame()
            x = (sf.size.width - hud_w) / 2
            y = sf.size.height * 0.25
        else:
            x, y = 500, 300

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((x, y), (hud_w, hud_h)),
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
            ((0, 0), (hud_w, hud_h)))
        self._window.setContentView_(self._view)
        self._window.setAlphaValue_(0.0)

        self._initialized = True

    def show(self, volume, muted=False):
        """Show HUD with given volume. Thread-safe — dispatches to main thread."""
        def _do_show():
            self._ensure_init()
            self._view.setVolume_muted_(volume, muted)
            self._window.setAlphaValue_(1.0)
            self._window.orderFrontRegardless()

            # Cancel previous hide timer
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
