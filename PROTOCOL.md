# X17 Blake / Wings Tech 2ea8:2203 protocol notes

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
| 33 | polling rate (0x00=125, 0x01=250, 0x02=500, 0x03=1000 Hz) | 03 (= 1000 Hz) |
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
* `dpi --stage N --dpi V` setter verified with read-back.
* `lod 1-3` writes to byte 33; see note below re: polling conflict.
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

## Lighting: SOLVED (2026-08-24, verified live)

Blake effect ids (settings-frame byte 37): **completely different from
the Sharkoon table**:

| Id | Mode | Renders from Linux |
|----|------|--------------------|
| 0 | chroma (rainbow cycle) | ✅ |
| 1 | neon | ✅ |
| 2 | custom breathe | ✅ |
| 3 | breathe | ✅ |
| 4 | tail | ✅ |
| 5 | steady (solid palette) | ✅ |
| 6 | off | ✅ |

Other fields: byte 38 speed, byte 39 brightness (**0-4**, 0 = off),
byte 40 enable (=1), **byte 41 = color-slot enable bitmask (0x7f = all
seven), required for custom breathe / tail to render, bytes 42-62 =
7x RGB palette.

Commit frame (`02 02 a5` variant) is NOT all-zero: the vendor sends
**0xB5 @32, 0xB6 @37, 0xC8 @52** inside it (the device's so-called
"junk echo" frames are echoes of these). `protocol.build_commit()`
replicates it byte-exact.

## Key bindings: DECODED (2026-08-24, from OemDrv captures)

The **commit frame doubles as the button-remap carrier**. Its payload
region reuses offsets 22-63 as a table of 5-byte slots (bases 22, 27,
32, 37, 42, 47, 52). The historical "magic" bytes `b5@32 / b6@37 /
c8@52` are simply permanent slot residents present even in factory
commits, not protocol junk.

Record layout per occupied slot:

```
[tag][class][code][00][00]
tag   = 0xFC for all known classes
class = 0x00 keyboard, plain   -> code = HID usage id (Q=0x14, X=0x1B)
class = 0x01 keyboard, Ctrl+?  -> code = HID usage id of the base key
```

Evidence: `fc 00 14` appeared exactly in the fwd->Q capture, `fc 00 1b`
in fwd->X captures; each Apply produced only SET+COMMIT pairs.
settings frames never carry bindings.

**Live Linux write verification (2026-08-24):**

* `fc 00 1b` on slot 27 (forward): button typed `x`. ✅
* `fc 01 13` on slot 22 (back): fired **Ctrl+P** (browser print
  dialog), NOT right-click. This proves class 0x01 is a modified
  keyboard key and that Cfg.ini's `01 13 R` notation is the Windows UI
  namespace only. Real mouse-click targets later turned up as bare
  tags `b0/b1/b2`; see the function table below.
* Both bindings cleared via commit-with-empty-table; buttons returned
  to factory behavior instantly (no power cycle needed).

Slot -> button map (fully mapped 2026-08-24, live relocate experiments):

| Offset | Button | Default content |
|--------|--------|-----------------|
| 7 | left click | empty (native) |
| 12 | right click | empty (native) |
| 17 | middle click | empty (native) |
| 22 | back | empty (native) |
| 27 | forward | empty (native) |
| 32 | wheel up | `b5` (= scroll up) |
| 37 | wheel down | `b6` (= scroll down) |
| 42 | dpi- | empty (native) |
| 47 | dpi+ | empty (native) |
| 52 | ? | `c8` (= LED cycle) |
| 57 | unidentified | accepts records |

The stride-5 slot grid therefore runs 7..52+ and covers every
programmable button including the main clicks; rebinding left/right/
middle themselves works exactly like in OemDrv.

### Bare-tag function records: DECODED LIVE (2026-08-24)

Single-byte records `[T][00][00][00][00]` assign built-in functions.
Decoded by relocating candidate tags into verified slots and observing
the effect on Linux, no Windows captures involved:

