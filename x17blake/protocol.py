REPORT_SIZE = 64

REPORT_ID = 0x04
MSG_TYPE_SETTINGS = 0xA001
CMD_GET_SETTINGS = 0x01
CMD_SET_SETTINGS = 0x02

# Fantech Windows .mly macro export (cracked 2026-08-30 via OemDrv RE).
# Every byte on disk is ROR8(x, 2); decode with ROL2.  Decoded layout:
#   0x00  u32 magic 0xFA3388A0 (the value Add_Macro checks)
#   0x04  u32 unknown (timestamp or checksum)
#   0x14  wchar_t macro name, plain ASCII after decode
#   0x68  u16 = 1 (both samples)
#   0x6a  event array, 12 bytes each, 101 slots to EOF:
#         [vk:u16][flags:u16][delay:u32 ms]
#         flags bit0: 1 = key down, 0 = key up; delay = pause AFTER the event
MLY_MAGIC = 0xFA3388A0
MLY_EVENTS_OFF = 0x6A
MLY_EVENT_COUNT = (1318 - MLY_EVENTS_OFF) // 12


def _rol2(b):
    return ((b << 2) | (b >> 6)) & 0xFF


def _mly_decode(data):
    return bytes(_rol2(b) for b in data)


# VK code -> HID usage
VK_HID = {
    0x08: 0x2A, 0x09: 0x2B, 0x0D: 0x28, 0x10: 0xE1, 0x11: 0xE0, 0x12: 0xE2,
    0x13: 0xE3, 0x14: 0x39, 0x1B: 0x29, 0x20: 0x2C, 0x21: 0x4B, 0x22: 0x4E,
    0x23: 0x4D, 0x24: 0x4A, 0x25: 0x50, 0x26: 0x52, 0x27: 0x4F, 0x28: 0x51,
    0x2C: 0x46, 0x2D: 0x49, 0x2E: 0x4C, 0x5B: 0xE3, 0x5C: 0xE7, 0x5D: 0x65,
    0x60: 0x62, 0x6A: 0x55, 0xFD: 0x58,
    0x6B: 0x57, 0x6D: 0x56, 0x6E: 0x63, 0x6F: 0x54, 0x90: 0x53, 0x91: 0x47,
    0xA0: 0xE1, 0xA1: 0xE5, 0xA2: 0xE0, 0xA3: 0xE4, 0xA4: 0xE2, 0xA5: 0xE6,
    0xBA: 0x33, 0xBB: 0x2E, 0xBC: 0x36, 0xBD: 0x2D, 0xBE: 0x37, 0xBF: 0x38,
    0xC0: 0x35, 0xDB: 0x2F, 0xDC: 0x31, 0xDD: 0x30, 0xDE: 0x34,
}
for _i in range(26):
    VK_HID[0x41 + _i] = 0x04 + _i          # A-Z
for _i in range(1, 10):
    VK_HID[0x30 + _i] = 0x1D + _i          # 1-9
VK_HID[0x30] = 0x27                        # 0
for _i in range(12):
    VK_HID[0x70 + _i] = 0x3A + _i          # F1-F12
for _i in range(1, 10):
    VK_HID[0x60 + _i] = 0x58 + _i          # numpad 1-9
VK_HID[0x60] = 0x62                        # numpad 0


HEADER_MAGIC = bytes([0x01, 0x02, 0xA5])
TRAILER_MAGIC = bytes([0x02, 0x00, 0xA5])

LED_EFFECTS = {
    0: "chroma",
    1: "neon",
    2: "custom_breathe",
    3: "breathe",
    4: "tail",
    5: "off",
    6: "steady",
}

_DPI_SET = [
    200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100,
    1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000, 2100,
    2200, 2300, 2400, 2500, 2600, 2700, 2800, 2900, 3000, 3100,
    3200, 3300, 3400, 3500, 3600, 3700, 3800, 3900, 4000, 4100,
    4200, 4300, 4400, 4500, 4600, 4700, 4800, 4900, 5000, 6000,
    7000, 8000, 9000, 10000,
]

