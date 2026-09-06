"""Experimental terminal UI (curses, stdlib only).

Layout follows the vendor app (Keys / DPI / LED tabs) with lazygit-style
navigation: hjk/l or arrows, modal pickers, status bar with key hints.
All writes reuse the CLI library paths, so auto-backup and safety
validation behave exactly like the commands.
"""

import curses

from . import protocol
from .device import Device, DeviceError
from .state import (
    SafetyError,
    load_binding_entries,
    save_backup,
    save_binding_entries,
    validate_mutations,
)
from .cli import _write_bindings, _flash_frame


BUTTONS = [
    (7, "Left button"),
    (12, "Right button"),
    (17, "Middle button"),
    (27, "Forward"),
    (22, "Back"),
    (47, "DPI +"),
    (42, "DPI -"),
]

# Top-view Blake art for the Keys tab; each digit 1-7 appears exactly
# once and marks the matching BUTTONS[n-1] hotspot (1 left, 2 right,
# 3 middle, 4 forward, 5 back, 6 dpi+, 7 dpi-).
MOUSE_ART = [
    "        .----------------------.",
    "       /           3          \\",
    "      /    1           2      \\",
    "     |         ( 6 )           |",
    "  4 >|           7             |",
    "  5 >|                         |",
    "     |                         |",
    "     |            __           |",
    "     |          /    \\         |",
    "     |          \\____/         |",
    "      \\        FANTECH        /",
    "       \\______________________/",
]

ART_HOTSPOTS = {}
for _n in range(1, 8):
    for _r, _row in enumerate(MOUSE_ART):
        _c = _row.find(str(_n))
        if _c >= 0:
            ART_HOTSPOTS[_n] = (_r, _c)
            break
assert len(ART_HOTSPOTS) == 7

EFFECT_ORDER = ["chroma", "neon", "custom_breathe", "breathe", "tail", "steady", "off"]
POLLING_ORDER = (125, 250, 500, 1000)
POLLING_LABEL = {hz: f"{hz} Hz" for hz in POLLING_ORDER}

TAB_NAMES = ("Keys", "DPI", "LED")

COLOR_TITLE = 1
COLOR_ACCENT = 2
COLOR_DIM = 3
COLOR_WARN = 4


class Picker:
    """Modal filterable list. items: list of (label, payload)."""

    def __init__(self, title, items):
        self.title = title
        self.items = items
        self.sel = 0
        self.filter_text = ""
        self.top = 0

    def visible(self):
        if not self.filter_text:
            return self.items
        return [it for it in self.items if self.filter_text in it[0].lower()]

    def move(self, delta):
        vis = self.visible()
        if not vis:
            return
        self.sel = max(0, min(len(vis) - 1, self.sel + delta))
        self._scroll(vis)

    def _scroll(self, vis):
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self._rows():
            self.top = self.sel - self._rows() + 1

    def _rows(self):
        return max(4, curses.LINES - 10)


