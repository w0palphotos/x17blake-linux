# How this driver was reverse engineered

Nobody working on this project needs to read assembly. The decoded
protocol lives in plain English in [PROTOCOL.md](PROTOCOL.md); this note
only records how those facts were obtained, so future work can redo or
extend the analysis without starting from zero.

## Source material

The vendor binaries (`Blake_EB__X17_Software_V1.0_19082000.exe` and the
extracted `FANTECH X17/` folder) come from Fantech's own download page
and are intentionally NOT committed to this repository (see
`.gitignore`). Keep a local copy if you want to redo analysis.

Key files inside:

| File           | Role                                                |
| -------------- | --------------------------------------------------- |
| `OemDrv.exe`   | MFC GUI; builds every protocol frame here           |
| `Lowerdev.dll` | thin `HidD_*` passthrough, nothing to learn        |
| `Cfg.ini`      | sensor/DPI tables, default key codes, polling hints |
| `text.xml`     | UI strings (feature list, "Restore" button, etc.)   |

## Regenerating disassembly

```sh
objdump -d --no-show-raw-insn "FANTECH X17/OemDrv.exe"   > /tmp/oem.asm
objdump -x "FANTECH X17/OemDrv.exe"                      # import/export tables
```

The `.exe` is PE32 i386; image base 0x400000. Convert file offsets to
virtual addresses via section headers (`objdump -h`): for `.rdata`,
`VA = 0x56a000 + (file_off - 0x169200)`.

## Already-decoded landmarks in OemDrv.exe

| Address                        | What it is                                                         |
| ------------------------------ | ------------------------------------------------------------------ |
| `0x401000`                     | HID transport: prepends report id `0x04`, overlapped 64-byte write |
| `0x401150`                     | send wrapper: stage buffer -> transport -> Sleep(20 ms) per chunk  |
| `0x43ce10`                     | reply poller (~100 x 20 ms) validating `A0 ...` header             |
| `0x43cce0`                     | LoadLibrary/GetProcAddress resolver for Lowerdev.dll               |
| `0x43c5e0`                     | reader thread (interface 1 input reports)                          |
| `0x43ce10–0x43d630`            | message builders cluster (opener/GET/SET/commit/A7)                |
| `0x43d130`                     | GET settings; parses reply payload at offset +5 into caller struct |
| `0x43cfe0`                     | SET settings (variant A `01 02 A5`, then commit B `02 02 a5`)      |
| `0x43d240`                     | `MallocMacroID` — builds the `A7 [id] [size+5 BE16]` header, waits for the `... 01` ack |
| `0x43d2f0`                     | `FreeMacroID(0)` — the `AA 00` opener that flushes stored macros |
| `0x43d380`                     | `SetMacro` — chunks the macro payload into `A8` frames (57 B each, `[A8][id][0][seg][total][len][data]`, `Sleep(15)`) |
| `0x409ba0`                     | the whole Apply flow: free IDs, per-macro upload (50 ms pacing), binding matrix, `SetMatrix` commit |
| `0x4097c0`                     | `StMacro_To_HdMacro` — event list to device payload `[01][30 zeros][step stream]`; also reveals the opcode set (02/03 key, 01 delay, 04/05 click, 06 wheel, 08/09 repeat) |
| `0x416750`                     | Import `.mly` dialog handler: fixed `0x526` (1318 B) read, magic check |
| `0x59c700`                     | VK→HID table (104 pairs) — the exact key set the firmware supports in macros |
| `0x594f40+`                    | UTF-16 debug strings (`Add_Macro: FAILED...`, `MallocMacroID: ...`, `SetMacro: ...`) — free navigation aids |
| globals `0x5d9020`, `0x5d8fe0` | receive buffers                                                    |

Frame grammar and byte layouts: see PROTOCOL.md.

## Methodology that worked

1. **Reuse public work first**: this platform is shared with the Sharkoon
   Light2 200 (same VID:PID `2ea8:2203`).
   https://github.com/axel-dd/sharkoon-light2-200 ships labeled pcaps;
   `tools/pcap_frames.py` extracts frames from them:
   ```sh
   python3 tools/pcap_frames.py "captures/reset settings.pcapng"
   ```
   The factory-reset frame came from their `reset settings.pcapng`.
2. **Live probing beats guessing**: GET/SET round-trips with read-back
   verification (see `x17blake probe --roundtrip`).
