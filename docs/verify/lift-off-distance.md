# Verified: lift-off distance

**Status:** ✅ verified · **Date:** 2026-08-23

## Protocol facts

| Item | Detail |
|---|---|
| Storage | settings-frame byte [33] |
| Encoding | raw = UI level + 1 (UI 1/2/3 -> 0x02/0x03/0x04) |
| Factory value | raw 3 (UI level 2), matches `Cfg.ini DefLOD=2` |

## Test procedure & evidence

```sh
$ x17blake lod 3
lift-off distance: -> UI level 3 (raw 4)
verified

$ x17blake lod 2
lift-off distance: -> UI level 2 (raw 3)
verified
```

Round-trip 2->3->2 executed live with read-back after each write;
both transitions confirmed in the returned frame. Value persisted
across subsequent replug.

Note: a hardware review (frontum.co.uk) claims LOD is fixed at ~3 mm
on this model; the vendor protocol nevertheless exposes three levels,
and the setting sticks in the frame, treat the physical effect of
each level as uncharacterized.

## Related code

`protocol.set_lift_off_distance`, `cli.cmd_lod`.
