"""Macro live-test harness.

Watches the mouse's keyboard interface (hidraw, interface 0) and
prints every HID key report it emits. Used to verify what a macro
actually types: run this, press the macro button, compare output.

Usage:
    python3 tools/macro_monitor.py [timeout_seconds]
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from x17blake import hidraw, protocol  # noqa: E402

MODIFIERS = {
    0x01: "LCtrl", 0x02: "LShift", 0x04: "LAlt", 0x08: "LGui",
    0x10: "RCtrl", 0x20: "RShift", 0x40: "RAlt", 0x80: "RGui",
}


def decode_report(pkt):
    if len(pkt) < 8 or pkt[0] != 0x01:
        return None
    mods = pkt[1]
    keys = [k for k in pkt[3:9] if k]
    return mods, keys


def main():
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    nodes = hidraw.find_hidraw(interface=0)
    if not nodes:
        raise SystemExit("no keyboard interface hidraw node found")
    path = nodes[0][1]
    print(f"watching {path} for {timeout:.0f}s — press the macro button now")
    fd = os.open(path, os.O_RDONLY)
    deadline = time.time() + timeout
    last = None
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            pkt = os.read(fd, 64)
            decoded = decode_report(pkt)
            if decoded is None:
                continue
            mods, keys = decoded
            if (mods, keys) == last:
                continue  # skip key-repeat echoes
            last = (mods, keys)
            mod_names = [n for bit, n in MODIFIERS.items() if mods & bit]
            key_names = [protocol.keyboard_code_name(k) for k in keys]
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] mods={mod_names} keys={key_names}")
    finally:
        os.close(fd)
        print("done")


if __name__ == "__main__":
    import select
    main()
