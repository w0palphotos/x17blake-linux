# USB capture guide: recording and mapping MCU frames

How to systematically record what the vendor Windows tool sends to the
mouse, so new features can be decoded without guesswork. This workflow
produced every opcode in [PROTOCOL.md](../PROTOCOL.md).

## One-time / per-session setup

```sh
lsusb | grep -i 2ea8        # NOTE THE BUS NUMBER, it moves between ports!
sudo modprobe usbmon        # no-op if already loaded
sudo tcpdump -i usbmon<N> -s0 -w captures/<segment>.pcap
```

* `<N>` = the bus from `lsusb` (e.g. Bus 003 -> `usbmon3`). **The mouse
  changes buses whenever it is replugged into a different port, this
  has silently wasted a capture before; always re-check.
* Sanity check within ~10 s of starting: touch the mouse / click once,
  then `ls -la captures/<segment>.pcap`, the file must be growing.
* To hand the mouse to the Windows VM: virt-viewer menu ->
  *Redirect USB device*. Take it back the same way when testing from
  Linux (`x17blake` cannot see a redirected device).

## Golden rules

1. **One action per ~8–10 s.** Timestamp gaps are your click markers.
2. **Baseline between segments:**
   `x17blake preset apply initial-factory --yes` so every segment starts
   from an identical state.
3. Name captures after the single action recorded:
   `captures/button-fwd-keyb.pcap`, not `captures/session4.pcap`.
4. Never trust one surprising result, repeat the segment twice.
5. Start tcpdump BEFORE launching/using OemDrv for that action, stop
   right after (Ctrl-C): keeps files small and segments clean.

## Segment checklist

Confirmed against the actual OemDrv UI (Key assignment / DPI / LED /
Parameter / Macros pages). **Update 2026-08-25:** segments 2-4 are
RESOLVED — double-click speed, scrolling speed and mouse sensitivity
are Windows-only API calls (`SPI_SETDOUBLECLICKTIME`,
`SPI_SETWHEELSCROLLLINES`, `SPI_SETMOUSESPEED`); no firmware storage.
See `docs/verify/windows-only-settings.md`.  Segments 5-7 are
OBSOLETE, button semantics were decoded entirely from Linux via the
relocate-and-press technique (see REVERSING.md and
`tools/explore_bindings.py`); no VM capture needed.  Remaining
valuable segments marked with ❗.

| # | Segment name | Action inside OemDrv | Unlocks | Status |
|---|---|---|---|---|
| ~~1~~ | ~~`param-polling`~~ | ~~cycle each polling-rate option~~ | ~~polling-rate opcode~~ | **SOLVED**: byte 33 |
| ~~2~~ | ~~`param-sensitivity`~~ | ~~sensitivity slider: 1 → Apply, then 20 → Apply~~ | ~~sensitivity byte (1-20)~~ | **NOT ON DEVICE** |
| ~~3~~ | ~~`param-scroll`~~ | ~~scroll-speed slider: 1 → Apply, then 10 → Apply~~ | ~~scroll-speed byte (1-10)~~ | **NOT ON DEVICE** |
| ~~4~~ | ~~`param-dblclick`~~ | ~~double-click slider: 830 → Apply, then 200 → Apply~~ | ~~debounce field (16-bit ms?)~~ | **NOT ON DEVICE** |
| ~~5~~ | ~~key-fwd-keyb~~ |, |, | decoded from Linux |
| ~~6~~ | ~~key-back-media~~ |, |, | decoded from Linux (function tags) |
| ~~7~~ | ~~key-disable~~ | any button -> Disable | disable encoding | still unknown; a 30 s capture would settle it |
| ~~8~~ | ~~`macro-record-shortcut`~~ | ~~record keyboard shortcut, save~~ | ~~macro blob format (`AA`->`A7`->`A8` trio)~~ | **SOLVED** — fully reversed from OemDrv (Ghidra): step encoding, payload wrapper, multi-frame chunking; see PROTOCOL.md |
| ~~9~~ | ~~`macro-assign`~~ | ~~assign macro to thumb button~~ | ~~assignment linkage~~ | **SOLVED** — `F3 [id] [mode] [times] 00` slot record on the COMMIT frame; upload sequence in PROTOCOL.md |

Settings that produce ZERO new frames during capture are Windows-side
only, document and skip them (Linux has native pointer/scroll
acceleration).

Already-decoded segments (do not redo): startup burst, DPI writes,
mode switching for all seven effects, brightness slider, Restore
button, commit-frame behavior, **all simple key remaps** (commit-frame
binding table + function tags; see PROTOCOL.md).

## Decode workflow

```sh
python3 tools/pcap_frames.py captures/<segment>.pcap
```

Then correlate:

1. List OUT frames chronologically; match their count/order to your
   clicks.
2. Frames matching known families (`A0 01 xx` settings, `A1 02` init,
   `A4 03` params, commit) are already understood, tag and skip.
3. Anything NEW is the payload you came for. Diff it against the same
   frame from the previous segment: changed bytes = encoded value.
4. Two captures whose inputs differ in exactly one option isolate a
   field with certainty.
5. Write findings into PROTOCOL.md immediately (opcode table +
   payload sketch), including which byte positions stayed constant.

Known unknowns at time of writing:

| Topic | Hint |
|---|---|
| ~~Macro step data~~ | **SOLVED** — full upload protocol + step encoding + `.mly` format reversed (see PROTOCOL.md macro sections) |
| Class tags `90`/`92`/`f3` | `90`/`92` decoded (volume/mute); `f3` = macro binding record (`F3 [id] [mode] [times] 00`) |
| Commit payload `b5/b6/c8` | permanent binding-slot residents; owners unknown |

## Pitfalls (all encountered live)

* Wrong usbmon bus (device moved ports) -> zero mouse frames captured;
  verify with a movement wiggle + file growth first.
* Stale libvirt hostdev pin -> passthrough silently fails; keep the
  VM definition matching by vendor/product only (no address).
* Stale pip-installed copy shadowing the working tree -> test via
  `python3 -m x17blake` from the repo, or reinstall editable.
* Direction/endpoint fields in classic-pcap usbmon headers live at
  byte offsets 9/10, NOT packed bits at offset 8, use
  `tools/pcap_frames.py`, which handles both formats correctly now.
* The engine only re-renders after a fresh INIT + parameter bank;
  bare SETs update storage but can leave visuals stale.
