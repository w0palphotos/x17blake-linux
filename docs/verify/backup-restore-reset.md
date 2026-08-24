# Verified: backup / restore / factory reset

**Status:** ✅ proven in recovery · **Date:** 2026-08-23/24

## Protocol facts

| Operation | Frames |
|---|---|
| Backup source | GET frame (`04 A0 01 01…`), reply stored as hex JSON in `~/.config/x17blake/` |
| Restore | SET frame rebuilt from backup, `validate=False`, gated by `--yes` |
| Factory reset | `04 A0 01 02 \| 02 02 A5 \| zeros(+B5/B6/C8)` — the vendor "Restore button" frame, sourced from the Sharkoon Light² 200 capture of the same platform |

The commit variant carries payload bytes 0xB5@32, 0xB6@37, 0xC8@52;
sent alone it acts as a config reload/recovery trigger.

## Recovery proven live (the incident)

Early experiments wrote invalid effect ids (Sharkoon's id 9 does not
exist on this firmware), which killed the lighting engine and two
button bindings. Neither was visible in the settings frame — the block
stayed byte-pristine while the engine was wedged.

Recovery sequence executed:

```sh
x17blake reset --yes      # factory-reset frame
# unplug 5 s -> replug
```

Result: back thumb button and scroll-down restored, LED engine revived.
Confirmed twice; a third attempt after deeper corruption did not
revive lighting until the full OemDrv session (Windows VM) rewrote
config — see lighting-custom-breathe-tail.md for that chapter.

## Safety rails added because of it

* Every mutating command auto-saves `auto-prewrite` backup first.
* Writes restricted to verified offsets (`state.MUTABLE_OFFSETS`);
  unknown-field writes raise `SafetyError` unless explicitly forced.
* `restore` defaults to dry-run diff output.

## Related code

`state.py` (backup/restore/guardrails), `cli.cmd_backup/cmd_restore/cmd_reset`,
`protocol.build_factory_reset/build_commit`.