_DPI_HW = [
    0x04, 0x06, 0x08, 0x0B, 0x0D, 0x0F, 0x12, 0x14, 0x16, 0x19,
    0x1B, 0x1D, 0x20, 0x22, 0x24, 0x27, 0x29, 0x2B, 0x2E, 0x30,
    0x32, 0x34, 0x37, 0x39, 0x3B, 0x3E, 0x40, 0x42, 0x45, 0x47,
    0x49, 0x4C, 0x4E, 0x50, 0x53, 0x55, 0x57, 0x5A, 0x5C, 0x5E,
    0x61, 0x63, 0x65, 0x68, 0x6A, 0x6C, 0x6F, 0x71, 0x73, 0x75, 0x77,
    0x79, 0x7B, 0x7D,
]

assert len(_DPI_SET) == len(_DPI_HW)

_DPI_TO_REG = dict(zip(_DPI_SET, _DPI_HW))
_REG_TO_DPI = dict(zip(_DPI_HW, _DPI_SET))


def dpi_supported(dpi):
    return dpi in _DPI_TO_REG


def dpi_to_register(dpi):
    try:
        return _DPI_TO_REG[dpi]
    except KeyError:
        raise ValueError(
            f"unsupported dpi {dpi}; valid: "
            f"{_DPI_SET[0]}..{_DPI_SET[-1]} in steps of 100"
        ) from None


def dpi_from_register(reg):
    return _REG_TO_DPI.get(reg)


def dpi_stage_encode(x, y):
    return bytes([0x00, dpi_to_register(x), dpi_to_register(y)])


def dpi_stage_decode(data):
    return (
        dpi_from_register(data[1]),
        dpi_from_register(data[2]),
    )


def build_frame(command):
    frame = bytearray(REPORT_SIZE)
    frame[0] = REPORT_ID
    frame[1] = (MSG_TYPE_SETTINGS >> 8) & 0xFF
    frame[2] = MSG_TYPE_SETTINGS & 0xFF
    frame[3] = command
    return frame


def build_get_settings():
    return build_frame(CMD_GET_SETTINGS)


def build_set_settings(current):
    frame = bytearray(current)
    frame[3] = CMD_SET_SETTINGS
    return frame


def build_commit(bindings=None):
    """Commit frame.

    With bindings=None this is the plain vendor commit (permanent slot
    residents only). With a {slot_offset: 5-byte record} dict, the given
    key-binding records are injected into their slots — the same carrier
    OemDrv uses for button remaps (verified against live captures).
    """
    frame = bytearray(REPORT_SIZE)
    frame[0] = REPORT_ID
    frame[1] = (MSG_TYPE_SETTINGS >> 8) & 0xFF
    frame[2] = MSG_TYPE_SETTINGS & 0xFF
    frame[3] = CMD_SET_SETTINGS
    frame[4:7] = bytes([0x02, 0x02, 0xA5])
    frame[32] = SLOT_RESIDENT_B5
    frame[37] = SLOT_RESIDENT_B6
    frame[52] = SLOT_RESIDENT_C8
    if bindings:
        for offset, record in bindings.items():
            if len(record) != 5:
                raise ValueError("binding record must be exactly 5 bytes")
            if offset % 5 != 2:
                raise ValueError(f"bad binding slot offset {offset}")
            if offset in SLOT_RESIDENTS:
                raise ValueError(
                    f"offset {offset} holds a permanent resident; "
                    f"refusing implicit write"
                )
            frame[offset : offset + 5] = record
    return frame