3. **One variable per experiment**, always with `x17blake backup` first.
4. Guides worth reading:
   - https://santeri.pikarinen.com/pages/usb_hid_reverse_engineering/
   - https://holland.sh/post/crafting-drivers-libusb/
   - https://blog.lx862.com/blog/2024-05-13-reverse-engineering-a-mouse/
   - https://github.com/santeri3700/hyperx_pulsefire_dart_reverse_engineering

## Decoding without the VM (2026-08-24)

Once the commit-frame binding table was understood from pcaps, the rest
of the button semantics were decoded entirely from Linux, no Windows
captures needed. The technique, now automated in
`tools/explore_bindings.py`:

1. **Relocate** an unknown record (e.g. bare tag `90`) into a slot
   whose physical button is known (forward = offset 27).
2. **Press and observe three channels**: the config-channel notify
   echo (`[01][class][code]`, keyboard-class records only), the
   boot-mouse reports on interface 0 (click bits / wheel), and a GET
   settings delta afterwards (active stage / profile changes).
3. For functions with no observable side channel (volume, mute,
   media), ask the operator what they perceived, one press per
   candidate, five candidates per round.
4. **Bisect safely first**: `--single` writes one record and checks the
   device survives it (some functions re-enumerate the USB device when
   pressed; writes themselves never did).

This decoded the full special-function table (volume/media/scroll/
LED-cycle), the slot->button map for dpi-/dpi+, and falsified the
Cfg.ini mouse-button-code assumption (`fc 01 13` is Ctrl+P, not
right-click) in a single session. A follow-up pass went further:

* planting letters into never-seen offsets proved the stride-5 grid
  starts at 7: slots 7/12/17 belong to the LEFT/RIGHT/MIDDLE buttons,
  so every programmable button is remappable;
* sweeping the bare-tag space found the input-action enum
  `b0-b6` (left/right/middle click, navigate forward/back, scroll
  up/down), which is how mouse-click targets are encoded on the wire;
* class `fc 0a <code>` turned out to be a press-and-hold form
  (`fc 0a 13` dims the display while held).

If you ever need deeper static work, Ghidra (headless) gives function
boundaries that raw objdump lacks; everything above was done with objdump

- grep alone.

For the hands-on USB capture workflow (VM setup, segment checklist,
decode loop), see [docs/CAPTURE-GUIDE.md](docs/CAPTURE-GUIDE.md).

## Macro protocol + `.mly` format (2026-08-30, Ghidra MCP session)

The macro upload trio (`AA`/`A7`/`A8`), the step encoding, and the
Windows `.mly` macro file format were cracked in one session by
combining three techniques — recorded here because the mix is the
reusable part:

1. **Known-plaintext on `.mly`**: two exports of the *same* recording
   (`test-typing.mly`, `qwerty-test.mly`) differ only in timestamps, so
   key bytes that matched across files had to be the encoded key IDs;
   the recorded typing order (qwerty rows, not alphabetical!) plus
   `DSADSA.mly` (events known from a UI screenshot) fixed the mapping.
   The magic `28 22 cc be` vs the `Add_Macro` code checking
   `0xFA3388A0` exposed the obfuscation: **every byte is ROR8(x, 2)**.
   Decoded, the file is plain magic + ASCII name + `[vk:u16][flags:u16]
   [delay:u32 ms]` events — full layout in PROTOCOL.md.
2. **Ack probing on the wire**: sending `A8` variants and reading the
   device's single-byte verdict (`byte 2 == 01` accepted) pinned which
   preamble fields the firmware validates — no button presses needed.
3. **Ghidra on `OemDrv.exe`** (via the ryuumonbuchi MCP): the ack probe
   told us *what* to look for; the decompiler gave the exact chunking
   (`ceil(n/57)`, seg/total/len fields), payload wrapper
   (`[01][30 zeros][steps]`), apply sequence with vendor timing
   (100/50/15/50 ms), and the VK→HID table. Search the UTF-16 debug
   strings first (`MallocMacroID`, `SetMacro`, `StMacro_To_HdMacro`) —
   each one sits next to its builder function.

The resulting implementation lives in `x17blake/protocol.py`
(`parse_mly`, `build_macro_frames`) and `x17blake/device.py`
(`upload_macro`), verified byte-for-byte against
`captures/capture-1.pcap`.
