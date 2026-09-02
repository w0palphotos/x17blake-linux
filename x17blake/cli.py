import argparse
import difflib
import json
import os
import re
import struct
import sys
import time

from . import hidraw, protocol
from .device import Device, DeviceError
from .state import (
    SafetyError,
    diff_bytes,
    latest_path,
    load_backup,
    load_binding_entries,
    save_backup,
    save_binding_entries,
    binding_table,
    validate_mutations,
)

STATE_DIR = os.path.expanduser("~/.config/x17blake")
MACRO_DIR = os.path.join(STATE_DIR, "macros")
USER_PRESET_DIR = os.path.join(STATE_DIR, "presets")
BUNDLED_PRESET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets"
)


EFFECT_NAMES = protocol.EFFECT_NAMES


def cmd_tui(_args):
    from . import tui
    return tui.run()


def _fail(msg, code=2):
    print(f"error: {msg}")
    raise SystemExit(code)


def _open_path():
    nodes = hidraw.find_hidraw(interface=1)
    return nodes[0][1] if nodes else None


def cmd_info(_args):
    nodes = hidraw.find_hidraw()
    if not nodes:
        print("device not found (2ea8:2203)")
        return 1
    where = hidraw.usb_location(nodes[0][1])
    if where:
        print(
            f"Bus {where[0]:03d} Device {where[1]:03d}: "
            f"ID {hidraw.VENDOR_ID:04x}:{hidraw.PRODUCT_ID:04x}"
        )
    denied = False
    for iface, node in nodes:
        ok = os.access(node, os.R_OK | os.W_OK)
        denied = denied or not ok
        print(f"{node}  interface={iface}  {'ok' if ok else 'permission denied'}")
    if denied:
        print("hint: run `sudo ./install.sh` from the repo (or see README)")
        return 1
    return 0


def _stage_line(frame):
    active = frame[7] + 1
    parts = []
    for i in range(7):
        off = protocol.stage_offset(i + 1)
        x, y = protocol.dpi_stage_decode(frame[off : off + 3])
        mark = "*" if i + 1 == active else " "
        parts.append(f"{mark}{i+1}:{x}" if x == y else f"{mark}{i+1}:{x}/{y}")
    return "  ".join(parts)


def _show_pretty(frame):
    s = protocol.parse_settings(frame)
    node = _open_path() or "?"
    print(f"Fantech X17 Blake ({node})")
    print(f"  profile   : {s['profile']}")
    print(f"  dpi       : {_stage_line(frame)}")
    print(f"  polling   : {s['polling_hz'] or '?'} Hz")
    led = s["led_effect"]
    print(f"  led       : {led}  brightness={s['led_brightness']} speed={s['led_speed']}")
    colors = "  ".join(f"{i+1}:%02X%02X%02X" % c for i, c in enumerate(s["colors"]))
    print(f"  colors    : {colors}")


def cmd_show(args):
    with Device() as dev:
        frame = dev.read()
    if args.json:
        print(json.dumps(protocol.parse_settings(frame), indent=2))
    else:
        _show_pretty(frame)
    return 0


def cmd_probe(args):
    with Device() as dev:
        response = dev.read()
        print(protocol.format_hexdump(response))
        if args.roundtrip:
            verify = dev.apply(protocol.build_set_settings(response), validate=False)
            ok = verify == response
            print("roundtrip:", "OK (state unchanged)" if ok else "STATE CHANGED")
            return 0 if ok else 3
    return 0


def _mutate_and_apply(dev, mutator, what):
    current = dev.read()
    save_backup(current, label="auto-prewrite")
    new = bytearray(current)
    mutator(new)
    changed = validate_mutations(current, new) if bytes(current) != bytes(new) else []
    state = dev.apply(bytes(new))
    print(f"{what}: applied ({len(changed)} byte(s) changed)")
    return state


def _resolve_dpi(value):
    try:
        protocol.dpi_to_register(value)
    except ValueError as err:
        _fail(str(err))
    return value


def cmd_dpi(args):
    _resolve_dpi(args.dpi)
    with Device() as dev:
        current = dev.read()
        active = current[7] + 1

        def mut(f):
            protocol.set_stage(f, active, args.dpi, args.dpi)

        state = _mutate_and_apply(dev, mut, f"dpi stage {active} -> {args.dpi}")
        got = protocol.dpi_stage_decode(state[protocol.stage_offset(active) :][:3])
        print(f"verified: stage {active} = {got[0]} / {got[1]} dpi")
        return 0 if got == (args.dpi, args.dpi) else 3


def cmd_stage(args):
    _resolve_dpi(args.dpi)
    if not 1 <= args.index <= 7:
        _fail("stage index must be 1..7")
    with Device() as dev:

        def mut(f):
            protocol.set_stage(f, args.index, args.dpi, args.dpi)

        state = _mutate_and_apply(dev, mut, f"dpi stage {args.index} -> {args.dpi}")
        got = protocol.dpi_stage_decode(state[protocol.stage_offset(args.index) :][:3])
        print(f"verified: stage {args.index} = {got[0]} / {got[1]} dpi")
        return 0 if got == (args.dpi, args.dpi) else 3


def _parse_color(text):
    try:
        rgb = bytes.fromhex(text)
    except ValueError:
        rgb = b""
    if len(rgb) != 3:
        _fail(f"color must be RRGGBB hex, got '{text}'")
    return rgb


def _resolve_effect(text):
    if text.lstrip("-").isdigit():
        eid = int(text, 0)
        if not 0 <= eid <= 9:
            _fail("effect id must be 0..9")
        return eid
    eid = EFFECT_NAMES.get(text)
    if eid is None:
        names = ", ".join(sorted(EFFECT_NAMES))
        _fail(f"unknown effect '{text}'\n  known: {names}")
    return eid