class App:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.tab = 0
        self.sel = 0
        self.picker = None
        self.picker_stage = None
        self.status = "ready"
        self.frame = None
        self.dev = None

    # ── device helpers ──────────────────────────────────────────────

    def refresh(self):
        self.frame = bytearray(self.dev.read())

    def apply_frame(self):
        current = self.dev.read()
        save_backup(current, label="auto-prewrite")
        new = bytearray(self.frame)
        validate_mutations(current, new)
        self.frame = bytearray(self.dev.apply(bytes(new)))

    def apply_flash(self, new):
        save_backup(bytearray(self.frame), label="auto-prewrite")
        self.frame = bytearray(_flash_frame(self.dev, bytes(new)))

    def write_bindings(self, entries):
        _write_bindings(self.dev, entries)
        save_binding_entries(entries)
        self.refresh()

    # ── binding state ───────────────────────────────────────────────

    def binding_for(self, slot):
        for e in load_binding_entries():
            if int(e["slot"]) == slot:
                suffix = {"keyboard": "", "keyboard_ctrl": " (ctrl)",
                          "special": "", "macro": " (macro)"}.get(e["class"], "")
                return f"{e['name']}{suffix}"
        return None

    # ── drawing ─────────────────────────────────────────────────────

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(COLOR_TITLE, curses.COLOR_RED, -1)
        curses.init_pair(COLOR_ACCENT, curses.COLOR_CYAN, -1)
        curses.init_pair(COLOR_DIM, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(COLOR_WARN, curses.COLOR_YELLOW, -1)

    def _put(self, y, x, text, attr=0):
        """Bounds-safe addstr on stdscr; never writes the last column."""
        scr = self.stdscr
        h, w = scr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w - 1:
            return
        try:
            scr.addstr(y, x, str(text)[:w - x - 1], attr)
        except curses.error:
            pass

    def draw(self):
        scr = self.stdscr
        scr.erase()
        h, w = scr.getmaxyx()
        self._draw_title(w)
        self._draw_tabs(w)
        top = 3
        body_h = h - 5
        if self.tab == 0:
            self._draw_keys_tab(scr, top, body_h, w)
        elif self.tab == 1:
            self._draw_dpi_tab(scr, top)
        else:
            self._draw_led_tab(scr, top)
        self._draw_status(w, h)
        if self.picker:
            self._draw_picker(scr, h, w)
        # single window, single refresh: getch()'s implicit stdscr
        # refresh can no longer wipe anything
        scr.refresh()

    def _draw_title(self, w):
        t = " x17blake TUI — Fantech X17 Blake (2ea8:2203) "
        self._put(0, max(0, (w - len(t)) // 2), t,
                  curses.A_BOLD | curses.color_pair(COLOR_TITLE))
        self._put(1, 2, "testing build — every write auto-backs up "
                        "to ~/.config/x17blake/", curses.A_DIM)

    def _draw_tabs(self, w):
        x = 2
        for i, name in enumerate(TAB_NAMES):
            label = f" {i + 1} {name} "
            attr = curses.A_REVERSE | curses.A_BOLD if i == self.tab else 0
            self._put(2, x, label, attr)
            x += len(label) + 2

    def _draw_keys_tab(self, scr, top, body_h, w):
        entries = {int(e["slot"]): e for e in load_binding_entries()}

        if w >= 70 and body_h >= 15:
            self._draw_keys_threezone(scr, top, body_h, entries, w)
            return

        # fallback for narrow/short terminals: single full-width list
        self._put(top, 2, "Button assignment", curses.A_BOLD)
        for i, (slot, label) in enumerate(BUTTONS):
            e = entries.get(slot)
            target = (e["name"] if e else None) or "native"
            marker = ">" if i == self.sel else " "
            attr = curses.A_REVERSE if i == self.sel else 0
            self._put(top + 2 + i, 2,
                      f" {marker} {i + 1}  {label:<16} -> {target}", attr)
        self._put(top + 11, 2, "the device never reports bindings back;",
                  curses.A_DIM)
        self._put(top + 12, 2,
                  "this list is locally tracked state (same as CLI)",
                  curses.A_DIM)

    def _draw_keys_threezone(self, scr, top, body_h, entries, w):
        compact = w < 88
        left_w = 22 if compact else 30
        right_w = 20 if compact else 24

        # left pane: main clicks + side buttons (1-5)
        self._put(top, 1, "Buttons", curses.A_BOLD)
        for i, (slot, label) in enumerate(BUTTONS[:5]):
            marker = ">" if i == self.sel else " "
            line = f" {marker} {i + 1}  {label[:12] if compact else label}"
            if not compact:
                e = entries.get(slot)
                line += f" -> {(e['name'] if e else None) or 'native'}"
            attr = curses.A_REVERSE if i == self.sel else 0
            self._put(top + 2 + i, 1, line[:left_w - 2], attr)

        # right pane: DPI buttons (6-7) + details of the selected button
        rx = w - right_w - 1
        self._put(top, rx, "DPI", curses.A_BOLD)
        for j, i in ((1, 5), (2, 6)):
            slot, label = BUTTONS[i]
            marker = ">" if i == self.sel else " "
            attr = curses.A_REVERSE if i == self.sel else 0
            self._put(top + j, rx, f" {marker} {i + 1}  {label}", attr)

        slot, label = BUTTONS[self.sel]
        e = entries.get(slot)
        binding = (e["name"] if e else None) or "native"
        details = [
            ("Details", curses.A_BOLD),
            (f"{self.sel + 1} {label}", 0),
            (f"slot {slot}", 0),
            (f"binding: {binding}", 0),
            ("", 0),
            ("enter assign", curses.A_DIM),
            ("d clear binding", curses.A_DIM),
        ]
        for j, (text, attr) in enumerate(details):
            self._put(top + 4 + j, rx, text, attr)
        for j, note in enumerate(
            ["wheel up/down are", "factory residents.", "Bindings are",
             "locally tracked", "state only (the", "device never",
             "reports them)."]
        ):
            self._put(top + body_h - 7 + j, rx, note, curses.A_DIM)

        # middle: the mouse, with the selected hotspot highlighted
        art_w = max(len(r) for r in MOUSE_ART)
        zone = w - left_w - right_w - 2
        ax = left_w + max(0, (zone - art_w) // 2)
        for r, row in enumerate(MOUSE_ART):
            self._put(top + 2 + r, ax, row[:zone], curses.A_DIM)
        for n, (r, c) in ART_HOTSPOTS.items():
            attr = curses.color_pair(COLOR_TITLE) | curses.A_BOLD
            if n - 1 == self.sel:
                attr |= curses.A_REVERSE
            self._put(top + 2 + r, ax + c, str(n), attr)

    def _draw_dpi_tab(self, scr, top):
        f = self.frame
        active = f[7]
        mask = f[8]
        self._put(top, 2, "DPI stages  (mask=%02X)" % mask, curses.A_BOLD)
        for i in range(7):
            x, y = protocol.dpi_stage_decode(f[protocol.stage_offset(i + 1):][:3])
            mark = "*" if i == active else " "
            cur = ">" if i == self.sel else " "
            val = f"{x}" if x == y else f"{x}/{y}"
            attr = curses.A_REVERSE if i == self.sel else 0
            star = curses.A_BOLD if i == active else 0
            self._put(top + 2 + i, 2,
                      f" {cur} stage {i + 1}: {val:>9} dpi {mark}", attr | star)
        hz = protocol.polling_from_raw(f[33])
        cur = ">" if self.sel == 7 else " "
        attr = curses.A_REVERSE if self.sel == 7 else 0
        self._put(top + 9, 2, f" {cur} polling : {POLLING_LABEL.get(hz, '?'):>9}", attr)
        self._put(top + 11, 2, "* = active stage", curses.A_DIM)

    def _draw_led_tab(self, scr, top):
        f = self.frame
        eid = f[37]
        names = {protocol.EFFECT_NAMES[n]: n for n in EFFECT_ORDER}
        current = names.get(eid, f"id {eid}")
        self._put(top, 2, "Lighting", curses.A_BOLD)
        self._put(top + 2, 2, f"  mode      : {current}")
        self._put(top + 3, 2, f"  brightness: {f[39]}  (0-4)")
        speed = protocol.led_speed_from_wire(f[38])
        self._put(top + 4, 2, f"  speed     : {speed}  (0-2, user scale)")
        palette = " ".join("%02X%02X%02X" % tuple(f[o:o + 3])
                           for o in (protocol.color_offset(i) for i in range(1, 8)))
        self._put(top + 6, 2, "  palette   : " + palette, curses.A_DIM)
        self._put(top + 9, 2, "enter cycles mode · +/- brightness · [/] speed",
                  curses.A_DIM)

    def _draw_status(self, w, h):
        hint = "1-3/tab tabs · j/k move · enter apply · q quit"
        if self.tab == 0:
            hint = "enter assign · d clear binding · " + hint.replace("enter apply · ", "")
        if self.tab == 1:
            hint = "+/- dpi · a set active · p polling · " + hint.replace("enter apply · ", "")
        self._put(h - 2, 0, self.status.ljust(w - 1), curses.A_DIM)
        self._put(h - 1, 0, (" " + hint).ljust(w - 1),
                  curses.color_pair(COLOR_DIM))

    def _draw_picker(self, scr, h, w):
        p = self.picker
        vis = p.visible()
        rows = min(len(vis) or 1, max(4, h - 10))
        box_h = rows + 4
        box_w = min(56, w - 6)
        y0 = max(0, (h - box_h) // 2)
        x0 = max(0, (w - box_w) // 2)
        self._put(y0, x0, "+" + "-" * (box_w - 2) + "+", curses.A_BOLD)
        self._put(y0 + box_h - 1, x0, "+" + "-" * (box_w - 2) + "+")
        self._put(y0, x0 + 2, f" {p.title} ", curses.A_BOLD)
        self._put(y0 + 1, x0 + 1, f"filter: {p.filter_text}_")
        for i in range(rows):
            idx = p.top + i
            if idx >= len(vis):
                break
            label = vis[idx][0]
            attr = curses.A_REVERSE if idx == p.sel else 0
            self._put(y0 + 2 + i, x0 + 1, (" " + label)[:box_w - 3], attr)
        self._put(y0 + box_h - 1, x0 + 2,
                  " type to filter · enter pick · esc cancel ", curses.A_DIM)

    # ── input ───────────────────────────────────────────────────────

    def run(self):
        scr = self.stdscr
        scr.keypad(True)
        try:
            self._init_colors()
        except curses.error:
            pass
        with Device() as dev:
            self.dev = dev
            self.refresh()
            while True:
                self.draw()
                key = scr.getch()
                if key in (27, -1):
                    if key == 27 and self.picker:
                        self.picker = None
                        self.picker_stage = None
                        continue
                    break
                if not self._handle(key):
                    break

    def _handle(self, key):
        if key == curses.KEY_RESIZE:
            return True
        if self.picker:
            return self._handle_picker(key)
        if key in (ord("q"), ord("Q")):
            return False
        if key in (curses.KEY_LEFT,):
            self.tab = (self.tab - 1) % 3
            self.sel = 0
            return True
        if key in (curses.KEY_RIGHT, ord("\t")):
            self.tab = (self.tab + 1) % 3
            self.sel = 0
            return True
        if key in map(ord, "123"):
            self.tab = key - ord("1")
            self.sel = 0
            return True
        if key in (curses.KEY_DOWN, ord("j")):
            self._move_sel(1)
            return True
        if key in (curses.KEY_UP, ord("k")):
            self._move_sel(-1)
            return True
        if self.tab == 0:
            return self._handle_keys_tab(key)
        if self.tab == 1:
            return self._handle_dpi_tab(key)
        return self._handle_led_tab(key)

    def _move_sel(self, delta):
        limit = {0: len(BUTTONS) - 1, 1: 7, 2: 0}[self.tab]
        self.sel = max(0, min(limit, self.sel + delta))

    def _status_err(self, err):
        self.status = f"error: {err}"

    def _handle_keys_tab(self, key):
        if key not in (curses.KEY_ENTER, 10, 13, ord("d")):
            return True
        slot, _label = BUTTONS[self.sel]
        try:
            if key == ord("d"):
                entries = [e for e in load_binding_entries()
                           if int(e["slot"]) != slot]
                self.write_bindings(entries)
                self.status = f"cleared binding for {BUTTONS[self.sel][1]}"
                return True
            self.picker_stage = ("assign", slot)
            self.picker = Picker(
                f"assign {BUTTONS[self.sel][1]}",
                [("clear binding", ("clear", None)),
                 ("keyboard key...", ("keyboard", None)),
                 ("special function...", ("special", None)),
                 ("cancel", ("cancel", None))],
            )
        except (SafetyError, DeviceError, OSError) as err:
            self._status_err(err)
        return True

    def _handle_dpi_tab(self, key):
        f = self.frame
        try:
            if key in (ord("+"), ord("=")):
                if self.sel < 7:
                    self._bump_stage(self.sel + 1, +100)
                return True
            if key == ord("-"):
                if self.sel < 7:
                    self._bump_stage(self.sel + 1, -100)
                return True
            if key == ord("a") and self.sel < 7:
                new = bytearray(f)
                protocol.set_active_stage(new, self.sel)
                self.frame = new
                self.apply_frame()
                self.status = f"active stage -> {self.sel + 1}"
                return True
            if key == ord("p") and self.sel == 7:
                hz = protocol.polling_from_raw(f[33]) or 1000
                nxt = POLLING_ORDER[(POLLING_ORDER.index(hz) + 1) % len(POLLING_ORDER)]
                new = bytearray(f)
                protocol.set_polling(new, nxt)
                self.frame = new
                self.apply_frame()
                self.status = f"polling -> {nxt} Hz"
        except (SafetyError, DeviceError, ValueError, OSError) as err:
            self._status_err(err)
        return True

    def _bump_stage(self, index, delta):
        f = self.frame
        x, y = protocol.dpi_stage_decode(f[protocol.stage_offset(index):][:3])
        target = (x if x == y else y) + delta
        new = bytearray(f)
        protocol.set_stage(new, index, target, target)
        self.frame = new
        self.apply_frame()
        self.status = f"stage {index} -> {target} dpi"

    def _handle_led_tab(self, key):
        if key not in (curses.KEY_ENTER, 10, 13, ord("+"), ord("="),
                       ord("-"), ord("["), ord("]")):
            return True
        f = self.frame
        new = bytearray(f)
        try:
            if key in (curses.KEY_ENTER, 10, 13):
                ids = [protocol.EFFECT_NAMES[n] for n in EFFECT_ORDER]
                nxt = ids[(ids.index(f[37]) + 1) % len(ids)] if f[37] in ids else ids[0]
                protocol.set_effect(new, nxt)
                what = f"effect -> {EFFECT_ORDER[nxt]}"
            elif key in (ord("+"), ord("=")):
                protocol.set_brightness(new, min(4, f[39] + 1))
                what = f"brightness -> {min(4, f[39] + 1)}"
            elif key == ord("-"):
                protocol.set_brightness(new, max(0, f[39] - 1))
                what = f"brightness -> {max(0, f[39] - 1)}"
            elif key == ord("]"):
                protocol.set_speed(new, min(2, protocol.led_speed_from_wire(f[38]) + 1))
                what = f"speed -> {min(2, protocol.led_speed_from_wire(f[38]) + 1)}"
            else:
                protocol.set_speed(new, max(0, protocol.led_speed_from_wire(f[38]) - 1))
                what = f"speed -> {max(0, protocol.led_speed_from_wire(f[38]) - 1)}"
            self.apply_flash(new)
            self.status = what
        except (SafetyError, DeviceError, ValueError, OSError) as err:
            self._status_err(err)
        return True

    # ── picker flow ─────────────────────────────────────────────────

    def _handle_picker(self, key):
        p = self.picker
        if key in (curses.KEY_DOWN, ord("j")):
            p.move(1)
            return True
        if key in (curses.KEY_UP, ord("k")):
            p.move(-1)
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            p.filter_text = p.filter_text[:-1]
            p.sel = p.top = 0
            return True
        if 32 <= key < 127:
            p.filter_text += chr(key).lower()
            p.sel = p.top = 0
            return True
        if key == 27:
            self.picker = None
            return True
        if key not in (curses.KEY_ENTER, 10, 13):
            return True
        vis = p.visible()
        if not vis:
            return True
        choice = vis[p.sel][1]
        if self.picker_stage[0] == "assign":
            return self._picker_assign(choice)
        return self._picker_value(choice)

    def _picker_assign(self, choice):
        kind, _payload = choice
        slot = self.picker_stage[1]
        if kind == "cancel":
            self.picker = None
            return True
        if kind == "clear":
            self.picker = None
            try:
                entries = [e for e in load_binding_entries()
                           if int(e["slot"]) != slot]
                self.write_bindings(entries)
                self.status = f"cleared {BUTTONS[self.sel][1]}"
            except (SafetyError, DeviceError, OSError) as err:
                self._status_err(err)
            return True
        if kind == "keyboard":
            items = [(n, ("keyboard", protocol.KEYBOARD_KEY_NAMES[n], n))
                     for n in sorted(protocol.KEYBOARD_KEY_NAMES)]
        else:
            items = [(n, ("special", protocol.SPECIAL_FUNCTION_TAGS[n], n))
                     for n in sorted(protocol.SPECIAL_FUNCTION_TAGS)]
        self.picker_stage = ("value", slot)
        self.picker = Picker(kind, items)
        return True

    def _picker_value(self, choice):
        kind, code, name = choice
        slot = self.picker_stage[1]
        self.picker = None
        self.picker_stage = None
        try:
            entries = [e for e in load_binding_entries()
                       if int(e["slot"]) != slot]
            entries.append({"slot": slot, "class": kind,
                            "code": code, "name": name})
            self.write_bindings(entries)
            self.status = f"{BUTTONS[self.sel][1]} -> {name}"
        except (SafetyError, DeviceError, OSError) as err:
            self._status_err(err)
        return True


def run():
    def _main(stdscr):
        App(stdscr).run()
        return 0

    try:
        return curses.wrapper(_main)
    except DeviceError as err:
        print(f"error: {err}")
        print("hint: x17blake info   (check the mouse is plugged in)")
        return 1
    except PermissionError as err:
        print(f"error: {err}")
        print("hint: sudo ./install.sh   (installs the udev rule)")
        return 1