def parse_commit(frame):
    """Decode key-binding records from a commit-frame payload.

    Only tag-0xFC records are returned; permanent slot residents
    (b5/b6/c8) and any foreign tags are ignored.
    """
    found = {}
    for offset in COMMIT_SLOT_OFFSETS:
        chunk = bytes(frame[offset : offset + 5])
        if not chunk or chunk[0] != BINDING_TAG_KEYBOARD:
            continue
        rec = decode_binding(chunk)
        if rec is not None:
            found[offset] = rec
    return found


COLOR_SLOTS_ALL = 0x7F


# --- Key binding table -------------------------------------------------
#
# The commit frame doubles as the button-remap carrier: offsets 22..63
# hold 5-byte slots (bases 22, 27, 32, 37, 42, 47, 52). Three bases are
# permanent residents even in factory commits; the rest carry one
# remap record each when set:
#
#     [tag][class][code][00][00]
#
#   tag 0xFC; class 0x00 = plain keyboard key (HID usage id,
#   Q=0x14, X=0x1B); class 0x01 = MODIFIED keyboard key — verified
#   live 2026-08-24: `fc 01 13` fired Ctrl+P (browser print dialog),
#   so class 0x01 adds a Ctrl-style modifier to the same HID usage
#   space. The wire encoding for mouse-BUTTON targets (bind a button
#   to left/right/middle/...) is still unknown; Cfg.ini's 11..15/A8/A9/AE
#   values are the Windows UI namespace only and do NOT appear on the
#   wire like that.
#
# Verified live against OemDrv captures AND Linux-written records:
# forward->Q/X typed correctly, slot 22/27 ownership confirmed.

BINDING_TAG_KEYBOARD = 0xFC
KEY_CLASS_KEYBOARD = 0x00
KEY_CLASS_KEYBOARD_CTRL = 0x01
BINDING_TAG_MACRO = 0xF3

# Bare-tag records ([T][00][00][00][00]) assign built-in functions.
# Decoded live 2026-08-24 by relocating candidates into verified slots
# and observing the effect (no VM captures needed). The tag space is a
# vendor enum: 90-96 media cluster, b0-b6 input actions, c8 LED cycle.
SPECIAL_FUNCTIONS = {
    0x90: "volume_up",
    0x91: "volume_down",
    0x92: "mute",
    0x93: "play_pause",
    0x94: "stop",           # inert without media context; inferred slot
    0x95: "prev_track",
    0x96: "next_track",
    0xB0: "left_click",     # verified: forward slot produced real clicks
    0xB1: "right_click",
    0xB2: "middle_click",
    0xB3: "nav_forward",    # browser-history forward
    0xB4: "nav_back",       # browser-history back
    0xB5: "scroll_up",
    0xB6: "scroll_down",
    0xC8: "led_cycle",      # cycles lighting color mode
}
SPECIAL_FUNCTION_TAGS = {v: k for k, v in SPECIAL_FUNCTIONS.items()}

SLOT_RESIDENT_B5 = 0xB5
SLOT_RESIDENT_B6 = 0xB6
SLOT_RESIDENT_C8 = 0xC8
SLOT_RESIDENTS = {
    32: SLOT_RESIDENT_B5,
    37: SLOT_RESIDENT_B6,
    52: SLOT_RESIDENT_C8,
}

COMMIT_SLOT_OFFSETS = (7, 12, 17, 22, 27, 32, 37, 42, 47, 52)

# Slot ownership fully mapped 2026-08-24 (live relocate experiments,
# cross-checked against capture-1): the stride-5 grid starts at 7 and
# covers every programmable button incl. the main clicks.
SLOT_NAMES = {
    7: "left",
    12: "right",
    17: "middle",
    27: "forward",
    22: "back",
    42: "dpi_minus",
    47: "dpi_plus",
}
VERIFIED_SLOTS = frozenset((7, 12, 17, 22, 27, 42, 47))
EXPERIMENTAL_SLOTS = frozenset((57,))

