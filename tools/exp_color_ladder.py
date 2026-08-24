import time

from x17blake.device import Device
from x17blake import protocol
from x17blake.state import save_backup

PAIRS = [
    ("FF0000", "000000"),
    ("FF0000", "7F0000"),
    ("FF0000", "3F0000"),
    ("00FF00", "007F00"),
    ("0000FF", "00007F"),
    ("FF8000", "FF0000"),
]

FLIPS = 3
HOLD = 2.0


def main():
    with Device() as dev:
        base = bytearray(dev.read())
        save_backup(base, label="color-ladder")
        dev.led_begin_session()
        for pf in protocol.build_led_params(True, 4):
            dev._port.exchange(pf)

        def apply(rgb):
            f = bytearray(base)
            f[37] = protocol.EFFECT_NAMES["steady"]
            f[38] = 2
            f[39] = 4
            f[40] = 1
            f[41] = protocol.COLOR_SLOTS_ALL
            for i in range(1, 8):
                protocol.set_stage_color(f, i, bytes.fromhex(rgb))
            out = bytearray(f)
            out[3] = protocol.CMD_SET_SETTINGS
            dev._port.exchange(bytes(out))
            dev._port.exchange(protocol.build_commit())

        for i, (a, b) in enumerate(PAIRS, 1):
            print(f">>> PAIR {i}/6: {a} <-> {b}", flush=True)
            for _ in range(FLIPS):
                for color in (a, b):
                    apply(color)
                    time.sleep(HOLD)
    print(">>> ladder complete")


if __name__ == "__main__":
    main()
