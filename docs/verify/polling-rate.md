# Verified: polling rate

**Status:** verified
**Date:** 2026-08-25

## Protocol facts

| Item | Detail |
|---|---|
| Storage | settings-frame byte [33] |
| Encoding | raw value maps directly to Hz |
| Factory value | raw 0x03 = 1000 Hz |

| Raw | Hz |
|-----|-----|
| 0x00 | 125 |
| 0x01 | 250 |
| 0x02 | 500 |
| 0x03 | 1000 |

## Evidence (per-transition pcaps)

One file per Apply, Parameter -> Polling Rate dropdown only. Each file
produced exactly one SET frame on EP3 OUT:

| File | Transition | Raw | Hz | Match |
|------|-----------|-----|----|-------|
| `polling-1000-to-500.pcap` | 1000->500 | 0x02 | 500 | yes |
| `polling-500-to-250.pcap` | 500->250 | 0x01 | 250 | yes |
| `polling-250-to-125.pcap` | 250->125 | 0x00 | 125 | yes |

Factory default (0x03 = 1000 Hz) confirmed by `x17blake show` read-back.
OemDrv sends it on first open but was suppressed in the bundled
`param-polling.pcap` because the device was already at 1000 Hz.

## Live Linux verification

```sh
$ python3 -m x17blake polling 500
polling -> 500 Hz: applied (1 byte(s) changed)
verified: byte33=0x02 => 500 Hz

$ python3 -m x17blake polling 1000
polling -> 1000 Hz: applied (1 byte(s) changed)
verified: byte33=0x03 => 1000 Hz
```

Value persists across re-enumeration.

## Notes

Polling rate does NOT change DPI or sensitivity. It changes how often the
mouse reports movement (125 Hz = 8 ms interval, 1000 Hz = 1 ms). No
change in cursor distance-per-inch is expected; only latency and
smoothness are affected. The USB descriptor `bInterval` stays at 1 ms
(1000 Hz max). The firmware throttles report generation, not the
descriptor.

## Related code

`protocol.POLLING_RATES`, `protocol.set_polling()`, `cli.cmd_polling`.