# Cfg.ini UI namespace (installer defaults). Reference only — these
# are NOT wire codes for mouse-button targets.
MOUSE_BUTTON_CODES = {
    "left": 0x11,
    "middle": 0x12,
    "right": 0x13,
    "forward": 0x14,
    "back": 0x15,
    "dpi_down": 0x19,
    "dpi_up": 0x1A,
    "scroll_up": 0xA8,
    "scroll_down": 0xA9,
    "fire": 0xAE,
}
MOUSE_BUTTON_NAMES = {v: k for k, v in MOUSE_BUTTON_CODES.items()}

_HID_NAV_KEYS = {
    "esc": 0x29,
    "tab": 0x2B,
    "space": 0x2C,
    "enter": 0x28,
    "backspace": 0x2A,
    "capslock": 0x39,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "printscreen": 0x46,
    "scrolllock": 0x47,
    "pause": 0x48,
    "application": 0x65,
    "numlock": 0x53,
    "kpdivide": 0x54,
    "kpmultiply": 0x55,
    "kpminus": 0x56,
    "kpplus": 0x57,
    "kpenter": 0x58,
    "kp1": 0x59, "kp2": 0x5A, "kp3": 0x5B, "kp4": 0x5C, "kp5": 0x5D,
    "kp6": 0x5E, "kp7": 0x5F, "kp8": 0x60, "kp9": 0x61, "kp0": 0x62,
    "kpdot": 0x63,
    # punctuation (US layout)
    "minus": 0x2D,
    "equal": 0x2E,
    "lbracket": 0x2F,
    "rbracket": 0x30,
    "backslash": 0x31,
    "semicolon": 0x33,
    "quote": 0x34,
    "grave": 0x35,
    "comma": 0x36,
    "dot": 0x37,
    "slash": 0x38,
}


def _build_keyboard_keys():
    keys = {}
    for i in range(26):
        keys[chr(ord("a") + i)] = 0x04 + i
    for n in range(1, 10):
        keys[str(n)] = 0x1E + (n - 1)
    keys["0"] = 0x27
    for n in range(1, 13):
        keys[f"f{n}"] = 0x3A + (n - 1)
    keys.update(_HID_NAV_KEYS)
    # Modifier keys
    keys.update({
        "lctrl": 0xE0, "ctrl": 0xE0, "rctrl": 0xE4,
        "lshift": 0xE1, "shift": 0xE1, "rshift": 0xE5,
        "lalt": 0xE2, "alt": 0xE2, "ralt": 0xE6,
        "lgui": 0xE3, "gui": 0xE3, "win": 0xE3, "super": 0xE3, "rgui": 0xE7,
    })
    return keys


# Every named keyboard key bindable via `keys bind SLOT --key NAME`.
HID_KEYBOARD_KEYS = _build_keyboard_keys()
KEYBOARD_KEY_NAMES = sorted(HID_KEYBOARD_KEYS)


def hid_keyboard_code(name):
    """Resolve a keyboard key name (or raw 0xNN) to a HID usage id."""
    text = str(name).strip().lower()
    if text in HID_KEYBOARD_KEYS:
        return HID_KEYBOARD_KEYS[text]
    if text.startswith("0x"):
        try:
            code = int(text, 16)
        except ValueError:
            raise ValueError(f"unknown keyboard key '{name}'") from None
        if not 0x04 <= code <= 0xE7:
            raise ValueError(f"hid usage {text} outside writable range")
        return code
    raise ValueError(
        f"unknown keyboard key '{name}'; known: "
        + ", ".join(KEYBOARD_KEY_NAMES)
    )


def keyboard_code_name(code):
    for name, value in HID_KEYBOARD_KEYS.items():
        if value == code:
            return name
    return f"0x{code:02X}"


def encode_binding(key_class, code):
    return bytes([BINDING_TAG_KEYBOARD, key_class & 0xFF, code & 0xFF, 0, 0])


def encode_macro(macro_id, cycle_mode=0, cycle_times=1):
    if not 1 <= macro_id <= 255:
        raise ValueError("macro_id must be 1..255")
    return bytes([BINDING_TAG_MACRO, macro_id & 0xFF, cycle_mode & 0xFF, cycle_times & 0xFF, 0])


