# Verified: settings readout / device info

**Status:** ✅ tested · **Date:** 2026-08-23/24

## What it proves

The host can enumerate the device, open its config channel without
root (udev `uaccess`), and decode the full 64-byte settings frame.

## Protocol facts

* Device discovery: `/sys/class/hidraw/*/device/uevent` contains
  `HID_ID=0003:00002EA8:00002203`; the config interface is the one with
  `bInterfaceNumber=01` (interface 0 is the boot-mouse channel).
* GET request: `04 A0 01 01 <zeros…>` written to EP3 OUT.
* Reply: settings frame starting `04 A0 01 01`, magic `01 02 a5`
  at [4..6] and `02 00 a5` at [34..36] — both required, or the packet
  is the trailing echo/junk frame.
* Payload layout documented in PROTOCOL.md.

## Test procedure & evidence

```sh
$ x17blake info
/dev/hidraw1  interface=0
/dev/hidraw2  interface=1

$ x17blake show
Fantech X17 Blake (/dev/hidraw2)
  profile   : 1
  dpi       : *1:500   2:1200   3:1600   4:2000   5:2400   6:3000   7:4000
  lift-off  : 2
  led       : ripple  brightness=0 speed=0
  colors    : 1:FF0000  2:00FF00  ...
```

Observed values matched the mouse's actual state at every read across
both test days; repeated reads are byte-stable.

## Related code

`x17blake/hidraw.py` (transport), `x17blake/device.py::read`,
`x17blake/protocol.py::parse_settings`.
