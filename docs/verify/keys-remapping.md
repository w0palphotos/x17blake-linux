# Button remapping — verified live from Linux

Feature: `x17blake keys bind|clear|show`. Everything below was proven on
hardware `2ea8:2203` on 2026-08-24 **without any Windows VM capture** —
the wire format came from earlier OemDrv pcaps, and every semantic
(slot ownership, function meanings) was established by writing
candidate records from Linux and observing the effect.

## Protocol facts

* The commit frame doubles as the button-binding carrier: offsets 22-63
  are 5-byte slots at bases 22, 27, 32, 37, 42, 47, 52. Permanent
  residents `b5@32 / b6@37 / c8@52` are factory wheel-up / wheel-down /
  LED-cycle assignments, not protocol magic.
* Record formats:
  * `fc 00 <HID>` — plain keyboard key (`fc 00 14` = Q)
  * `fc 01 <HID>` — Ctrl-modified key (`fc 01 13` = Ctrl+P)
  * `<T> 00 00 00 00` — built-in function (see table)
* Slot ownership: 27=forward, 22=back, 42=dpi-, 47=dpi+; slot 57
  accepts records but its button is unidentified.
* GET replies never contain bindings — host-side state is the only
  source of truth; a commit write redefines the whole table.
* Special-function records emit no button-press notify on EP2 IN;
  keyboard-class bindings echo as `[01][class][00][code]`.

## Function table (relocate-and-press experiments)

| Tag | Function | Evidence |
|-----|----------|----------|
| 0x90 | volume up | user-observed, two independent rounds |
| 0x91 | volume down | ditto |
| 0x92 | mute | ditto |
| 0x93 | play/pause | ditto |
| 0x94 | stop (inferred) | inert in test conditions |
| 0x95 | previous track | ditto |
| 0x96 | next track | ditto |
| 0xB5 | scroll up | forward-slot relocation |
| 0xB6 | scroll down | forward-slot relocation |
| 0xC8 | lighting-mode cycle | forward-slot relocation |

Tags 0x97-0x9A emit keyboard-like output (`98`=Mod+R, `99`=Mod+F,
`9A`='d') — separate shortcut space, uncatalogued.

## Commands used and results

```sh
$ x17blake keys bind forward --key x
bound forward -> x; current table:
  forward              -> x (keyboard)
# pressing Forward typed "x" into the terminal          -> PASS

$ x17blake keys clear --all
cleared 2 binding(s); ...
# Forward/Back immediately behaved factory-default      -> PASS

$ x17blake keys bind back --special mute
# pressing Back toggled mute (OS volume OSD)            -> PASS

$ x17blake preset apply initial-factory --yes
restored 0 binding(s) from preset                       -> PASS
```

Safety behavior verified:

* auto-backup before every binding write
* writes restricted to verified slots unless `--experimental`
* resident slots (b5/b6/c8 positions) never written implicitly
* empty-table commit restores stock behavior instantly; bindings
  survive device re-enumeration (observed during crash-recovery test)

## Known limitations

* Mouse-button targets (bind to right-click etc.) have no known wire
  encoding yet — Cfg.ini codes are UI-namespace only.
* Disable tag, macro step encoding, polling-rate opcode: open.
