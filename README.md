# x17blake

Linux configurator for the Fantech X17 Blake gaming mouse
(Wings Tech `2ea8:2203`), reverse engineered from the Windows driver
package. Pure Python stdlib; no dependencies; no daemon.

## Status: work in progress

| Feature                          | State                               |
| -------------------------------- | ----------------------------------- |
| Read settings / device info      | ✅ tested                           |
| **DPI stages & active stage**    | ✅ **tested end-to-end**            |
| Lift-off distance                | ⚠️ implemented, light testing       |
| Backup / restore / factory reset | ✅ proven during recovery           |
| **Lighting: chroma/neon/breathe/steady/off, brightness, colors** | ✅ **tested end-to-end** |
| Lighting: custom breathe / tail  | ✅ tested                           |
| Button remapping                 | ❌ future work                      |
| Polling rate                     | ❌ future work                      |

> **Note:** all lighting modes, DPI stages and recovery tooling are
> verified in daily use. Protocol reference:
> [PROTOCOL.md](PROTOCOL.md).

Should also work on anything sharing the `2ea8:2203` platform
(e.g. Sharkoon Light² 200) — untested reports welcome.

## Install

```sh
git clone https://github.com/w0palphotos/x17blake-linux.git
cd x17blake-linux

# one-time: allow your user to talk to the mouse
sudo cp udev/70-x17blake.rules /usr/lib/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# run without installing anything:
python3 -m x17blake show
```

Optional editable install (`pip install -e .`) provides the
`x17blake` command; see [TESTING.md](TESTING.md) for venv details and
stale-copy diagnostics.

## Usage

```sh
x17blake show                  # pretty status panel (--json for scripts)
x17blake info                  # list hidraw nodes

x17blake dpi 1600              # set dpi of the ACTIVE stage (200-10000)
x17blake stage 3 2000          # set stage 1-7 individually
x17blake lod 2                 # lift-off distance 1-3

# Lighting — modes: chroma, neon, custom_breathe, breathe, tail,
# steady, off — plus brightness 0-4 and colors
x17blake led steady --color FF0000 --brightness 4
x17blake led chroma
x17blake led tail
x17blake led off

# Color tip: channels are effectively ON/OFF on this firmware —
# use --brightness 0-4 for darker shades, not dark hex values.

x17blake backup [label]        # snapshot state to ~/.config/x17blake/
x17blake restore latest.json   # dry-run diff; add --yes to apply
x17blake reset --yes           # factory reset (recovery path)
```

Every mutating command auto-backups first and writes only to
verified-safe fields; unknown-field writes are refused at the protocol
layer.

## Developing on another machine

Requirements: **Linux**, Python ≥ 3.9, any USB host controller.
Windows/macOS are not supported yet (the transport uses Linux
`hidraw`/sysfs directly).

```sh
sudo dnf install git python3          # Fedora
git clone https://github.com/w0palphotos/x17blake-linux && cd x17blake-linux
python3 -m x17blake info              # verify device access
```

That's the whole build — there is nothing to compile. Code layout:

| File                   | What lives there                                 |
| ---------------------- | ------------------------------------------------ |
| `x17blake/hidraw.py`   | OS transport (hidraw ioctls, frame exchange)     |
| `x17blake/protocol.py` | frame builders/parsers, DPI tables — port target |
| `x17blake/device.py`   | transaction layer + safety validation            |
| `x17blake/state.py`    | backup/restore, mutation guardrails              |
| `x17blake/cli.py`      | argparse CLI                                     |

For reverse-engineering new features start at
[REVERSING.md](REVERSING.md); test workflow in
[TESTING.md](TESTING.md). Protocol reference:
[PROTOCOL.md](PROTOCOL.md).

## Roadmap

- [x] Lighting: chroma / neon / breathe / steady / off + brightness + colors
- [x] Lighting: custom breathe / tail
- [ ] Button remapping (`A7` channel layout)
- [ ] Polling rate control
- [ ] TUI frontend (on top of the CLI library layer)
- [ ] RPM packaging, COPR