def encode_macro_steps(steps):
    """Encode macro steps into the wire byte format.

    steps: list of ("down", hid_code) | ("up", hid_code) | ("delay", ms)
    Wire format (StMacro_To_HdMacro): 02 XX = key down, 03 XX = key up,
    01 HH LL = delay ms (big-endian 16-bit).
    """
    buf = bytearray()
    for action, value in steps:
        if action == "down":
            buf += bytes([0x02, value & 0xFF])
        elif action == "up":
            buf += bytes([0x03, value & 0xFF])
        elif action == "delay":
            buf += bytes([0x01, (value >> 8) & 0xFF, value & 0xFF])
        else:
            raise ValueError(f"unknown macro action '{action}'")
    return bytes(buf)


MACRO_PAYLOAD_HEADER = b"\x01" + b"\x00" * 30
A8_CHUNK_DATA_MAX = 0x39  # 57 bytes per A8 chunk (OemDrv SetMacro @0x43d380)


def build_macro_payload(steps):
    """Device macro image (StMacro_To_HdMacro @0x4097c0): [0x01][30 zeros][steps]."""
    return MACRO_PAYLOAD_HEADER + encode_macro_steps(steps)


def build_macro_opener():
    """AA 00 frame — FreeMacroID(0): flush stored macros, starts upload session."""
    frame = bytearray(REPORT_SIZE)
    frame[0] = REPORT_ID
    frame[1] = 0xAA
    return frame


def build_macro_frames(macro_id, steps):
    """Build A7 header + A8 chunk frames for a macro upload.

    Reversed from OemDrv (MallocMacroID @0x43d240, SetMacro @0x43d380):
      A7: [A7][macro_id][(payload_size+5) u16 big-endian]
      A8 chunk (data <= 57 bytes): [A8][macro_id][0][seg 1-based][total][len][data]
    Verified byte-for-byte against capture-1.pcap for the DSADSA macro.
    """
    payload = build_macro_payload(steps)
    size_field = len(payload) + 5
    if size_field > 0xFFFF:
        raise ValueError("macro too large for device")
    a7 = bytearray(REPORT_SIZE)
    a7[0] = REPORT_ID
    a7[1] = 0xA7
    a7[2] = macro_id & 0xFF
    a7[3] = (size_field >> 8) & 0xFF
    a7[4] = size_field & 0xFF

    chunks = [payload[i:i + A8_CHUNK_DATA_MAX]
              for i in range(0, len(payload), A8_CHUNK_DATA_MAX)]
    total = len(chunks)
    frames = [bytes(a7)]
    for seg, chunk in enumerate(chunks, 1):
        a8 = bytearray(REPORT_SIZE)
        a8[0] = REPORT_ID
        a8[1] = 0xA8
        a8[2] = macro_id & 0xFF
        a8[3] = 0x00
        a8[4] = seg
        a8[5] = total
        a8[6] = len(chunk)
        a8[7:7 + len(chunk)] = chunk
        frames.append(bytes(a8))
    return frames


def parse_mly(path):
    """Parse a Fantech Windows .mly macro export into (action, value) steps."""
    import struct
    data = _mly_decode(open(path, "rb").read())
    magic, = struct.unpack_from("<I", data, 0)
    if magic != MLY_MAGIC:
        raise ValueError(f"{path}: bad decoded magic {magic:#010x} "
                         "(not a Fantech .mly macro?)")
    steps = []
    off = MLY_EVENTS_OFF
    for _ in range(MLY_EVENT_COUNT):
        vk, flags, delay = struct.unpack_from("<HHI", data, off)
        if vk == 0 and flags == 0 and delay == 0:
            break
        hid = VK_HID.get(vk)
        if hid is None:
            raise ValueError(f"{path}: unmapped VK {vk:#06x} at {off:#x}")
        steps.append(("down" if flags & 1 else "up", hid))
        if delay:
            steps.append(("delay", min(delay, 0xFFFF)))
        off += 12
    return steps


