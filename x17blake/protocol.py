REPORT_SIZE = 64

REPORT_ID = 0x04
MSG_TYPE_SETTINGS = 0xA001
CMD_GET_SETTINGS = 0x01
CMD_SET_SETTINGS = 0x02

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


def build_commit():
    frame = bytearray(REPORT_SIZE)
    frame[0] = REPORT_ID
    frame[1] = (MSG_TYPE_SETTINGS >> 8) & 0xFF
    frame[2] = MSG_TYPE_SETTINGS & 0xFF
    frame[3] = CMD_SET_SETTINGS
    frame[4:7] = bytes([0x02, 0x02, 0xA5])
    return frame


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
        "lift_off_distance_raw": frame[33],
        "lift_off_distance_ui": frame[33] - 1 if frame[33] >= 2 else None,
        "magic_trailer": frame[34:37].hex(),
        "led_effect_raw": frame[37],
        "led_effect": LED_EFFECTS.get(frame[37], f"unknown_{frame[37]:#04x}"),
        "led_speed": frame[38],
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


def set_speed(frame, speed):
    if not 0 <= speed <= LED_MAX_SPEED:
        raise ValueError(f"speed must be 0..{LED_MAX_SPEED}")
    frame[38] = speed


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


def set_lift_off_distance(frame, ui_level):
    if ui_level not in (1, 2, 3):
        raise ValueError("lift-off distance must be 1..3")
    frame[33] = ui_level + 1


def set_led(frame, effect=None, brightness=None, speed=None, colors_enabled=None):
    if effect is not None:
        frame[37] = effect & 0xFF
    if speed is not None:
        if not 0 <= speed <= 2:
            raise ValueError("led speed must be 0..2 (lower = faster)")
        frame[38] = speed
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
