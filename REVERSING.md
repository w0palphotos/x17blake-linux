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

| File | Role |
|---|---|
| `OemDrv.exe` | MFC GUI; builds every protocol frame here |
| `Lowerdev.dll` | thin `HidD_*` passthrough — nothing to learn |
| `Cfg.ini` | sensor/DPI tables, default key codes, polling hints |
| `text.xml` | UI strings (feature list, "Restore" button, etc.) |

## Regenerating disassembly

```sh
objdump -d --no-show-raw-insn "FANTECH X17/OemDrv.exe"   > /tmp/oem.asm
objdump -x "FANTECH X17/OemDrv.exe"                      # import/export tables
```

The `.exe` is PE32 i386; image base 0x400000. Convert file offsets to
virtual addresses via section headers (`objdump -h`): for `.rdata`,
`VA = 0x56a000 + (file_off - 0x169200)`.

## Already-decoded landmarks in OemDrv.exe

| Address | What it is |
|---|---|
| `0x401000` | HID transport: prepends report id `0x04`, overlapped 64-byte write |
| `0x401150` | send wrapper: stage buffer -> transport -> Sleep(20 ms) per chunk |
| `0x43ce10` | reply poller (~100 x 20 ms) validating `A0 ...` header |
| `0x43cce0` | LoadLibrary/GetProcAddress resolver for Lowerdev.dll |
| `0x43c5e0` | reader thread (interface 1 input reports) |
| `0x43ce10–0x43d630` | message builders cluster (opener/GET/SET/commit/A7) |
| `0x43d130` | GET settings; parses reply payload at offset +5 into caller struct |
| `0x43cfe0` | SET settings (variant A `01 02 A5`, then commit B `02 02 A5`) |
| `0x43d240` | key/binding upload channel (`A7 ...`) — layout still open |
| globals `0x5d9020`, `0x5d8fe0` | receive buffers |

Frame grammar and byte layouts: see PROTOCOL.md.

## Methodology that worked

1. **Reuse public work first** — this platform is shared with the Sharkoon
   Light2 200 (same VID:PID `2ea8:2203`).
   https://github.com/axel-dd/sharkoon-light2-200 ships labeled pcaps;
   `tools/pcap_frames.py` extracts frames from them:
   ```sh
   python3 tools/pcap_frames.py "captures/reset settings.pcapng"
   ```
   The factory-reset frame came from their `reset settings.pcapng`.
2. **Live probing beats guessing** — GET/SET round-trips with read-back
   verification (see `x17blake probe --roundtrip`).
3. **One variable per experiment**, always with `x17blake backup` first.
4. Guides worth reading:
   - https://santeri.pikarinen.com/pages/usb_hid_reverse_engineering/
   - https://holland.sh/post/crafting-drivers-libusb/
   - https://blog.lx862.com/blog/2024-05-13-reverse-engineering-a-mouse/
   - https://github.com/santeri3700/hyperx_pulsefire_dart_reverse_engineering

If you ever need deeper static work, Ghidra (headless) gives function
boundaries that raw objdump lacks; everything above was done with objdump
+ grep alone.
