# Verified: double-click speed, scrolling speed, mouse sensitivity are Windows-only

**Status:** verified (not on device)
**Date:** 2026-08-25

## Protocol facts

OemDrv's Parameter page exposes three sliders:

| Control | Slider range | Factory default | Windows API |
|---|---|---|---|
| Double-click speed | 200-830 ms (right=fast, left=slow) | 550 | `SPI_SETDOUBLECLICKTIME` |
| Scrolling speed | 1-10 | 3 | `SPI_SETWHEELSCROLLLINES` |
| Mouse sensitivity | 1-20 | 10 | `SPI_SETMOUSESPEED` |

None are stored in the mouse firmware.  The settings frame is byte-for-byte
identical across every slider position; no `A4` param-bank or other new
frame types appear.

## Evidence (per-transition pcaps)

One SET-settings + one COMMIT per Apply.  All eight captures produce
identical frame payloads (verified byte-by-byte):

| File | Control | Position | Frames | Unique payload |
|---|---|---|---|---|
| `dblclick-830.pcap` | Double-click | 830 ms | SET+COMMIT | identical to all others |
| `dblclick-550.pcap` | Double-click | 550 ms (default) | SET+COMMIT | identical |
| `dblclick-200.pcap` | Double-click | 200 ms | SET+COMMIT | identical |
| `scroll-1.pcap` | Scrolling speed | 1 | SET+COMMIT | identical |
| `scroll-5.pcap` | Scrolling speed | 5 | SET+COMMIT | identical |
| `scroll-10.pcap` | Scrolling speed | 10 | SET+COMMIT | identical |
| `sensitivity-min.pcap` | Mouse sensitivity | 1 | SET+COMMIT | identical |
| `sensitivity-max.pcap` | Mouse sensitivity | 20 | SET+COMMIT | identical |

The only difference vs a prior capture at a different polling rate was byte 33
(polling), confirming the settings frame is what OemDrv writes and these
three controls never participate.

## Linux equivalents

| Control | Linux path |
|---|---|
| Double-click speed | Tool-level or desktop setting (GTK `gtk-double-click-time`, KDE double-click interval) |
| Scrolling speed | `libinput scroll-factor`, compositor or `xinput` properties |
| Mouse sensitivity | `libinput AccelSpeed` (range -1.0 to 1.0), `xinput set-prop` for Xorg |

## Related code

No firmware code needed.  Linux-native configuration via compositor / libinput.
