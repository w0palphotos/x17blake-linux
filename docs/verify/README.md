# Verification index

Per-feature proof documents. Each records the protocol facts behind the
feature, the exact test commands, and the observed result from live
sessions on hardware `2ea8:2203` (Fantech X17 Blake, bcdDevice 1.04,
Fedora 44, kernel hidraw transport).

| Document | Feature | Result |
|---|---|---|
| [settings-readout.md](settings-readout.md) | Read settings / device info | ✅ |
| [dpi.md](dpi.md) | DPI stages & active stage | ✅ end-to-end |
| [lift-off-distance.md](lift-off-distance.md) | Lift-off distance (not supported) | fixed ~1.1 mm |
| [backup-restore-reset.md](backup-restore-reset.md) | Backup / restore / factory reset | ✅ proven in recovery |
| [lighting-core.md](lighting-core.md) | chroma / neon / breathe / steady / off, brightness, colors | ✅ end-to-end |
| [lighting-custom-breathe-tail.md](lighting-custom-breathe-tail.md) | custom breathe / tail modes | ✅ end-to-end |
| [color-depth.md](color-depth.md) | Effective color resolution | ✅ characterized |
| [keys-remapping.md](keys-remapping.md) | Button remapping (keyboard + special functions) | ✅ end-to-end |
| [windows-only-settings.md](windows-only-settings.md) | Double-click / scroll speed / sensitivity | NOT ON DEVICE |

Shared transport facts used everywhere (details in
[PROTOCOL.md](../../PROTOCOL.md)):

* Config channel = interface 1 -> `/dev/hidrawN`; writes go out as
  64-byte interrupt OUT frames on EP3, replies arrive on EP2 IN.
* Frame envelope: `[0x04][A0 01][cmd][payload...]`.
* Every transaction yields two packets: the response plus a trailing
  echo/junk frame, clients must validate both magic fields.
