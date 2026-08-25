import argparse
import difflib
import json
import os
import re
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
USER_PRESET_DIR = os.path.join(STATE_DIR, "presets")
BUNDLED_PRESET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets"
)


EFFECT_NAMES = protocol.EFFECT_NAMES


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
    for iface, node in nodes:
        print(f"{node}  interface={iface}")
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
            _fail("bind requires a slot: forward|back|42|47 [--experimental]")
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
        }[key_class]
        entries.append({"slot": offset, "class": class_name, "code": code, "name": label})

        with Device() as dev:
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
    given = [v for v in (args.key, args.hid, args.special) if v is not None]
    if len(given) != 1:
        _fail("choose exactly one of --key KEY, --special FN, --hid 0xNN")
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
            "  x17blake preset save daily                 snapshot everything\n"
            "  x17blake reset --yes                       factory reset (recovery)\n"
            "\n"
            "every mutating command auto-backups first and refuses to write\n"
            "fields that are not verified-safe; see also PROTOCOL.md and\n"
            "tools/explore_bindings.py for protocol research."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

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
                   help="animation speed (lower = faster)")
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
        print("hint: check udev rule and permissions (/etc/udev/rules.d/70-x17blake.rules)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
