# x17blake

Linux configurator for the Fantech X17 Blake gaming mouse
(Wings Tech `2ea8:2203`), reverse engineered from the Windows driver
package. Pure Python stdlib; no dependencies.

Status: protocol probing phase. See [PROTOCOL.md](PROTOCOL.md).

## Install (development)

```sh
sudo cp udev/70-x17blake.rules /usr/lib/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
pip install .
```

## Usage

```sh
x17blake show                  # pretty status panel (--json for scripts)
x17blake info                  # hidraw nodes

# DPI
x17blake dpi 1600              # set dpi of the ACTIVE stage
x17blake stage 3 2000          # set stage 3

# Lighting (effects: pulsating_rgb_cycle, pulsating, permanent, color_change,
#  single_color_marquee, multi_color_marquee, ripple, trigger, heartbeat, off)
x17blake led ripple --brightness 5 --speed 1
x17blake led permanent --color FF0000
x17blake color 00FF00          # solid-color shortcut (all slots)

x17blake lod 2                 # lift-off distance 1-3
x17blake profile 2             # profile slot 1-5

# Safety
x17blake backup [label]        # snapshot device state to ~/.config/x17blake/
x17blake restore latest.json   # dry-run diff; add --yes to apply
x17blake reset --yes           # factory reset (fixes bindings/LED state)
```

Every mutating command auto-saves a backup first. Writes are restricted
to verified field offsets — raw/unknown-field writes require explicit
override and never happen through normal commands.

No dependencies, no daemon, no root (with the shipped udev rule).

## Roadmap

- [x] Protocol dialect + transport fully decoded
- [x] Setters with read-back verification + safety layer
- [x] Factory reset / recovery path (proven live)
- [ ] Button remapping (A7 channel layout)
- [ ] Polling rate control
- [ ] TUI frontend (on top of the CLI library layer)
- [ ] RPM packaging, COPR
