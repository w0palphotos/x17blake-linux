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
    save_backup,
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
    lod = s["lift_off_distance_ui"]
    print(f"  lift-off  : {lod if lod else s['lift_off_distance_raw']}")
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
        dev._port.exchange(protocol.build_commit())
        time.sleep(0.05)
        state = dev.read()
    print(f"{what}: applied")
    _show_pretty(state)
    return 0


def cmd_lod(args):
    with Device() as dev:

        def mut(f):
            protocol.set_lift_off_distance(f, args.level)

        state = _mutate_and_apply(dev, mut, f"lift-off distance -> {args.level}")
        raw = state[33]
        ok = raw == args.level + 1
        print(f"verified: lift-off = {raw - 1 if raw >= 2 else raw}")
        return 0 if ok else 3



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
    dev._port.exchange(protocol.build_commit())
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
                print(f"error: unknown command '{bad}' — did you mean '{close[0]}'?")
                raise SystemExit(2)
        super().error(message)


def main(argv=None):
    parser = FriendlyParser(
        prog="x17blake",
        description="Fantech X17 Blake (Wings Tech 2ea8:2203) configurator",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("info", help="list matching hidraw nodes")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("show", help="pretty-print current settings")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("probe", help="raw debug dump of the settings frame")
    p.add_argument("--roundtrip", action="store_true")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("dpi", help="set dpi of the ACTIVE stage")
    p.add_argument("dpi", type=int, metavar="DPI")
    p.set_defaults(func=cmd_dpi)

    p = sub.add_parser("stage", help="set dpi of a specific stage")
    p.add_argument("index", type=int, metavar="1-7")
    p.add_argument("dpi", type=int, metavar="DPI")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("led", help="lighting control (Blake-native modes)")
    p.add_argument("effect", nargs="?", metavar="MODE",
                   help="chroma, neon, custom_breathe, breathe, tail, off, steady")
    p.add_argument("--brightness", type=int, choices=range(0, 5), metavar="0-4")
    p.add_argument("--speed", type=int, choices=range(0, 3), metavar="0-2")
    p.add_argument("--color", metavar="RRGGBB", help="paint all 7 color slots")
    p.set_defaults(func=cmd_led)

    p = sub.add_parser("lod", help="lift-off distance")
    p.add_argument("level", type=int, choices=(1, 2, 3), metavar="1-3")
    p.set_defaults(func=cmd_lod)

    p = sub.add_parser("backup", help="snapshot current device state")
    p.add_argument("label", nargs="?", default="manual")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore", help="apply a saved backup")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--yes", action="store_true", help="actually write (default: dry run)")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("preset", help="list / save / apply named presets")
    p.add_argument("action", choices=("list", "save", "apply"))
    p.add_argument("name", nargs="?", help="preset name")
    p.add_argument("-d", "--description", help="note stored with preset save")
    p.add_argument("--yes", action="store_true", help="apply without dry run")
    p.set_defaults(func=cmd_preset)

    p = sub.add_parser("reset", help="factory reset (not yet available)")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
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
