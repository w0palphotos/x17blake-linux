"""Linux-side binding explorer — decodes button functions without the VM.

Two modes:

  --single HEX5   Bisect without presses: write ONE record into the
                  verified forward slot, wait, and report whether the
                  firmware survives it (some records reboot the MCU —
                  e.g. polling/profile changes re-enumerate the device).

  --round NAME    Apply a batch of candidates across all five slots,
                  then press your customizable buttons once each; every
                  press is correlated across three channels (config-
                  channel echo, boot-mouse reports, settings deltas).

Every application auto-backups; previous bindings are restored at the
end unless --keep is given.
"""

import argparse
import json
import os
import select
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from x17blake import hidraw, protocol, state  # noqa: E402

STATE_DIR = state.STATE_DIR
LOG_PATH = os.path.join(STATE_DIR, "explore-log.json")
BINDINGS_PATH = os.path.join(STATE_DIR, "bindings.json")

SLOT_ORDER = [27, 22, 42, 47, 57]

ROUNDS = {
    "relocate": [
        "9000000000",
        "9200000000",
        "b500000000",
        "b600000000",
        "c800000000",
    ],
    "cls-02-06": [
        "fc02130000",
        "fc03130000",
        "fc04130000",
        "fc05130000",
        "fc06130000",
    ],
    "cls-07-0b": [
        "fc07130000",
        "fc08130000",
        "fc09130000",
        "fc0a130000",
        "fc0b130000",
    ],
    "cls-0c-10": [
        "fc0c130000",
        "fc0d130000",
        "fc0e130000",
        "fc0f130000",
        "fc10130000",
    ],
    "misc": [
        "f301000100",
        "fc01140000",
        "fc00130000",
        "fc00ae0000",
        "fc00a80000",
    ],
}

ROUND_ORDER = ["relocate", "cls-02-06", "cls-07-0b", "cls-0c-10", "misc"]

BTN_NAMES = {0x01: "LEFT-click", 0x02: "RIGHT-click", 0x04: "MIDDLE-click"}


# --- resilient transport ------------------------------------------------

class Link:
    """Config-channel link that survives device re-enumeration."""

    def __init__(self):
        self.port = None

    def _reopen(self):
        try:
            if self.port:
                self.port.close()
        except OSError:
            pass
        self.port = None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                self.port = hidraw.open_config_interface(interface=1)
                self.port.open()
                return True
            except FileNotFoundError:
                time.sleep(0.7)
        raise SystemExit("device did not come back within 15s")

    def open(self):
        self._reopen()

    def close(self):
        if self.port:
            try:
                self.port.close()
            except OSError:
                pass

    def exchange(self, frame, attempts=3):
        for i in range(attempts):
            try:
                return self.port.exchange(frame)
            except OSError:
                if i == attempts - 1:
                    raise
                print("   (device dropped — waiting for re-enumeration ...)",
                      flush=True)
                self._reopen()

    def get_settings(self, attempts=3):
        packets = self.exchange(protocol.build_get_settings(), attempts)
        return protocol.settings_from_packets(packets)

    def read_notify(self, timeout):
        try:
            ready = select.select([self.port._fd], [], [], timeout)[0]
            if not ready:
                return None
            return os.read(self.port._fd, 64)
        except OSError:
            return None


def load_tracked_entries():
    try:
        with open(BINDINGS_PATH) as fh:
            return [e for e in json.load(fh) if isinstance(e, dict)]
    except FileNotFoundError:
        return []


def entries_to_table(entries):
    class_map = {
        "keyboard": protocol.KEY_CLASS_KEYBOARD,
        "keyboard_ctrl": protocol.KEY_CLASS_KEYBOARD_CTRL,
    }
    table = {}
    for e in entries:
        cls = class_map.get(e.get("class"))
        if cls is None:
            raise SystemExit(f"unknown stored binding class {e.get('class')!r}")
        table[int(e["slot"])] = protocol.encode_binding(cls, int(e["code"]))
    return table


def apply_table(link, table):
    current = link.get_settings()
    if current is None:
        raise SystemExit("no GET response")
    state.save_backup(current, label="explore-pre")
    out = bytearray(current)
    out[3] = protocol.CMD_SET_SETTINGS
    link.exchange(bytes(out))
    link.exchange(protocol.build_commit(table))
    time.sleep(0.05)


def open_boot_mouse():
    nodes = hidraw.find_hidraw(interface=0)
    if not nodes:
        return None
    return os.open(nodes[0][1], os.O_RDONLY | os.O_NONBLOCK)


def drain_ep1(fd, window):
    events = []
    deadline = time.time() + window
    quiet = 0.35
    last = time.time()
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            if events and time.time() - last >= quiet:
                break
            continue
        try:
            data = os.read(fd, 16)
        except BlockingIOError:
            continue
        except OSError:
            break
        if data:
            events.append(bytes(data))
            last = time.time()
    return events


def summarize_ep1(events):
    notes = []
    for d in events:
        if len(d) < 4:
            continue
        btns = d[0] & 0x07
        if btns:
            notes.append("+".join(BTN_NAMES[b] for b in (1, 2, 4) if btns & b))
        if d[3]:
            notes.append("WHEEL-" + ("down" if d[3] > 0x7F else "up"))
    seen = []
    for n in notes:
        if n not in seen:
            seen.append(n)
    return seen