def cmd_led(args):
    effect_id = None
    if args.effect is not None:
        try:
            effect_id = protocol.resolve_effect(args.effect)
        except ValueError as err:
            _fail(str(err))

    brightness = 4 if args.brightness is None else args.brightness
    enable = effect_id != protocol.EFFECT_NAMES["off"] if effect_id is not None else True
    rgb = _parse_color(args.color) if args.color else None

    def mut(f):
        if effect_id is not None:
            protocol.set_effect(f, effect_id)
        if args.speed is not None:
            protocol.set_speed(f, args.speed)
        if rgb is not None:
            for i in range(1, 8):
                protocol.set_stage_color(f, i, rgb)
        protocol.set_brightness(f, brightness)
        f[40] = 1
        f[41] = protocol.COLOR_SLOTS_ALL

    what = "led"
    if effect_id is not None:
        what += f" mode={args.effect}"
    what += f" brightness={brightness}"
    if args.speed is not None:
        what += f" speed={args.speed}"
    if rgb is not None:
        what += f" color={args.color}"

    with Device() as dev:
        current = dev.read()
        save_backup(current, label="auto-prewrite")
        new = bytearray(current)
        mut(new)
        validate_mutations(current, new)
        out = bytearray(new)
        out[3] = protocol.CMD_SET_SETTINGS
        dev.led_begin_session()
        for param_frame in protocol.build_led_params(enable, brightness):
            dev._port.exchange(param_frame)
        dev._port.exchange(bytes(out))
        dev._port.exchange(dev.binding_commit())
        time.sleep(0.05)
        state = dev.read()
    print(f"{what}: applied")
    _show_pretty(state)
    return 0


def cmd_polling(args):
    with Device() as dev:

        def mut(f):
            protocol.set_polling(f, args.hz)

        state = _mutate_and_apply(dev, mut, f"polling -> {args.hz} Hz")
        raw = state[protocol.POLLING_OFFSET]
        hz = protocol.polling_from_raw(raw)
        ok = hz == args.hz
        print(f"verified: byte33={raw:#04x} => {hz} Hz")
        return 0 if ok else 3


# --- key bindings ------------------------------------------------------

def _load_bindings():
    return load_binding_entries()


def _save_bindings(entries):
    save_binding_entries(entries)


def _entries_to_table(entries):
    return binding_table(entries)


def _format_slot(offset):
    name = protocol.SLOT_NAMES.get(offset, f"0x{offset:02X}")
    star = "" if offset in protocol.VERIFIED_SLOTS else " (unmapped)"
    return f"{name}{star}"


def _describe_table(entries):
    if not entries:
        return ["  (no custom bindings — all buttons factory-default)"]
    lines = []
    for e in sorted(entries, key=lambda x: x["slot"]):
        target = e["name"]
        if e["class"] == "keyboard":
            target += " (keyboard)"
        lines.append(f"  {_format_slot(int(e['slot'])):20s} -> {target}")
    return lines


def cmd_keys(args):
    action = args.action or "show"

    if action == "show":
        entries = _load_bindings()
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            print("tracked button bindings (local state — the device never")
            print("reports bindings back; bindings made in OemDrv are invisible here):")
            for line in _describe_table(entries):
                print(line)
        return 0

    if action == "bind":
        if not args.slot:
            _fail("bind requires a slot: forward|back|dpi_minus|dpi_plus [--experimental]")
        if len(args.slot) != 1:
            _fail("bind takes exactly one slot")
        if args.mouse is not None:
            _fail(
                "mouse-button targets are not yet decodable on the wire "
                "(Cfg.ini codes are UI-only); use --key or --hid for now"
            )
        offset = _resolve_slot(args.slot[0], args.experimental)
        key_class, code, label = _resolve_target(args)

        entries = [e for e in _load_bindings() if int(e["slot"]) != offset]
        class_name = {
            protocol.KEY_CLASS_KEYBOARD: "keyboard",
            protocol.KEY_CLASS_KEYBOARD_CTRL: "keyboard_ctrl",
            "special": "special",
            "macro": "macro",
        }[key_class]
        entries.append({"slot": offset, "class": class_name, "code": code, "name": label})

        with Device() as dev:
            if key_class == "macro":
                steps = _resolve_macro_steps(args)
                dev.upload_macro(code, steps)
            _write_bindings(dev, entries)
        _save_bindings(entries)
        print(f"bound {_format_slot(offset)} -> {label}; current table:")
        for line in _describe_table(entries):
            print(line)
        return 0

    if action == "clear":
        if not args.slot and not args.all:
            _fail("clear requires at least one slot (or --all)")
        targets = {_resolve_slot(name, args.experimental) for name in args.slot}
        entries = _load_bindings()
        kept = [
            e for e in entries
            if not (int(e["slot"]) in targets and _may_touch(int(e["slot"]), args.experimental))
        ]
        if args.all:
            kept = []
        removed = len(entries) - len(kept)
        if not removed and not args.all:
            print("nothing to clear for the given slot(s)")
            return 0
        with Device() as dev:
            _write_bindings(dev, kept)
        _save_bindings(kept)
        if removed:
            print(f"cleared {removed} binding(s);", end=" ")
        else:
            print("wrote empty binding table;", end=" ")
        print("current table:")
        for line in _describe_table(kept):
            print(line)
        return 0

    _fail(f"unknown keys action '{action}'")


def _may_touch(offset, experimental):
    return offset in protocol.VERIFIED_SLOTS or experimental


def _resolve_slot(name, experimental):
    text = str(name).strip().lower()
    named = {v: k for k, v in protocol.SLOT_NAMES.items()}
    if text in named:
        offset = named[text]
    else:
        try:
            offset = int(text, 16) if text.startswith("0x") else int(text)
        except ValueError:
            known = ", ".join(sorted(set(protocol.SLOT_NAMES.values())))
            _fail(f"unknown slot '{name}'\n  known: {known}")
        if offset not in protocol.COMMIT_SLOT_OFFSETS or offset in protocol.SLOT_RESIDENTS:
            _fail(f"offset {offset} is not an assignable binding slot")
    if not _may_touch(offset, experimental):
        _fail(
            f"slot {text} is not yet mapped to a physical button "
            "(run tools/probe_slots.py first); pass --experimental to force"
        )
    return offset


