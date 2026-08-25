# Lift-off distance

**Status:** conflicted (was: verified)
**Original date:** 2026-08-23

## What we thought

Byte 33 was treated as lift-off distance. Raw = UI level + 1, factory raw 3
equals UI 2, matching `Cfg.ini DefLOD=2`. Live round-trip writes 2->3->4
confirmed read-back, so it looked solid.

## Why it's wrong

On 2026-08-25 the `param-polling.pcap` capture showed OemDrv writes
**0x00/0x01/0x02/0x03** to byte 33 when cycling 125/250/500/1000 Hz in the
Parameter page. Factory default 0x03 is 1000 Hz. The earlier LOD test was
therefore setting polling rate, not LOD. The read-back matched because the
device stores any value the host writes.

A hardware review (frontum.co.uk) says LOD is fixed at ~3 mm on this
model. The vendor protocol exposes no known LOD register on the wire.

## Related code

`protocol.set_lift_off_distance` (now aliases `set_polling`), `cli.cmd_lod`.