def wait_presses(link, count, deadline_s, ep1_fd):
    results = []
    deadline = time.time() + deadline_s
    while len(results) < count and time.time() < deadline:
        pkt = link.read_notify(timeout=0.4)
        if not pkt or pkt[0] != 0x01:
            continue
        rec = protocol.parse_notify(pkt)
        if rec is None:
            continue
        events = drain_ep1(ep1_fd, 1.1) if ep1_fd is not None else []
        results.append({"echo": rec, "ep1": [d.hex() for d in events]})
        remaining = count - len(results)
        if remaining:
            print(f"   captured {len(results)}/{count} — keep going...",
                  flush=True)
    return results


def describe(result):
    echo = result["echo"]
    label = f"{echo.get('name', '?')} [{echo.get('class', '?')}]"
    effects = summarize_ep1([bytes.fromhex(h) for h in result["ep1"]])
    eff = ", ".join(effects) if effects else "(no boot-mouse activity)"
    return f"{label:24s} -> {eff}"


def interesting_delta(before, after):
    if not before or not after or before == after:
        return {}
    fields = {}
    if before[7] != after[7]:
        fields["active_stage"] = f"{before[7]}->{after[7]}"
    if before[33] != after[33]:
        fields["lod"] = f"{before[33]}->{after[33]}"
    if before[40] != after[40]:
        fields["profile"] = f"{before[40]}->{after[40]}"
    return fields


def log_round(entry):
    os.makedirs(STATE_DIR, exist_ok=True)
    log = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH) as fh:
                log = json.load(fh)
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    with open(LOG_PATH, "w") as fh:
        json.dump(log, fh, indent=2)
        fh.write("\n")


def run_round(link, name, records, ep1_fd, deadline_s):
    print(f"\n=== ROUND '{name}' ===", flush=True)
    print("candidates:",
          ", ".join(r[:2] + "/" + r[2:4] for r in records), flush=True)
    before_frame = link.get_settings()
    apply_table(link, dict(zip(SLOT_ORDER, [bytes.fromhex(r) for r in records])))
    time.sleep(0.4)  # give a would-be re-enumeration a chance to surface
    if link.get_settings() is None:
        print("   !! device vanished right after apply — batch crashed it",
              flush=True)
    print(f"applied. Press each customizable button ONCE "
          f"({len(records)} presses, ~1s apart).\n", flush=True)
    results = wait_presses(link, len(records), deadline_s, ep1_fd)
    after = link.get_settings()
    deltas = interesting_delta(before_frame, after or b"")
    for res in results:
        print("  " + describe(res), flush=True)
    if deltas:
        print(f"  settings deltas: {deltas}", flush=True)
    missing = len(records) - len(results)
    if missing:
        print(f"  ({missing} press(es) not received)", flush=True)
    log_round({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "round",
        "round": name,
        "records": dict(zip(map(str, SLOT_ORDER[:len(records)]), records)),
        "results": results,
        "settings_deltas": deltas,
    })


def run_single(link, hex_record, slot=27, wait_s=2.5):
    record = bytes.fromhex(hex_record)
    print(f"\n=== SINGLE {hex_record} -> slot {slot} ===", flush=True)
    apply_table(link, {slot: record})
    print(f"written; waiting {wait_s}s to see if the firmware keeps running ...",
          flush=True)
    time.sleep(wait_s)
    alive = link.get_settings() is not None
    verdict = "SURVIVED" if alive else "CRASHED the MCU (device re-enumerated)"
    print(f"verdict: {verdict}", flush=True)
    log_round({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "single",
        "record": hex_record,
        "slot": slot,
        "survived": alive,
    })
    return alive


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", action="append", choices=list(ROUNDS),
                    help="batch round(s) to run")
    ap.add_argument("--single", metavar="HEX5", nargs="+",
                    help="bisect one or more 5-byte records (no presses needed)")
    ap.add_argument("--slot", type=int, default=27,
                    help="target slot for --single (default 27)")
    ap.add_argument("--keep", action="store_true",
                    help="leave the last batch applied afterwards")
    ap.add_argument("--deadline", type=int, default=150,
                    help="seconds to wait for presses per round")
    args = ap.parse_args()
    if not args.single and not args.round:
        ap.error("choose --single HEX5 or --round NAME")

    link = Link()
    link.open()
    ep1_fd = open_boot_mouse()
    try:
        if args.single:
            for record in args.single:
                run_single(link, record, slot=args.slot)
                time.sleep(0.4)
        for name in args.round or []:
            run_round(link, name, ROUNDS[name], ep1_fd, args.deadline)
    finally:
        if not args.keep:
            print("\nrestoring empty binding table ...", flush=True)
            try:
                apply_table(link, {})
                entries = load_tracked_entries()
                if entries:
                    apply_table(link, entries_to_table(entries))
                print("done.", flush=True)
            except SystemExit:
                print("warning: could not restore — run "
                      "`python3 -m x17blake keys clear --all` when the "
                      "mouse is back", flush=True)
        link.close()
        if ep1_fd is not None:
            os.close(ep1_fd)


if __name__ == "__main__":
    main()
