"""Watch both mouse interfaces: config (button press) + keyboard (macro output)."""
import os
import select
import sys
import time

sys.path.insert(0, "/home/w0pal/Projects/x17blake-linux")
from x17blake import hidraw

HID = {0x04 + i: chr(ord("a") + i) for i in range(26)}
HID.update({0xE0: "lctrl", 0xE1: "lshift", 0xE2: "lalt", 0x46: "printscreen",
            0x65: "application", 0x28: "enter", 0x2C: "space"})

cfg = os.open(hidraw.find_hidraw(interface=1)[0][1], os.O_RDONLY | os.O_NONBLOCK)
kbd = os.open(hidraw.find_hidraw(interface=0)[0][1], os.O_RDONLY | os.O_NONBLOCK)
timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 60
deadline = time.time() + timeout
print(f"watching {timeout}s — PRESS DPI- NOW")
last_keys = frozenset()
while time.time() < deadline:
    r, _, _ = select.select([cfg, kbd], [], [], 0.5)
    for fd in r:
        try:
            pkt = os.read(fd, 64)
        except BlockingIOError:
            continue
        if not pkt:
            continue
        which = "CFG " if fd == cfg else "KBD "
        if fd == cfg:
            print(f"{which}{pkt.hex()}")
        else:
            keys = frozenset(pkt[3:9])
            for k in keys - last_keys:
                if k:
                    print(f"KBD  down {HID.get(k, hex(k))}")
            for k in last_keys - keys:
                if k:
                    print(f"KBD  up   {HID.get(k, hex(k))}")
            last_keys = keys
print("done")
