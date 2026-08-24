# USB capture guide — recording and mapping MCU frames

How to systematically record what the vendor Windows tool sends to the
mouse, so new features can be decoded without guesswork. This workflow
produced every opcode in [PROTOCOL.md](../PROTOCOL.md).

## One-time / per-session setup

```sh
lsusb | grep -i 2ea8        # NOTE THE BUS NUMBER — it moves between ports!
sudo modprobe usbmon        # no-op if already loaded
sudo tcpdump -i usbmon<N> -s0 -w captures/<segment>.pcap
```

* `<N>` = the bus from `lsusb` (e.g. Bus 003 -> `usbmon3`). **The mouse
  changes buses whenever it is replugged into a different port** — this
  has silently wasted a capture before; always re-check.
* Sanity check within ~10 s of starting: touch the mouse / click once,
  then `ls -la captures/<segment>.pcap` — the file must be growing.
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
4. Never trust one surprising result — repeat the segment twice.
5. Start tcpdump BEFORE launching/using OemDrv for that action, stop
   right after (Ctrl-C) — keeps files small and segments clean.

## Segment checklist

| # | Segment name | Action inside OemDrv | Unlocks |
|---|---|---|---|
| 1 | `polling-<rate>` | each polling-rate option, one file each | polling-rate opcode |
| 2 | `button-fwd-keyb` | remap Forward button -> keyboard key "B", Apply | `A7` binding layout |
| 3 | `button-back-media` | remap Back -> media key, Apply | key-class codes |
| 4 | `button-disable` | set any button -> Disable | disable encoding |
| 5 | `button-defaults` | Restore defaults on key page | reset vs A7 interplay |
| 6 | `macro-record` | record 3-click macro, save, assign | macro blob format |
| 7 | `cb-color-picker` | Custom Breathe -> pick dark red, Apply | color quantization check |
| 8 | `debounce` | Parameter page debounce options, if present | extra settings bytes |

Already-decoded segments (do not redo): startup burst, DPI writes,
mode switching for all seven effects, brightness slider, Restore
button, commit-frame behavior.

## Decode workflow

```sh
python3 tools/pcap_frames.py captures/<segment>.pcap
```

Then correlate:

1. List OUT frames chronologically; match their count/order to your
   clicks.
2. Frames matching known families (`A0 01 xx` settings, `A1 02` init,
   `A4 03` params, commit) are already understood — tag and skip.
3. Anything NEW is the payload you came for. Diff it against the same
   frame from the previous segment: changed bytes = encoded value.
4. Two captures whose inputs differ in exactly one option isolate a
   field with certainty.
5. Write findings into PROTOCOL.md immediately (opcode table +
   payload sketch), including which byte positions stayed constant.

Known unknowns at time of writing:

| Topic | Hint |
|---|---|
| `A7` frames | key/binding upload channel; builder at OemDrv.exe `0x43d240`; carries per-key records during macro/key-list processing |
| Polling rate | `Cfg.ini` hint `DR=0x500`; likely a short dedicated frame |
| `AA 00` frame | sent near macro processing; purpose unclear |
| Commit payload `B5/B6/C8` | required for full render updates; semantics unknown |

## Pitfalls (all encountered live)

* Wrong usbmon bus (device moved ports) -> zero mouse frames captured;
  verify with a movement wiggle + file growth first.
* Stale libvirt hostdev pin -> passthrough silently fails; keep the
  VM definition matching by vendor/product only (no address).
* Stale pip-installed copy shadowing the working tree -> test via
  `python3 -m x17blake` from the repo, or reinstall editable.
* Direction/endpoint fields in classic-pcap usbmon headers live at
  byte offsets 9/10, NOT packed bits at offset 8 — use
  `tools/pcap_frames.py`, which handles both formats correctly now.
* The engine only re-renders after a fresh INIT + parameter bank;
  bare SETs update storage but can leave visuals stale.