def _resolve_target(args):
    given = [v for v in (args.key, args.hid, args.special, args.macro, args.macro_file) if v is not None]
    if len(given) != 1:
        _fail("choose exactly one of --key, --special, --hid, --macro, or --macro-file")
    if args.macro_file is not None:
        return "macro", 1, f"macro-file:{args.macro_file}"
    if args.macro is not None:
        return "macro", args.macro, f"macro:{args.macro}"
    if args.special is not None:
        name = args.special.strip().lower()
        tag = protocol.SPECIAL_FUNCTION_TAGS.get(name)
        if tag is None:
            _fail(
                f"unknown special function '{args.special}'\n  known: "
                + ", ".join(sorted(protocol.SPECIAL_FUNCTION_TAGS))
            )
        return "special", tag, name
    if args.key is not None:
        try:
            code = protocol.hid_keyboard_code(args.key)
        except ValueError as err:
            _fail(str(err))
        return protocol.KEY_CLASS_KEYBOARD, code, args.key.lower()
    try:
        code = int(args.hid, 16) if args.hid.startswith("0x") else int(args.hid)
    except (ValueError, AttributeError):
        _fail(f"--hid expects a number, got '{args.hid}'")
    if not 0 <= code <= 0xE7:
        _fail("--hid code must be 0..0xE7")
    return protocol.KEY_CLASS_KEYBOARD, code, f"hid:{code:#04x}"


# ── Macro step builder ──────────────────────────────────────────────

# HID usage codes for common modifier keys
_MOD_HID = {
    "ctrl": 0xE0, "lctrl": 0xE0, "rctrl": 0xE4,
    "shift": 0xE1, "lshift": 0xE1, "rshift": 0xE5,
    "alt": 0xE2, "lalt": 0xE2, "ralt": 0xE6,
    "gui": 0xE3, "lgui": 0xE3, "rgui": 0xE7,
    "win": 0xE3, "super": 0xE3,
}

# Predefined macros (id -> (steps, description))
BUILTIN_MACROS = {
    1: {
        "name": "ctrl_alt_t",
        "desc": "Ctrl+Alt+T (terminal)",
        "steps": [
            ("down", 0xE2), ("down", 0xE0),    # Alt, Ctrl
            ("delay", 140),
            ("down", 0x17),                      # T
            ("delay", 79),
            ("up", 0x17),                        # T
            ("delay", 31),
            ("up", 0xE2),                        # Alt
            ("delay", 15),
            ("up", 0xE0),                        # Ctrl
        ],
    },
    2: {
        "name": "ctrl_shift_esc",
        "desc": "Ctrl+Shift+Esc (task manager)",
        "steps": [
            ("down", 0xE0),                      # Ctrl
            ("down", 0xE1),                      # Shift
            ("delay", 30),
            ("down", 0x29),                      # Esc = 0x29
            ("delay", 30),
            ("up", 0x29),
            ("delay", 15),
            ("up", 0xE1),
            ("delay", 15),
            ("up", 0xE0),
        ],
    },
    3: {
        "name": "ctrl_c",
        "desc": "Ctrl+C (copy)",
        "steps": [
            ("down", 0xE0),
            ("delay", 20),
            ("down", 0x06),                      # C = 0x06
            ("delay", 30),
            ("up", 0x06),
            ("delay", 15),
            ("up", 0xE0),
        ],
    },
    4: {
        "name": "ctrl_v",
        "desc": "Ctrl+V (paste)",
        "steps": [
            ("down", 0xE0),
            ("delay", 20),
            ("down", 0x19),                      # V = 0x19
            ("delay", 30),
            ("up", 0x19),
            ("delay", 15),
            ("up", 0xE0),
        ],
    },
    5: {
        "name": "ctrl_z",
        "desc": "Ctrl+Z (undo)",
        "steps": [
            ("down", 0xE0),
            ("delay", 20),
            ("down", 0x1D),                      # Z = 0x1D
            ("delay", 30),
            ("up", 0x1D),
            ("delay", 15),
            ("up", 0xE0),
        ],
    },
}


def _resolve_macro_steps(args):
    """Return step list for the given macro ID or macro file."""
    if args.macro_file is not None:
        return protocol.parse_macro_file(args.macro_file)
    macro_id = args.macro
    if macro_id in BUILTIN_MACROS:
        return BUILTIN_MACROS[macro_id]["steps"]
    _fail(
        f"unknown macro ID {macro_id}\n  built-in macros:\n"
        + "\n".join(f"    {k}: {v['desc']}" for k, v in sorted(BUILTIN_MACROS.items()))
    )


def _write_bindings(dev, entries):
    """Apply the full binding table: SET(current) + COMMIT(records)."""
    current = dev.read()
    save_backup(current, label="auto-prewrite")
    commit = protocol.build_commit(_entries_to_table(entries))
    dev.apply(bytes(current), validate=False, commit=commit)
    dev.reload_bindings()
    time.sleep(0.05)
    state_frame = dev.read()
    if diff_bytes(state_frame, current):
        raise SafetyError("settings frame changed during binding write")
    return state_frame



def cmd_backup(args):
    with Device() as dev:
        frame = dev.read()
    path = save_backup(frame, label=args.label)
    print(f"backup saved: {path}")
    print(protocol.format_hexdump(frame))
    return 0


def _flash_frame(dev, frame):
    """Write a full settings frame with LED engine re-arming so the
    render follows the restored values."""
    dev.led_begin_session()
    brightness = max(0, min(protocol.LED_MAX_BRIGHTNESS, frame[39]))
    for param_frame in protocol.build_led_params(True, brightness):
        dev._port.exchange(param_frame)
    out = bytearray(frame)
    out[3] = protocol.CMD_SET_SETTINGS
    dev._port.exchange(bytes(out))
    dev._port.exchange(dev.binding_commit())
    time.sleep(0.05)
    return dev.read()


