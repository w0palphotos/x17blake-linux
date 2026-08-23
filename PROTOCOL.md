# X17 Blake / Wings Tech 2ea8:2203 — Protocol Notes

Working notes for reverse engineering the Fantech X17 Blake gaming mouse
config channel on Linux.

## Device topology

```
Bus 00X Device 00Y: ID 2ea8:2203 Wings Tech Gaming Mouse   bcdDevice 1.04

Interface 0 (boot mouse)      EP 1 IN,  interrupt,  8 bytes  -> /dev/hidraw1
Interface 1 (vendor/config)   EP 2 IN,  interrupt, 64 bytes  -> /dev/hidraw2
                              EP 3 OUT, interrupt, 64 bytes
```

The config software (`OemDrv.exe`) imports `HidD_SetFeature`,
`HidD_GetFeature`, `HidD_GetInputReport` -> control transfers over
interface 1. Interrupt OUT (EP 3) is an alternate transport used by the
same message format in the Sharkoon variant.

## Identity with Sharkoon Light2 200

Same VID:PID (2ea8:2203), same bcdDevice (1.04), same interface/endpoint
layout as the Sharkoon Light2 200 (PMW-3389 platform). Reference:
https://github.com/axel-dd/sharkoon-light2-200 (protocol docs + pcaps).

Known Light2 200 settings frame (64 bytes, report id 0x04):

| Byte(s) | Meaning                                   |
|---------|-------------------------------------------|
| 0       | 0x04 (report id / version)                |
| 1-2     | 0xA0 0x01 (message type)                  |
| 3       | command: 0x01 get, 0x02 set               |
| 4-6     | 01 02 A5                                  |
| 7       | active DPI stage (0-6)                    |
| 8       | enabled-stage bitmask                     |
| 9-29    | 7 x DPI stage (x/y), unit = 50            |
| 30-32   | zero                                      |
| 33      | lift-off distance (2-4; UI value - 1)     |
| 34-36   | 02 00 A5                                  |
| 37      | LED effect (0-9)                          |
| 38      | LED speed (0-2, lower = faster)           |
| 39      | LED brightness (0-10)                     |
| 40      | profile (1-5)                             |
| 41      | colors enabled (?)                        |
| 42-62   | 7 x RGB color                             |
| 63      | zero                                      |

LED effects: 0 pulsating RGB cycle, 1 pulsating, 2 permanent,
3 color change, 4 single-color marquee, 5 multi-color marquee,
6 ripple, 7 trigger, 8 heartbeat, 9 off.

DPI stage encoding (per stage, 3 bytes, values stored /50):

```
byte0 = ((x >> 8) & 0x0F) << 4 | ((y >> 8) & 0x0F)
byte1 = x & 0xFF
byte2 = y & 0xFF
```

## Blake-specific data from the Windows installer (Cfg.ini)

* Sensor id: 0x3325, max DPI 10000 (vs 16000 on Light2 200).
* Default stages: 800, 1200, 1600, 2000, 2400, 3000, 4000.
* Default stage colors (RGB): FF0000, 0000FF, 00FF00, FFFF00,
  00FFFF, FF00FF, FFFFFF.
* Polling register default `DR=0x500`.
* Key defaults (type, code, ?, slot):
  K1=01 11 L, K2=01 13 R, K3=01 12 M, K4=01 14 fwd, K5=01 15 back,
  K6=08 A8 scroll up, K7=08 A9 scroll down, K8=01 19 dpi-, K9=01 20 dpi+,
  K10=08 AE fire key.
* Software pages: key assignment, DPI, LED, macro, parameter
  (polling/debounce), gun (disabled).

## Windows binary layout

`Lowerdev.dll` is a thin HID transport shim. Exports:
`FindHidDevice`, `OpenHidDevice`, `GetDevVersion`, `GetProductID`,
`GetProductString`, `GetFeature`, `SetFeature`, `GetInputReport`,
`SetOutputReport`. Imports confirm HidD_* + SetupDi enumeration.
All protocol/command logic therefore lives in `OemDrv.exe`.

## CONFIRMED on live hardware (2026-08-23)

### Transport

GET/SET use **interrupt transfers on interface 1**: write the 64-byte frame
to EP3 OUT (`os.write` on hidraw2 = output report), read replies from EP2 IN.
Feature-report transfers do NOT work for this dialect
(`HIDIOCGFEATURE` returns 3 zero bytes, `HIDIOCSFEATURE` -> EPROTO).

On every transaction the device answers with **two packets**: the real
response first, then a trailing junk/status frame (`04 a0 01 ..` header
but magic `02 02 a5` at bytes 4-6, broken trailer, uninitialized bytes
b5/b6/c8 at offsets 32/37/52). Valid settings frames MUST have BOTH
magics (`01 02 a5` @4-6 AND `02 00 a5` @34-36); clients must filter on
both or they will parse garbage.