def parse_macro_file(path):
    """Parse a .macro text file into a list of (action, value) steps.

    Format (one per line, # comments, blank lines ignored):
        down <key>          key press (HID name or 0xNN)
        up <key>            key release
        delay <ms>          pause in milliseconds
        tap <key> [delay]   shorthand: down + delay + up (default 30ms)
        press <key1>+<key2>+... [delay]   combo: all down, delay, all up
    """
    steps = []
    with open(path) as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("#")[0].strip()
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()
            if cmd == "down" and len(parts) == 2:
                steps.append(("down", hid_keyboard_code(parts[1])))
            elif cmd == "up" and len(parts) == 2:
                steps.append(("up", hid_keyboard_code(parts[1])))
            elif cmd == "delay" and len(parts) == 2:
                steps.append(("delay", int(parts[1])))
            elif cmd == "tap" and len(parts) >= 2:
                code = hid_keyboard_code(parts[1])
                ms = int(parts[2]) if len(parts) > 2 else 30
                steps.append(("down", code))
                steps.append(("delay", ms))
                steps.append(("up", code))
            elif cmd == "press" and len(parts) >= 2:
                keys = parts[1].split("+")
                ms = int(parts[2]) if len(parts) > 2 else 30
                codes = [hid_keyboard_code(k) for k in keys]
                for c in codes:
                    steps.append(("down", c))
                steps.append(("delay", ms))
                for c in reversed(codes):
                    steps.append(("up", c))
            else:
                raise ValueError(f"line {lineno}: bad macro command: {raw.rstrip()}")
    return steps


def encode_special(tag):
    """Bare-tag function record, e.g. encode_special(0x90) = volume up."""
    if tag not in SPECIAL_FUNCTIONS:
        raise ValueError(
            f"unknown special function tag {tag:#04x}; known: "
            + ", ".join(sorted(SPECIAL_FUNCTIONS.values()))
        )
    return bytes([tag, 0, 0, 0, 0])


def decode_binding(record):
    if len(record) != 5 or record == b"\x00\x00\x00\x00\x00":
        return None
    tag, key_class, code = record[0], record[1], record[2]
    if record[1:] == b"\x00\x00\x00\x00" and tag in SPECIAL_FUNCTIONS:
        name = SPECIAL_FUNCTIONS[tag]
        return {"class": "special", "code": tag, "name": name}
    if tag != BINDING_TAG_KEYBOARD:
        return {"raw": record.hex(), "note": "unknown tag"}
    if key_class == KEY_CLASS_KEYBOARD:
        return {"class": "keyboard", "code": code, "name": keyboard_code_name(code)}
    if key_class == KEY_CLASS_KEYBOARD_CTRL:
        # verified live: fc 01 13 fired Ctrl+P (print dialog)
        return {
            "class": "keyboard_ctrl",
            "code": code,
            "name": f"ctrl+{keyboard_code_name(code)}",
        }
    return {"class": f"unknown_{key_class:#04x}", "code": code, "name": f"0x{code:02X}"}


def parse_notify(payload):
    """Decode a 9-byte button-press notify from EP2 IN.

    Layout: [01][class][?][code][zeros...] — echoes the current binding
    of whichever physical button was pressed (no button index present).
    """
    if len(payload) < 9 or payload[0] != 0x01:
        return None
    rec = decode_binding(bytes([BINDING_TAG_KEYBOARD, payload[1], payload[3], 0, 0]))
    if rec is None:
        return None
    rec["status"] = payload[2]
    return rec


def build_factory_reset():
    return build_commit()


