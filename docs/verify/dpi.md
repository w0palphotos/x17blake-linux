# Verified: DPI stages & active stage

**Status:** ✅ tested end-to-end · **Date:** 2026-08-23/24

## Protocol facts

| Item | Detail |
|---|---|
| Stage values | bytes [9..29], 7 triplets `[0x00, regX, regY]` |
| Active stage | byte [7] (0-based) |
| DPI encoding | sensor-register lookup from `Cfg.ini` `DPISET`<->`DPIHW`, 54 pairs: 200->0x04 … 10000->0x7D (step 100) |
| Write path | SET frame (`cmd=02`) + commit frame; read-back verify |

Sample anchors: 500->0x0B, 800->0x12, 1200->0x1B, 1600->0x24,
2000->0x2E, 2400->0x37, 3000->0x45, 4000->0x5C, 10000->0x7D.

## Test procedure & evidence

```sh
$ x17blake dpi 1200
dpi stage 1 -> 1200: applied (2 byte(s) changed)
verified: stage 1 = 1200 / 1200 dpi

$ x17blake stage 1 800      # -> verified
$ x17blake stage 1 500      # -> verified
```

* Live round-trips performed repeatedly on stages 1 and 2
  (500 <-> 800 <-> 1200), each confirmed by fresh GET.
* Cursor speed change felt in desktop use matched the written value.
* Values persist across unplug/replug (onboard memory).
* Invalid inputs rejected with the valid-range list
  (`200..10000 step 100`).

## Related code / addresses

* CLI: `x17blake/cli.py::cmd_dpi/cmd_stage`
* Mutators: `protocol.set_stage`, `protocol.dpi_to_register`
* Windows reference: builder cluster at OemDrv.exe `0x43ce10–0x43d630`
  (see REVERSING.md); register table source `Cfg.ini` lines 61-62.

## Known limits

Effective max is 10,000 DPI per vendor table despite some listings
advertising 12,000 (see README spec section).