| Tag | Function |
|-----|----------|
| 0x90 | volume up |
| 0x91 | volume down |
| 0x92 | mute |
| 0x93 | play/pause |
| 0x94 | stop (inferred; inert without media) |
| 0x95 | previous track |
| 0x96 | next track |
| 0xB0 | left click |
| 0xB1 | right click |
| 0xB2 | middle click |
| 0xB3 | navigate forward (browser history) |
| 0xB4 | navigate back (browser history) |
| 0xB5 | scroll up (= wheel's factory resident @32) |
| 0xB6 | scroll down (= wheel's factory resident @37) |
| 0xC8 | lighting-mode cycle (= resident @52) |

The `b0-b6` block is a complete input-action enum: any button can be
bound to a real mouse click, and the main clicks themselves rebind
through slots 7/12/17 exactly like in OemDrv. Class `fc 0a <code>` is a
press-and-HOLD form: with code `0x13` the display dims while held and
restores on release. Tags `c0-c3` showed no visible effect under
niri/Wayland (vendor functions the compositor ignores, or no-ops).

The residents at 32/37/52 are therefore factory wheel-up / wheel-down /
LED-cycle assignments stored in the same table. Special-function
bindings do NOT emit button-press notifies. Tags 0x97-0x9A emit
keyboard-like output (`98`=Mod+R, `99`=Mod+F, `9A`='d'): a separate
shortcut space, mapping uncatalogued.

**Live Linux write verification (2026-08-24):**

* `fc 00 1b` @27, Forward typed `x`.
* `fc 01 13` @22, fired **Ctrl+P** (print dialog), NOT right-click:
  class 0x01 is a modified keyboard key; Cfg.ini's `01 13 R` notation
  is the Windows UI namespace only.
* `90/91/92/93/95/96/B0-B6/C8`, all verified per table above, incl.
  real clicks from bare tags.
* Commit-with-empty-table restores factory behavior instantly; binding
  writes survive device re-enumeration.

Consequence of GET replies never containing binding bytes: neither
OemDrv nor this tool can READ bindings from the device, host-side
state is the only source of truth. Any COMMIT write redefines the
whole table (unused slots must be written as zeros).

Button-press notify (EP2 IN, unsolicited, 9 bytes):
`[01][class][?][code][zeros...]`, echoes the current binding of
whichever button was pressed (class/code in wire namespace); carries
NO button index.

Macro upload trio (capture-1): `AA 00` opener -> `A7 01 00 3c` ->
`A8 01 | 01 01 37 01 <zeros> | step data @38..` (timed key events).
Structure known; step encoding not yet decoded.

Unexplained singleton: an `f3 01 00 01` record seen on the forward
slot in capture-1 (likely a further class/combo form). Short 2-byte OUT
writes `0101`/`0103` (same capture) remain unidentified, polling-rate
candidates. The lone tags `90`/`92` are now decoded, see the function
table above.

## Color depth findings (2026-08-24)

Although the interface accepts full 8-bit-per-channel RGB (the
"16.8M colors" marketing figure), **rendered output is quantized:
each channel behaves as effectively ON/OFF**. Verified by alternating
flip tests with per-write re-arming: `FF0000`, `8B0000`, `7F0000` and
`3F0000` all render identically. Consequences:

* Use **brightness (0-4)** as the real dimmer, it scales the whole
  LED, not the hex value.
* Hex input stays 24-bit for compatibility; hardware snaps values.
* Effective palette ~= 8 binary combinations x 5 brightness levels.

Also confirmed: the lighting engine only refreshes its render state
when freshly armed (INIT + parameter bank preceding each write).
Sparse bare SETs update storage but may not re-render.

Session choreography required before lighting writes (as emitted by
OemDrv):

1. `A1 02 {00,01,02,03}` x2 (init handshake)
2. `A4 03 <param>` frames 1..6 then 0 (parameter bank init; templates
   in `protocol.LED_PARAM_TEMPLATES`; param 0 = [enable, brightness])
3. Settings-frame SET with effect/speed/brightness/en/palette
4. Commit frame (`02 02 a5` zeros)

Root cause of the historical LED wedges: early experiments wrote
Sharkoon effect ids (including invalid id 9 = "off") which this
firmware does not accept, ids are hard-validated to 0-6 everywhere
now. The settings-frame LED bytes work fine when values are legal and
the parameter bank is initialized first; earlier "mirror-only" theory
was wrong.

Solved: custom breathe / tail render with byte41=0x7f + vendor-exact
commit; no per-mode parameters exist.

## Polling: SOLVED (2026-08-25, from param-polling.pcap)

Settings-frame byte 33 encodes the USB polling rate:

| Raw | Hz |
|-----|-----|
| 0x00 | 125 |
| 0x01 | 250 |
| 0x02 | 500 |
| 0x03 | 1000 |

Factory default is 0x03 (1000 Hz), matching `Cfg.ini DR=0x500` and the
README spec.  The short `0101`/`0103` frames from `capture-1.pcap` are
NOT polling commands. The poll capture (`param-polling.pcap`) showed only
full 64-byte SET+COMMIT pairs on byte 33.

Previously this byte was labeled as lift-off distance (Sharkoon reference
`PROTOCOL.md:39`).  The LOD writes from 2026-08-23 (`lod 1-3` writing
raw 2/3/4) were therefore setting polling, not LOD.  A hardware review
confirms LOD is fixed at ~3 mm on this model; no LOD register is known.

## Open questions

1. Meaning of byte 8 (enabled mask = 0x01 while 7 stages configured?).
2. Macro step-data encoding inside the `AA`/`A7`/`A8` upload trio.
3. ~~Polling-rate command layout~~ **SOLVED**: settings-frame byte 33 encodes
   polling rate (0x00=125 Hz, 0x01=250, 0x02=500, 0x03=1000). See
   `docs/verify/polling-rate.md`.
4. Brightness/speed byte semantics on Blake firmware.
5. Disable-function tag; remaining special tags (`c0-c7` zone inert
   under Wayland so far; 0x97-0x9A shortcut space); button owning
   slot 52.
6. Whether class 0x01's modifier is fixed Ctrl or selectable; full
   behavior map of hold-class `fc 0a`.
7. Byte 41 purpose (not writable via settings frame).
8. LOD true byte: byte 33 is now confirmed as polling; the real LOD
   register (if any) is elsewhere. The LOD writes from 2026-08-23
   were effectively setting polling to 500/1000 Hz.

## Methodology references

* https://santeri.pikarinen.com/pages/usb_hid_reverse_engineering/
* https://holland.sh/post/crafting-drivers-libusb/
* https://blog.lx862.com/blog/2024-05-13-reverse-engineering-a-mouse/
* https://github.com/santeri3700/hyperx_pulsefire_dart_reverse_engineering
