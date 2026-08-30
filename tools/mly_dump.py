"""Debug dump for Fantech .mly macro files (thin wrapper over parse_mly).

The real format lives in x17blake/protocol.py: every byte ROR8(x,2);
events = [vk:u16][flags:u16][delay:u32 ms] @0x6a, 12 bytes each.
"""
import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from x17blake.protocol import parse_mly  # noqa: E402

VK_NAMES = {0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x14: "capslock",
            0x1B: "esc", 0x0D: "enter", 0x08: "backspace", 0x09: "tab",
            0x20: "space", 0x5B: "lwin", 0x5C: "rwin", 0xA0: "lshift",
            0xA1: "rshift", 0xA2: "lctrl", 0xA3: "rctrl", 0xA4: "lalt",
            0xA5: "ralt"}
for i in range(26):
    VK_NAMES[0x41 + i] = chr(ord("A") + i)
for n in range(10):
    VK_NAMES[0x30 + n] = str(n)
for i in range(12):
    VK_NAMES[0x70 + i] = f"F{i+1}"


def main():
    for path in sys.argv[1:]:
        raw = open(path, "rb").read()
        print(f"== {path} ==  (disk magic {raw[:4].hex()})")
        events = parse_mly(path)
        downs = sum(1 for a, _ in events if a == "down")
        print(f"  events: {downs} down / {len(events) - downs} up")
        for i, (action, hid) in enumerate(events):
            if action == "delay":
                print(f"  [{i:3d}] delay {hid}ms")
            else:
                print(f"  [{i:3d}] {action.upper():4s} {hid:#04x}")


if __name__ == "__main__":
    main()