def cmd_restore(args):
    frame, record = load_backup(args.file)
    with Device() as dev:
        current = dev.read()
        changed = diff_bytes(current, frame)
        if not changed:
            print("restore: device already matches backup")
            return 0
        print(f"restore from {args.file} ({record.get('timestamp', '?')}):")
        for i in changed:
            print(f"  byte {i:2d}: {current[i]:#04x} -> {frame[i]:#04x}")
        if not args.yes:
            print("dry run; add --yes to apply")
            return 0
        state = _flash_frame(dev, frame)
        remaining = diff_bytes(state, frame)
        if remaining:
            print(f"warning: {len(remaining)} byte(s) differ after write "
                  f"(device may normalize some fields)")
            for i in remaining[:16]:
                print(f"  byte {i:2d}: wanted {frame[i]:#04x}, got {state[i]:#04x}")
            return 3
        print("restore: verified OK")
        return 0


def _preset_file(name):
    for directory in (USER_PRESET_DIR, BUNDLED_PRESET_DIR):
        path = os.path.join(directory, f"{name}.json")
        if os.path.exists(path):
            return path
    return None


def _iter_presets():
    found = {}
    label = {USER_PRESET_DIR: "user", BUNDLED_PRESET_DIR: "bundled"}
    for directory in (BUNDLED_PRESET_DIR, USER_PRESET_DIR):
        if not os.path.isdir(directory):
            continue
        if os.path.commonpath([directory]) == os.path.commonpath([directory]) and os.path.isdir(directory):
            pass
        for fn in sorted(os.listdir(directory)):
            if fn.endswith(".json"):
                found.setdefault(fn[:-5], os.path.join(label[directory], fn))
    return found


def cmd_preset(args):
    if args.action == "list":
        presets = _iter_presets()
        if not presets:
            print("no presets (save one with: x17blake preset save <name>)")
            return 0
        for name, src in sorted(presets.items()):
            print(f"{name:24s} [{src}]")
        return 0

    if not args.name:
        _fail(f"preset {args.action} requires a name")

    if args.action == "save":
        os.makedirs(USER_PRESET_DIR, exist_ok=True)
        with Device() as dev:
            frame = dev.read()
        path = os.path.join(USER_PRESET_DIR, f"{args.name}.json")
        record = {
            "label": args.name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "description": args.description or "",
            "frame_hex": bytes(frame).hex(),
            "bindings": _load_bindings(),
        }
        with open(path, "w") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        print(f"preset saved: {path}")
        return 0

    if args.action == "apply":
        path = _preset_file(args.name)
        if path is None:
            names = list(_iter_presets())
            close = difflib.get_close_matches(args.name, names, n=1, cutoff=0.4)
            hint = f" — did you mean '{close[0]}'?" if close else ""
            known = ", ".join(sorted(names)) or "(none)"
            _fail(f"unknown preset '{args.name}'{hint}\n  available: {known}")
        frame, record = load_backup(path)
        with Device() as dev:
            current = dev.read()
            changed = diff_bytes(current, frame)
            desc = record.get("description") or record.get("timestamp", "")
            print(f"applying preset '{args.name}' ({desc}):")
            for i in changed:
                print(f"  byte {i:2d}: {current[i]:#04x} -> {frame[i]:#04x}")
            if not changed:
                print("device already matches this preset")
                return 0
            if not args.yes:
                print("dry run; add --yes to apply")
                return 0
            state = _flash_frame(dev, frame)
            bindings = record.get("bindings")
            if bindings is not None:
                _write_bindings(dev, bindings)
                _save_bindings(bindings)
                print(f"restored {len(bindings)} binding(s) from preset")
        _show_pretty(state)
        return 0

    _fail(f"unknown preset action '{args.action}'")


def cmd_macro(args):
    action = args.action or "list"

    if action == "list":
        os.makedirs(MACRO_DIR, exist_ok=True)
        files = sorted(f for f in os.listdir(MACRO_DIR) if f.endswith(".macro"))
        if not files:
            print("no macros saved yet")
            print(f"  create one: x17blake macro create <name>")
            print(f"  or write a .macro file in {MACRO_DIR}/")
            return 0
        for fn in files:
            path = os.path.join(MACRO_DIR, fn)
            try:
                steps = protocol.parse_macro_file(path)
                data = protocol.encode_macro_steps(steps)
                print(f"  {fn[:-6]:20s} {len(steps):3d} steps, {len(data):3d} bytes")
            except Exception as err:
                print(f"  {fn[:-6]:20s} (error: {err})")
        return 0

    if action == "record":
        return cmd_macro_record(args)

    if action == "import":
        if not args.file:
            _fail("macro import requires --file PATH.mly")
        steps = protocol.parse_mly(args.file)
        name = args.name or os.path.splitext(os.path.basename(args.file))[0]
        path = _macro_path(name)
        os.makedirs(MACRO_DIR, exist_ok=True)
        with open(path, "w") as fh:
            fh.write(f"# imported from {args.file}\n")
            fh.write(_steps_to_macro_text(steps))
        data = protocol.encode_macro_steps(steps)
        print(f"imported {args.file} -> {path}")
        print(f"  {len(steps)} steps, {len(data)} wire bytes")
        return 0

    if action == "show":
        if not args.name:
            _fail("macro show requires a name")
        path = _macro_path(args.name)
        if not os.path.exists(path):
            _fail(f"macro '{args.name}' not found at {path}")
        with open(path) as fh:
            print(fh.read(), end="")
        return 0

    if action == "create":
        if not args.name:
            _fail("macro create requires a name")
        path = _macro_path(args.name)
        if os.path.exists(path) and not args.force:
            _fail(f"macro '{args.name}' already exists; use --force to overwrite")
        os.makedirs(MACRO_DIR, exist_ok=True)
        mode = input("record from keyboard or type commands? [t/r] (t): ").strip().lower()
        if mode == "r":
            try:
                rec_steps = _record_keyboard_steps()
            except RuntimeError as err:
                _fail(str(err))
            if not rec_steps:
                _fail("nothing recorded")
            with open(path, "w") as fh:
                fh.write("# recorded from keyboard\n")
                fh.write(_steps_to_macro_text(rec_steps))
        else:
            steps_text = _interactive_macro_builder(args.name)
            with open(path, "w") as fh:
                fh.write(steps_text)
        # verify it parses
        steps = protocol.parse_macro_file(path)
        data = protocol.encode_macro_steps(steps)
        print(f"\nsaved: {path}")
        print(f"  {len(steps)} steps, {len(data)} bytes")
        print(f"\nbind it: x17blake keys bind <button> --macro-file {path}")
        return 0

    if action == "delete":
        if not args.name:
            _fail("macro delete requires a name")
        path = _macro_path(args.name)
        if not os.path.exists(path):
            _fail(f"macro '{args.name}' not found")
        os.remove(path)
        print(f"deleted: {path}")
        return 0

    if action == "compile":
        path = args.file
        if not path:
            if not args.name:
                _fail("macro compile requires a name or --file")
            path = _macro_path(args.name)
        if not os.path.exists(path):
            _fail(f"not found: {path}")
        steps = protocol.parse_macro_file(path)
        data = protocol.encode_macro_steps(steps)
        frames = protocol.build_macro_frames(1, steps)
        print(f"steps: {len(steps)}, wire bytes: {len(data)}, frames: {len(frames)}")
        print(f"step data: {data.hex()}")
        for i, f in enumerate(frames):
            label = "A7" if i == 0 else f"A8[{i}]"
            print(f"  {label}: {f.hex()}")
        return 0

    _fail(f"unknown macro action '{action}'")