### Frame layout (identical slots as Light2 200, different DPI codec)

Verified byte-for-byte against live reads:

| Byte(s) | Meaning | Live sample |
|---|---|---|
| 0 | 0x04 | |
| 1-2 | a0 01 | |
| 3 | cmd: 01 get / 02 set | |
| 4-6 | 01 02 a5 | |
| 7 | active stage (0-based) | 00 |
| 8 | enabled-stage mask (?) | 01 |
| 9-29 | 7 x `[00, regX, regY]` DPI stages | 000b0b, 001b1b, ... |
| 30-32 | zeros | |
| 33 | lift-off distance raw (UI = raw-1) | 03 (= UI 2) |
| 34-36 | 02 00 a5 | |
| 37 | LED effect id | 06 |
| 38-39 | LED speed / brightness | 00 00 |
| 40 | profile | 01 |
| 41 | colors enabled(?) | 00 |
| 42-62 | 7 x RGB | ff0000 00ff00 0000ff ff00ff ffff00 00ffff ffffff |
| 63 | 00 | |

### Blake DPI encoding (differs from Light2 200)

Each stage triplet is `00 regX regY`; register values come from the
sensor table in Cfg.ini (`DPISET` <-> `DPIHW`, 54 pairs,
200-5000 step 100, then 6000-10000). Example mapping:
500->0x0B, 800->0x12, 1200->0x1B, 1600->0x24, 2000->0x2E,
2400->0x37, 3000->0x45, 4000->0x5C, 10000->0x7D.

Live-read current config: stages [500, 1200, 1600, 2000, 2400, 3000, 4000],
active stage 1, profile 1.

### Proven by experiment

* Identity SET round-trip leaves state unchanged (probe --roundtrip OK).
* Mutating stage 1 (500->800) via SET applies immediately; restore verified.
* `dpi --stage N --dpi V`, `lod 1-3` setters verified with read-back.
* LED color slots DRIVE the RGB (all-7-green test seen by user).
  Earlier red test was invalid: slot 1 was already FF0000.
* LED effect byte (37) changes animations (10-id sweep visibly cycled
  patterns). Exact per-id animation mapping still to be catalogued.
* Brightness semantics unclear: device runs at brightness byte 0.
* Byte 41 is NOT writable via the settings frame (device forces 0);
  not confirmed to be "colors enabled".
* Original state fully restored after experiments.

## Message grammar (confirmed via Sharkoon pcaps + live Blake)

All frames: `[0x04][A0 01][cmd][payload...]`, 64 bytes total, sent as
interrupt OUT on EP3; replies on EP2 IN.

| Frame | Meaning |
|---|---|
| `A0 01 00 <zeros>` | session opener (app sends at startup) |
| `A0 01 01 <zeros>` | GET settings |
| `A0 01 02 \| 01 02 A5 \| settings` | SET settings (volatile apply) |
| `A0 01 02 \| 02 02 A5 \| zeros` | **FACTORY RESET** (alone = Restore button) or commit-companion after every SET |
| `A7 ...` | key/binding upload channel (macro/key-list processing); NOT settings frame |

Startup order observed: opener -> opener+ver -> GET -> SET-A -> SET-B(zeros).

Settings payload layout (offsets within 64B frame) as documented above.

## Incident log (2026-08-23)

A raw `A7 00 00 00...` experiment corrupted button bindings (back +
scroll-down dead) and the LED engine gate. Neither is represented in the
64B settings frame (which stayed factory-pristine throughout). Fixed by
factory-reset frame + power cycle. Lesson encoded in tooling: writes are
restricted to verified field offsets; unknown-field writes require
explicit override; auto-backup before every mutation.

## LED findings (2026-08-23, post-incident)

Writing bytes 37-41 / 42-62 through the settings frame is HARMFUL on
Blake firmware: the lighting engine accepts renders briefly, then dies
(at replug at latest), and the block reverts writes. Factory reset
frame revives it, but repeated wedges suggest NVM-level corruption.
The real lighting control must use a different opcode family
(candidates: `AA`, `A7` variants) — decode from a labeled Windows
OemDrv capture before any further LED experiments. The CLI therefore
blocks these fields (`state.MUTABLE_OFFSETS`) and ships no led/color
commands.

## Open questions

1. Meaning of byte 8 (enabled mask = 0x01 while 7 stages configured?).
2. Exact A7 frame layout (slot index / code mapping) for button remapping.
3. Polling-rate command layout (Cfg.ini `DR=0x500` hint).
4. Brightness/speed byte semantics on Blake firmware.
5. Byte 41 purpose (not writable via settings frame).

## Methodology references

* https://santeri.pikarinen.com/pages/usb_hid_reverse_engineering/
* https://holland.sh/post/crafting-drivers-libusb/
* https://blog.lx862.com/blog/2024-05-13-reverse-engineering-a-mouse/
* https://github.com/santeri3700/hyperx_pulsefire_dart_reverse_engineering
