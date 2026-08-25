# Lift-off distance

**Status:** not supported on this mouse
**Date:** 2026-08-25

## Why it's not adjustable

The X17 Blake uses the PixArt PMW3325 sensor, which has a fixed LOD of
approximately 1.1 mm. This is not a firmware setting the host can change.

The Sharkoon Light2 200 (same VID:PID 2ea8:2203) uses the PMW3389 and
does expose adjustable LOD (1-3 mm) via its driver software. The X17
Blake's OemDrv does not have an LOD slider. The frame layout in
PROTOCOL.md was originally copied from the Sharkoon reference and labeled
byte 33 as LOD, but that byte is actually the polling rate.

## What happened on 2026-08-23

`x17blake lod 1-3` wrote values 0x02/0x03/0x04 to byte 33 and
read-back confirmed the device stored them. This looked like successful
LOD adjustment. In reality it was setting the polling rate to 500/1000 Hz.
No physical lift test was performed at the time.

## Related code

`protocol.set_polling`, `cli.cmd_polling`. The `set_lift_off_distance`
function and `lod` subcommand have been removed.
