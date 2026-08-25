"""One-shot binding-slot mapper.

Writes a distinct keyboard key into every candidate binding slot, then
asks you to press each physical mouse button once. Button-press
notifications on the config channel echo the binding code, which
reveals which slot belongs to which button — replacing dozens of
one-by-one Windows capture segments with a single ~1-minute session.

Phase 1 (default) probes free slots 42/47/57 plus verified controls.
Phase 2 (--with-residents) additionally overwrites the permanent slot
residents b5/b6/c8 (offsets 32/37/52) — these may carry lighting
parameters; a factory reset restores them if anything misbehaves.

Usage:
    python3 tools/probe_slots.py [--with-residents]

Run from a terminal; letters produced by remapped buttons will simply
type into it (harmless).
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from x17blake import hidraw, protocol, state  # noqa: E402

STATE_DIR = state.STATE_DIR
SLOTMAP_PATH = os.path.join(STATE_DIR, "slotmap.json")
BINDINGS_PATH = os.path.join(STATE_DIR, "bindings.json")

PHYSICAL_BUTTONS = [
    "left",
    "right",
    "middle",
    "forward",
    "back",
    "dpi_up",
    "dpi_down",
    "scroll_up",
    "scroll_down",
    "fire",
]

# slot offset -> probe key (control slots first for pipeline validation)
PROBE_PHASE1 = {
    27: "j",   # forward (verified control)
    22: "h",   # back (verified control)
    42: "p",
    47: "o",
    57: "i",   # never observed nonzero in any capture
}
PROBE_RESIDENTS = {
    32: "u",
    37: "y",
    52: "t",
}


def write_probe_table(port, table):
    current = protocol.settings_from_packets(
        port.exchange(protocol.build_get_settings())
    )
    if current is None:
        raise SystemExit("no GET response; check device and permissions")
    state.save_backup(current, label="auto-preprobe")
    out = bytearray(current)
    out[3] = protocol.CMD_SET_SETTINGS
    port.exchange(bytes(out))
    port.exchange(protocol.build_commit(table))
    time.sleep(0.05)


def read_notify(port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        pkt = port.read_input_report(timeout=max(0.05, deadline - time.time()))
        if not pkt:
            continue
        if pkt[0] == 0x01 and len(pkt) >= 4:
            return protocol.parse_notify(pkt)
        # settings echoes (04 ...) are noise here
    return None


def main():
    with_residents = "--with-residents" in sys.argv
    table = dict(PROBE_PHASE1)
    if with_residents:
        table.update(PROBE_RESIDENTS)

    records = {
        off: protocol.encode_binding(protocol.KEY_CLASS_KEYBOARD,
                                     protocol.hid_keyboard_code(key))
        for off, key in table.items()
    }
    letter_to_slot = {key: off for off, key in table.items()}

    print("probe table (slot -> temporary key):")
    for off in sorted(records):
        label = protocol.SLOT_NAMES.get(off, "?")
        star = "" if off in protocol.VERIFIED_SLOTS else " *"
        print(f"  {off:3d} ({label}){star} -> '{table[off]}'")
    if with_residents:
        print("  WARNING: --with-residents overwrites b5/b6/c8 residents")
    print()

    port = hidraw.open_config_interface(interface=1)
    port.open()
    try:
        port.exchange(protocol.build_frame(0x00))  # vendor session opener
        write_probe_table(port, records)
        print("probe bindings applied. Previous bindings will be restored at the end.\n")

        mapping = {}
        pending = list(PHYSICAL_BUTTONS)
        while pending:
            btn = pending[0]
            try:
                answer = input(f"press [{btn}] once (s=skip, q=quit): ").strip().lower()
            except EOFError:
                break
            if answer == "q":
                break
            if answer == "s":
                pending.pop(0)
                continue
            notify = read_notify(port, 4.0)
            if notify is None:
                print("  (no notify received — nothing mapped?)")
                continue
            code = notify["code"]
            hit = [off for off, rec in records.items() if rec[2] == code]
            name = ""
            if notify["class"] in ("keyboard", "keyboard_ctrl"):
                name = notify["name"]
            else:
                name = f"{notify['class']}:{code:#04x}"
            if len(hit) == 1:
                off = hit[0]
                mapping[btn] = {"slot": off, "echo": name}
                print(f"  -> echo '{name}' => slot {off} "
                      f"({protocol.SLOT_NAMES.get(off, '?')})")
            else:
                print(f"  -> echo '{name}' matches slots {hit}; ambiguous")
            pending.pop(0)

        print("\n=== RESULT ===")
        reverse = {}
        for btn, info in mapping.items():
            reverse.setdefault(info["slot"], []).append(btn)
        for off in sorted(records):
            btns = reverse.get(off, [])
            known = "KNOWN" if off in protocol.VERIFIED_SLOTS else "NEW"
            print(f"  slot {off:3d} ('{table[off]}') : {', '.join(btns) or '(unidentified)'}"
                  f"   [{known}]")
        print("\ncheat-sheet if a button typed instead of notifying:")
        for off, key in sorted(table.items()):
            print(f"  '{key}' came from slot {off}")

        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(SLOTMAP_PATH, "w") as fh:
                json.dump(mapping, fh, indent=2)
                fh.write("\n")
            print(f"\nsaved: {SLOTMAP_PATH}")
        except OSError as err:
            print(f"(could not save slotmap: {err})")
    finally:
        print("\nrestoring previous bindings ...")
        write_probe_table(port, state.binding_table(state.load_binding_entries()))
        port.close()
        print("done.")


if __name__ == "__main__":
    main()