def parse_settings(frame):
    if len(frame) != REPORT_SIZE:
        raise ValueError(f"expected {REPORT_SIZE} bytes, got {len(frame)}")
    if frame[0] != REPORT_ID or frame[1] != 0xA0 or frame[2] != 0x01:
        raise ValueError(f"unexpected header {frame[:3].hex()}")
    stages = []
    for i in range(7):
        offset = 9 + i * 3
        sx, sy = dpi_stage_decode(frame[offset : offset + 3])
        stages.append({"index": i + 1, "x": sx, "y": sy})
    return {
        "command": frame[3],
        "magic_header": frame[4:7].hex(),
        "dpi_active_stage": frame[7] + 1,
        "dpi_enabled_mask": frame[8],
        "dpi_stages": stages,
        "unknown_31_33": frame[30:33].hex(),
        "polling_raw": frame[POLLING_OFFSET],
        "polling_hz": polling_from_raw(frame[POLLING_OFFSET]),
        "magic_trailer": frame[34:37].hex(),
        "led_effect_raw": frame[37],
        "led_effect": LED_EFFECTS.get(frame[37], f"unknown_{frame[37]:#04x}"),
        "led_speed": led_speed_from_wire(frame[38]),
        "led_brightness": frame[39],
        "profile": frame[40],
        "colors_enabled": frame[41],
        "colors": [tuple(frame[42 + i * 3 : 45 + i * 3]) for i in range(7)],
        "tail": frame[63],
    }


def is_settings_frame(pkt):
    return (
        len(pkt) == REPORT_SIZE
        and pkt[0] == REPORT_ID
        and pkt[1] == 0xA0
        and pkt[2] == 0x01
        and pkt[4:7] == HEADER_MAGIC
        and pkt[34:37] == TRAILER_MAGIC
    )


def settings_from_packets(packets):
    for pkt in reversed(packets):
        if is_settings_frame(pkt):
            return pkt
    return None


EFFECT_NAMES = {
    "chroma": 0,
    "neon": 1,
    "custom_breathe": 2,
    "breathe": 3,
    "tail": 4,
    "steady": 5,
    "off": 6,
}

LED_MIN_EFFECT = 0
LED_MAX_EFFECT = 6
LED_MAX_BRIGHTNESS = 4
LED_MAX_SPEED = 2

# Polling rate: settings-frame byte 33.
# Verified from OemDrv captures (param-polling.pcap): the driver writes
# 0x00/0x01/0x02/0x03 to byte 33 when cycling 125/250/500/1000 Hz.
POLLING_RATES = {125: 0x00, 250: 0x01, 500: 0x02, 1000: 0x03}
_POLLING_BY_RAW = {v: k for k, v in POLLING_RATES.items()}
POLLING_OFFSET = 33


def resolve_effect(text):
    if text.lstrip("+-").isdigit():
        eid = int(text, 0)
        if not LED_MIN_EFFECT <= eid <= LED_MAX_EFFECT:
            raise ValueError(
                f"effect id {eid} out of range; valid ids are "
                f"{LED_MIN_EFFECT}..{LED_MAX_EFFECT} — ids outside this "
                f"range corrupt the engine"
            )
        return eid
    eid = EFFECT_NAMES.get(text)
    if eid is None:
        raise ValueError(
            f"unknown effect '{text}'; known: {', '.join(sorted(EFFECT_NAMES))}"
        )
    return eid


