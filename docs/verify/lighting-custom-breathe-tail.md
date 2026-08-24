# Verified: custom breathe / tail modes

**Status:** ✅ tested end-to-end · **Date:** 2026-08-24

## Protocol facts

These modes use the same settings-frame write as every other mode
(effect id 2 = custom breathe, id 4 = tail): no dedicated opcodes.
They only render when:

1. Byte [41] (color-slot enable mask) carries `0x7F`, leaving it 0
   makes both modes render dark even though the write is accepted.
2. The commit frame matches the vendor layout, including payload
   bytes `0xB5 @32`, `0xB6 @37`, `0xC8 @52`.

Both facts were recovered from a labeled usbmon capture of OemDrv
performing the same clicks (`tools/pcap_frames.py` decodes it).

## How they were confirmed working in OemDrv first

USB passthrough to a Windows 11 VM (virt-manager), official OemDrv:
Tail and Custom Breathe visibly rendered there, proving engine
capability before any host-side attempt.

## Test procedure & evidence

```sh
x17blake led tail                                    # rendered
x17blake led custom_breathe --brightness 4           # rendered
```

Both applied with rainbow palette; user confirmed visible animation
for each. Read-back verified effect ids 4 and 2 respectively.

Debug trail that located the fix: byte-identical bare SETs still
rendered dark until byte[41]=0x7F and vendor-commit bytes were added;
a movement-reactive theory for Tail was disproven along the way.

## Related code

`protocol.COLOR_SLOTS_ALL`, `cli.cmd_led` (sets f[41]),
`protocol.build_commit`.