def _macro_path(name):
    if "/" in name or name in (".", ".."):
        _fail(f"macro name must not contain path separators: '{name}'")
    if name.endswith(".macro"):
        return name
    return os.path.join(MACRO_DIR, f"{name}.macro")


def _hid_key_name(code):
    # reverse lookup of protocol.HID_KEYBOARD_KEYS (first name wins)
    for name, val in protocol.HID_KEYBOARD_KEYS.items():
        if val == code:
            return name
    return f"hid:{code:#04x}"


# Linux evdev keycodes -> HID usages (only keys the firmware supports)
_LINUX_KEY_HID = {
    1: 0x29, 2: 0x1E, 3: 0x1F, 4: 0x20, 5: 0x21, 6: 0x22, 7: 0x23, 8: 0x24,
    9: 0x25, 10: 0x26, 11: 0x27, 12: 0x2D, 13: 0x2E, 14: 0x2A, 15: 0x2B,
    16: 0x14, 17: 0x1A, 18: 0x08, 19: 0x15, 20: 0x17, 21: 0x1C, 22: 0x18,
    23: 0x0C, 24: 0x12, 25: 0x13, 26: 0x2F, 27: 0x30, 28: 0x28, 29: 0xE0,
    30: 0x04, 31: 0x16, 32: 0x07, 33: 0x09, 34: 0x0A, 35: 0x0B, 36: 0x0D,
    37: 0x0E, 38: 0x0F, 39: 0x33, 40: 0x34, 41: 0x35, 42: 0xE1, 43: 0x31,
    44: 0x1D, 45: 0x1B, 46: 0x06, 47: 0x19, 48: 0x05, 49: 0x11, 50: 0x10,
    51: 0x36, 52: 0x37, 53: 0x38, 54: 0xE5, 55: 0x55, 56: 0xE2, 57: 0x2C,
    58: 0x39, 69: 0x53, 70: 0x47, 71: 0x5F, 72: 0x60, 73: 0x61, 74: 0x56,
    75: 0x5C, 76: 0x5D, 77: 0x5E, 78: 0x57, 79: 0x59, 80: 0x5A, 81: 0x5B,
    82: 0x62, 83: 0x63, 96: 0x58, 97: 0xE4, 98: 0x54, 99: 0x46, 100: 0xE6,
    102: 0x4A, 103: 0x52, 104: 0x4B, 105: 0x50, 106: 0x4F, 107: 0x4D,
    108: 0x51, 109: 0x4E, 110: 0x49, 111: 0x4C, 119: 0x48, 125: 0xE3,
    126: 0xE7, 127: 0x65,
}
for _f in range(10):
    _LINUX_KEY_HID[59 + _f] = 0x3A + _f        # F1-F10
_LINUX_KEY_HID[87] = 0x44                       # F11
_LINUX_KEY_HID[88] = 0x45                       # F12

_EV_FMT = "llHHI"
_EV_SIZE = struct.calcsize(_EV_FMT)


def _keyboard_event_devices():
    import glob
    nodes = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            # only devices that actually emit EV_KEY get polled; evdev
            # without EVIOCGBIT filtering would need extra ioctls, so
            # open everything and ignore unknown keycodes at read time
            nodes.append((path, fd))
        except PermissionError:
            continue
    if not nodes:
        raise RuntimeError(
            "no readable /dev/input/event* devices; run with sudo or "
            "add yourself to the input group (sudo usermod -aG input $USER)"
        )
    return nodes


def _record_keyboard_steps(stop_double_esc=True):
    """Record physical keyboard into steps.  Press Esc twice (<400ms) to stop."""
    import select
    import termios
    import time as _time
    import tty

    nodes = _keyboard_event_devices()
    fds = [fd for _, fd in nodes]
    print(f"recording from {len(fds)} evdev device(s)")
    print("type your keys now (combos work: hold ctrl, tap c)...")
    print("press ESC twice (<0.4s apart) or ctrl+c to finish & save")
    sys.stdout.flush()

    old_attrs = None
    try:
        old_attrs = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin)      # no echo, keep ctrl+c signalling
    except termios.error:
        pass                          # stdin not a tty (piped); record anyway
    try:
        _drain_devices(nodes)
        return _record_loop(nodes, stop_double_esc)
    finally:
        if old_attrs is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_attrs)
        for _, fd in nodes:
            os.close(fd)


def _drain_devices(nodes):
    """Discard anything already queued (prompt keystrokes that landed
    between device open and recording start)."""
    for _, fd in nodes:
        while True:
            try:
                data = os.read(fd, _EV_SIZE)
            except BlockingIOError:
                break
            if len(data) < _EV_SIZE:
                break