LED_PARAM_TEMPLATES = {
    0: bytes.fromhex(
        "04a4030001040100ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    1: bytes.fromhex(
        "04a4030100000100ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    2: bytes.fromhex(
        "04a40302000a0100ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    3: bytes.fromhex(
        "04a4030300000100ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    4: bytes.fromhex(
        "04a4030400000100ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    5: bytes.fromhex(
        "04a4030500000100ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
    6: bytes.fromhex(
        "04a4030600000000ff000000ff000000ffff00ffffff0000ffffffffff"
        "0000000000000000000000000000000000000000000000000000000000000000"
    ),
}


def build_led_params(enable, brightness):
    out = []
    for param in (1, 2, 3, 4, 5, 6, 0):
        frame = bytearray(LED_PARAM_TEMPLATES[param])
        if param == 0:
            frame[4] = 1 if enable else 0
            frame[5] = max(0, min(LED_MAX_BRIGHTNESS, brightness))
        out.append(bytes(frame))
    return out


def build_init_step(step):
    frame = bytearray(REPORT_SIZE)
    frame[0] = REPORT_ID
    frame[1] = 0xA1
    frame[2] = 0x02
    frame[3] = step & 0xFF
    return frame


def set_effect(frame, effect):
    if not LED_MIN_EFFECT <= effect <= LED_MAX_EFFECT:
        raise ValueError(f"effect {effect} outside valid range 0..6")
    frame[37] = effect


def led_speed_from_wire(raw):
    """Wire byte (0 = fastest on device) -> user scale (0 = slowest)."""
    return LED_MAX_SPEED - raw


def set_speed(frame, speed):
    """Set animation speed on the USER scale: 0 = slowest, 2 = fastest.

    The wire byte is inverted (0 = fastest on the device); see
    led_speed_from_wire for the reverse mapping.
    """
    if not 0 <= speed <= LED_MAX_SPEED:
        raise ValueError(f"speed must be 0..{LED_MAX_SPEED}")
    frame[38] = LED_MAX_SPEED - speed


def set_brightness(frame, level):
    if not 0 <= level <= LED_MAX_BRIGHTNESS:
        raise ValueError(f"brightness must be 0..{LED_MAX_BRIGHTNESS}")
    frame[39] = level


def stage_offset(index):
    if not 1 <= index <= 7:
        raise ValueError("dpi stage must be 1..7")
    return 9 + (index - 1) * 3


def color_offset(index):
    if not 1 <= index <= 7:
        raise ValueError("color slot must be 1..7")
    return 42 + (index - 1) * 3


def set_stage(frame, index, x=None, y=None):
    off = stage_offset(index)
    cur_x, cur_y = dpi_stage_decode(frame[off : off + 3])
    nx = x if x is not None else cur_x
    ny = y if y is not None else cur_y
    if nx is None or ny is None:
        raise ValueError(f"cannot resolve current stage {index} values")
    frame[off : off + 3] = dpi_stage_encode(nx, ny)


def set_active_stage(frame, index):
    if not 1 <= index <= 7:
        raise ValueError("dpi stage must be 1..7")
    frame[7] = index - 1


def set_enabled_mask(frame, mask):
    frame[8] = mask & 0xFF


def set_polling(frame, hz):
    """Set polling rate in Hz.  Writes the raw byte directly."""
    if hz not in POLLING_RATES:
        valid = ", ".join(str(k) for k in sorted(POLLING_RATES))
        raise ValueError(f"polling rate must be one of: {valid}")
    frame[POLLING_OFFSET] = POLLING_RATES[hz]


def polling_from_raw(raw):
    """Resolve byte33 raw value to Hz, or None if unknown."""
    return _POLLING_BY_RAW.get(raw)


def set_led(frame, effect=None, brightness=None, speed=None, colors_enabled=None):
    if effect is not None:
        frame[37] = effect & 0xFF
    if speed is not None:
        if not 0 <= speed <= 2:
            raise ValueError("led speed must be 0..2 (0 = slowest, 2 = fastest)")
        frame[38] = LED_MAX_SPEED - speed
    if brightness is not None:
        if not 0 <= brightness <= 10:
            raise ValueError("led brightness must be 0..10")
        frame[39] = brightness
    if colors_enabled is not None:
        frame[41] = 1 if colors_enabled else 0


def set_profile(frame, index):
    if not 1 <= index <= 5:
        raise ValueError("profile must be 1..5")
    frame[40] = index


def set_stage_color(frame, index, rgb):
    off = color_offset(index)
    frame[off : off + 3] = bytes(rgb)


def format_hexdump(data):
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:04x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)