def _record_loop(nodes, stop_double_esc):
    import select
    import time as _time

    fds = [fd for _, fd in nodes]
    steps = []
    held = set()
    esc_pairs = []               # (down_step_idx, up_monotonic_time)
    esc_pending = None           # down_step_idx of a lone esc currently held
    t_last = None
    stopped = False
    try:
        while not stopped:
            ready, _, _ = select.select(fds, [], [], 0.2)
            for fd in ready:
                while True:
                    try:
                        data = os.read(fd, _EV_SIZE)
                    except BlockingIOError:
                        break
                    if len(data) < _EV_SIZE:
                        break
                    _, _, etype, code, value = struct.unpack(_EV_FMT, data)
                    if etype != 1 or value > 1:
                        continue
                    hid = _LINUX_KEY_HID.get(code)
                    if hid is None:
                        continue
                    now = _time.monotonic()
                    if value == 1 and hid not in held:
                        if t_last is not None:
                            gap = int((now - t_last) * 1000)
                            if gap > 0:
                                steps.append(("delay", min(gap, 0xFFFF)))
                        t_last = now
                        lone_esc = hid == 0x29 and not held
                        held.add(hid)
                        esc_pending = len(steps) if lone_esc else None
                        steps.append(("down", hid))
                    elif value == 0 and hid in held:
                        # releases of keys pressed before recording started
                        # (e.g. the enter that confirmed the prompt) are ignored
                        if t_last is not None:
                            gap = int((now - t_last) * 1000)
                            if gap > 0:
                                steps.append(("delay", min(gap, 0xFFFF)))
                        t_last = now
                        held.discard(hid)
                        steps.append(("up", hid))
                        if hid == 0x29 and stop_double_esc and not held:
                            if esc_pending is not None:
                                if esc_pairs and now - esc_pairs[-1][1] < 0.4:
                                    stopped = True
                                    break
                                esc_pairs.append((esc_pending, now))
                            esc_pending = None
                    else:
                        continue
                    print(f"\r  {len(steps):4d} steps   "
                          f"{'+' if value else '-'}{_hid_key_name(hid):12s}",
                          end="", flush=True)
            if stopped:
                break
    except KeyboardInterrupt:
        # ctrl+c = finish & save, but discard the ctrl+c gesture itself:
        # strip the trailing contiguous run of down events
        print()
        j = len(steps)
        removed_down = False
        while j > 0:
            action, val = steps[j - 1]
            if action == "down":
                held.discard(val)
                j -= 1
                removed_down = True
            elif action == "delay" and removed_down:
                j -= 1
                if j > 0 and steps[j - 1][0] != "down":
                    break
            else:
                break
        del steps[j:]
        for hid in sorted(held):
            steps.append(("up", hid))   # close keys still held so nothing sticks
    print()
    if stop_double_esc:
        # walk back over trailing esc pairs; keep stripping while the
        # gap between consecutive esc-ups is <400ms (an esc mash), so a
        # real content-esc more than 400ms earlier is preserved
        cut = len(steps)
        times = [t for _, t in esc_pairs]
        n = 0                       # pairs to strip
        while n < len(esc_pairs):
            pair_down = min(esc_pairs[-1 - n][0], len(steps))
            if n > 0 and times[-1 - n + 1] - times[-1 - n] >= 0.4:
                break               # gap too big: older esc is content
            cut = pair_down
            while cut > 0 and steps[cut - 1][0] == "delay":
                cut -= 1
            n += 1
        del steps[cut:]
    return steps


def cmd_macro_record(args):
    if not args.name:
        _fail("macro record requires a name")
    path = _macro_path(args.name)
    if os.path.exists(path) and not args.force:
        _fail(f"macro '{args.name}' already exists; use --force to overwrite")
    try:
        steps = _record_keyboard_steps()
    except RuntimeError as err:
        _fail(str(err))
    if not steps:
        _fail("nothing recorded")
    os.makedirs(MACRO_DIR, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("# recorded from keyboard\n")
        fh.write(_steps_to_macro_text(steps))
    data = protocol.encode_macro_steps(steps)
    frames = protocol.build_macro_frames(1, steps)
    print(f"\nsaved: {path}")
    print(f"  {len(steps)} steps, {len(data)} wire bytes, "
          f"{len(frames) - 1} A8 frame(s)")
    if len(data) > 993:
        print("  WARNING: step stream exceeds 993 bytes; "
              "device may truncate — split the macro")
    print(f"\nbind it: x17blake keys bind <button> --macro-file {path}")
    return 0


def _steps_to_macro_text(steps):
    """Render steps back into .macro text (used by macro import)."""
    lines = []
    i = 0
    while i < len(steps):
        action, value = steps[i]
        if action == "delay":
            lines.append(f"delay {value}")
            i += 1
            continue
        # collect a run of downs (possible combo) followed by matching ups
        downs = []
        while i < len(steps) and steps[i][0] == "down":
            downs.append(steps[i][1])
            i += 1
        ups = []
        while i < len(steps) and steps[i][0] == "up":
            ups.append(steps[i][1])
            i += 1
        if downs and ups and sorted(downs) == sorted(ups):
            names = "+".join(_hid_key_name(c) for c in downs)
            lines.append(f"press {names}")
        elif downs or ups:
            for c in downs:
                lines.append(f"down {_hid_key_name(c)}")
            for c in ups:
                lines.append(f"up {_hid_key_name(c)}")
    return "\n".join(lines) + "\n"


def _interactive_macro_builder(name):
    """Interactive CLI macro builder. Returns .macro file content."""
    print(f"=== Macro Builder: {name} ===")
    print("Commands:")
    print("  tap <key> [delay_ms]         key press+release (default 30ms)")
    print("  press <key1>+<key2>+... [ms] combo (e.g. press ctrl+c)")
    print("  down <key>                   key down")
    print("  up <key>                     key up")
    print("  delay <ms>                   pause")
    print("  done                         finish and save")
    print("  cancel                       abort")
    print()
    print("Available keys: " + ", ".join(sorted(protocol.HID_KEYBOARD_KEYS.keys())))
    print()

    lines = [f"# Macro: {name}"]
    step_count = 0

    while True:
        try:
            raw = input(f"[{step_count}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\ncancelled")
            raise SystemExit(1)

        if not raw or raw.startswith("#"):
            continue
        if raw.lower() == "cancel":
            print("cancelled")
            raise SystemExit(1)
        if raw.lower() == "done":
            if step_count == 0:
                print("  (no steps added, nothing to save)")
                raise SystemExit(1)
            break

        # Validate by parsing
        parts = raw.split()
        cmd = parts[0].lower()
        try:
            if cmd == "tap" and len(parts) >= 2:
                protocol.hid_keyboard_code(parts[1])
            elif cmd == "press" and len(parts) >= 2:
                for k in parts[1].split("+"):
                    protocol.hid_keyboard_code(k)
            elif cmd == "down" and len(parts) == 2:
                protocol.hid_keyboard_code(parts[1])
            elif cmd == "up" and len(parts) == 2:
                protocol.hid_keyboard_code(parts[1])
            elif cmd == "delay" and len(parts) == 2:
                int(parts[1])
            else:
                print(f"  unknown command: {raw}")
                continue
        except (ValueError, KeyError) as err:
            print(f"  error: {err}")
            continue

        lines.append(raw)
        step_count += 1
        print(f"  added: {raw}")

    return "\n".join(lines) + "\n"


def cmd_reset(args):
    frame = protocol.build_factory_reset()
    print("about to send factory-reset frame:")
    print(protocol.format_hexdump(frame))
    if not args.yes:
        print("dry run; add --yes to send")
        return 0
    with Device() as dev:
        port = dev._port
        port.exchange(frame)
        time.sleep(0.2)
        state = dev.read()
    _show_pretty(state)
    print("reset sent. Now UNPLUG the mouse, wait 5s, replug, then test "
          "back button / scroll-down / lighting.")
    return 0


class FriendlyParser(argparse.ArgumentParser):
    def error(self, message):
        m = re.search(r"invalid choice: '([^']+)' \(choose from ([^)]+)\)", message)
        if m:
            bad = m.group(1)
            options = re.findall(r"'([^']+)'", m.group(2))
            close = difflib.get_close_matches(bad, options, n=1, cutoff=0.4)
            if close:
                print(f"error: invalid choice '{bad}' — did you mean '{close[0]}'?")
                raise SystemExit(2)
        super().error(message)


_RAW = argparse.RawDescriptionHelpFormatter


def main(argv=None):
    parser = FriendlyParser(
        prog="x17blake",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Fantech X17 Blake (Wings Tech 2ea8:2203) Linux configurator\n\n"
            "Buttons, DPI, polling rate, lighting and presets\n"
            "straight over hidraw, no vendor software needed."
        ),
        epilog=(
            "examples:\n"
            "  x17blake show                              current state (--json for scripts)\n"
            "  x17blake dpi 1600                          set ACTIVE stage dpi\n"
            "  x17blake stage 3 2000                      set stage 1-7 individually\n"
            "  x17blake polling 500                       set polling rate\n"
            "  x17blake led chroma --brightness 4         rainbow mode\n"
            "  x17blake led steady --color FF0000         solid red\n"
            "  x17blake led off                           lights out\n"
            "  x17blake keys                              show button bindings\n"
            "  x17blake keys bind forward --key b         Forward types 'b'\n"
            "  x17blake keys bind back --special mute     Back toggles mute\n"
            "  x17blake keys clear --all                  factory button behavior\n"
            "  x17blake macro create my-combo             interactive macro builder\n"
            "  x17blake keys bind dpi_minus --macro-file ~/.config/x17blake/macros/my-combo.macro\n"
            "  x17blake preset save daily                 snapshot everything\n"
            "  x17blake reset --yes                       factory reset (recovery)\n"
            "\n"
            "every mutating command auto-backups first and refuses to write\n"
            "fields that are not verified-safe; see also PROTOCOL.md and\n"
            "tools/explore_bindings.py for protocol research."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser(
        "tui", help="experimental terminal UI",
        description="Curses UI for key assignment, DPI stages and "
                    "lighting. Testing build; every write uses the same "
                    "guarded paths as the CLI (auto-backup included).")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("help", help="show help (optionally for a command)")
    p.add_argument("topic", nargs="?", metavar="COMMAND",
                   help="print detailed help for COMMAND")
    p.set_defaults(func=None)

    p = sub.add_parser("info", help="list matching hidraw nodes")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser(
        "show", help="pretty-print current settings",
        description="Reads the device settings frame and renders it "
                    "(or dumps JSON with --json). Read-only.")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser(
        "probe", help="raw debug dump of the settings frame",
        description="Hexdump of the live settings frame; with --roundtrip "
                    "also writes the identical frame back and verifies "
                    "nothing changed (transport sanity check).")
    p.add_argument("--roundtrip", action="store_true",
                   help="write-read-verify identity of the settings frame")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser(
        "dpi", help="set dpi of the ACTIVE stage",
        description="Sets both axes of the active DPI stage. Valid values: "
                    "200..10000 in steps of 100 (sensor table).")
    p.add_argument("dpi", type=int, metavar="DPI")
    p.set_defaults(func=cmd_dpi)

    p = sub.add_parser(
        "stage", help="set dpi of a specific stage",
        description="Configures one of the seven hardware stages without "
                    "switching to it.")
    p.add_argument("index", type=int, metavar="1-7")
    p.add_argument("dpi", type=int, metavar="DPI")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser(
        "led", formatter_class=_RAW, help="lighting control (Blake-native modes)",
        description=(
            "Modes: chroma (rainbow cycle), neon, custom_breathe, breathe, "
            "tail, steady (solid palette color), off. Pass a mode name or "
            "its numeric id 0-6.\n"
            "Brightness 0-4 is the real dimmer; hex colors are effectively "
            "ON/OFF per channel on this firmware."),
        epilog=(
            "examples:\n"
            "  x17blake led tail --brightness 3\n"
            "  x17blake led steady --color 00FF00\n"
            "  x17blake led custom_breathe --speed 1"))
    p.add_argument("effect", nargs="?", metavar="MODE",
                   help="chroma, neon, custom_breathe, breathe, tail, off, steady")
    p.add_argument("--brightness", type=int, choices=range(0, 5), metavar="0-4")
    p.add_argument("--speed", type=int, choices=range(0, 3), metavar="0-2",
                   help="animation speed (0 = slowest, 2 = fastest)")
    p.add_argument("--color", metavar="RRGGBB", help="paint all 7 color slots")
    p.set_defaults(func=cmd_led)

    p = sub.add_parser("polling", help="polling rate (Hz)",
                        description="Sets the USB polling rate. Factory default is 1000 Hz.")
    p.add_argument("hz", type=int, choices=(125, 250, 500, 1000), metavar="125|250|500|1000")
    p.set_defaults(func=cmd_polling)

    p = sub.add_parser(
        "keys", formatter_class=_RAW,
        help="button remapping (show / bind / clear)",
        description=(
            "Bind any button (including left/right/middle) to keyboard "
            "keys, built-in functions or mouse actions. All button slots "
            "are verified; the device never reports bindings back, so "
            "state is tracked locally (~/.config/x17blake/bindings.json)."),
        epilog=(
            "examples:\n"
            "  x17blake keys bind forward --key b        Forward types 'b'\n"
            "  x17blake keys bind back --special mute    Back toggles mute\n"
            "  x17blake keys bind dpi_minus --special left_click\n"
            "  x17blake keys bind left --special right_click   swap L/R\n"
            "  x17blake keys clear --all                 factory behavior\n"
            "\n"
            "valid targets are listed under each flag above; typos get\n"
            "\"did you mean\" suggestions.\n"
            "\n"
            "caution: rebinding LEFT to a non-click function is safe only\n"
            "if you can still reach a terminal; `x17blake keys clear --all`\n"
            "restores everything (keyboard input suffices)."))
    p.add_argument("action", nargs="?", choices=("show", "bind", "clear"),
                   default="show")
    p.add_argument("slot", nargs="*", metavar="SLOT",
                   help="left | right | middle | back | forward | dpi_minus | dpi_plus")
    p.add_argument("--key", metavar="KEY", choices=protocol.KEYBOARD_KEY_NAMES,
                   help="keyboard target; one of: "
                        + ", ".join(protocol.KEYBOARD_KEY_NAMES)
                        + " (raw ids: --hid 0xNN)")
    p.add_argument("--macro", metavar="ID", type=int, help="assign built-in macro ID to the slot")
    p.add_argument("--macro-file", metavar="FILE", help="load macro from .macro text file")
    p.add_argument("--special", metavar="FN",
                   choices=sorted(protocol.SPECIAL_FUNCTION_TAGS),
                   help="built-in function; one of: "
                        + ", ".join(sorted(protocol.SPECIAL_FUNCTION_TAGS)))
    p.add_argument("--mouse", metavar="BUTTON",
                   help="not yet decodable on the wire; rejected with an explanation")
    p.add_argument("--hid", metavar="0xNN", help="raw HID usage id")
    p.add_argument("--experimental", action="store_true",
                   help="allow slots whose physical button is not yet mapped")
    p.add_argument("--all", action="store_true", help="clear every binding")
    p.add_argument("--json", action="store_true", help="machine-readable show output")
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("backup", help="snapshot current device state")
    p.add_argument("label", nargs="?", default="manual")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser(
        "restore", help="apply a saved backup",
        description="Diffs the backup against the device first; without "
                    "--yes it is a dry run.")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--yes", action="store_true", help="actually write (default: dry run)")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser(
        "preset", help="list / save / apply named presets",
        description="Full-state snapshots stored as JSON (device frame plus "
                    "button bindings). Bundled: initial-factory.")
    p.add_argument("action", choices=("list", "save", "apply"))
    p.add_argument("name", nargs="?", help="preset name")
    p.add_argument("-d", "--description", help="note stored with preset save")
    p.add_argument("--yes", action="store_true", help="apply without dry run")
    p.set_defaults(func=cmd_preset)

    p = sub.add_parser(
        "macro", formatter_class=_RAW,
        help="create / list / manage macro files",
        description=(
            "Create and manage .macro text files that define key sequences.\n"
            "Use 'x17blake macro create <name>' for interactive builder,\n"
            "then bind with 'x17blake keys bind <button> --macro-file <path>'."),
        epilog=(
            "examples:\n"
            "  x17blake macro list                       show saved macros\n"
            "  x17blake macro create my-combo            interactive builder\n"
            "  x17blake macro record my-combo            record real keystrokes\n"
            "                                            (esc esc = stop)\n"
            "  x17blake macro import x.mly               import Windows .mly macro\n"
            "  x17blake macro show my-combo              print macro file\n"
            "  x17blake macro compile my-combo           show wire encoding\n"
            "  x17blake macro delete my-combo            remove macro file\n"))
    p.add_argument("action", nargs="?",
                   choices=("list", "create", "show", "delete", "compile",
                            "import", "record"),
                   default="list")
    p.add_argument("name", nargs="?", metavar="NAME", help="macro name")
    p.add_argument("--force", action="store_true", help="overwrite existing macro")
    p.add_argument("--file", metavar="PATH", help="path for compile (instead of name)")
    p.set_defaults(func=cmd_macro)

    p = sub.add_parser(
        "reset", help="factory reset (recovery path)",
        description="Sends the vendor restore frame. Follow with an "
                    "unplug/replug. Use when lighting or bindings misbehave.")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_reset)

    def _cmd_help(args):
        if args.topic:
            target = sub.choices.get(args.topic)
            if target is None:
                parser.error(
                    f"unknown command '{args.topic}' (choose from "
                    f"{', '.join(c for c in sub.choices if c != 'help')})")
            target.print_help()
        else:
            parser.print_help()
        return 0

    sub.choices["help"].set_defaults(func=_cmd_help)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except SafetyError as err:
        print(f"safety: {err}")
        return 4
    except DeviceError as err:
        print(f"error: {err}")
        return 1
    except OSError as err:
        print(f"error: {err}")
        print(
            "hint: run `sudo ./install.sh` from the repo, or copy "
            "udev/70-x17blake.rules to /etc/udev/rules.d/ (see README; "
            "immutable distros: /etc, never /usr/lib)"
        )
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
