# x17blake

x17blake is a Linux configuration tool for the Fantech X17 Blake gaming mouse
(Wings Tech `2ea8:2203`). It talks to the vendor HID config interface directly
over hidraw and handles DPI stages, polling rate, lighting, button
remapping, presets and backups. The protocol was reverse engineered from the
Windows driver package. Pure Python stdlib, no daemon, nothing to compile.

<a href="PROTOCOL.md">Protocol notes</a> -
<a href="REVERSING.md">How it was reverse engineered</a> -
<a href="docs/CAPTURE-GUIDE.md">USB capture guide</a> -
<a href="TESTING.md">Testing without installing</a> -
<a href="docs/verify/README.md">Verification log</a>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-linux-lightgrey.svg)](#install)

**Official resources:** [Driver (Windows)](https://cdn.shopify.com/s/files/1/0630/1689/4649/files/Blake_EB__X17_Software_V1.0_19082000.exe?v=1703645864) -
[User Manual (PDF)](https://cdn.shopify.com/s/files/1/0630/1689/4649/files/Blake_X17_UM_23110600.pdf?v=1699339990) -
[FAQ](https://fantechworld.com/pages/blake-x17-faq)

x17blake supports:

- reading and writing all seven DPI stages (200 to 10000) and polling rate
  (125, 250, 500, 1000 Hz)
- every lighting mode the firmware has: chroma, neon, custom breathe, breathe,
  tail, steady color and off, plus brightness and the seven-slot palette
- remapping buttons to keyboard keys, Ctrl combos or built-in functions
  (volume, media transport, scroll, LED mode cycle)
- **keyboard macros**: record real keystrokes (`macro record`), interactive
  text builder (`macro create`), or import Windows `.mly` exports
  (`macro import`); upload protocol fully reversed incl. multi-frame
  chunking (step stream capped at 993 bytes per macro; media keys only
  work as direct button bindings, not inside macros)
- named presets that capture device state and bindings together
- automatic backups before every write, and a factory reset recovery path

Devices sharing the same platform, such as the Sharkoon Light² 200, should
work too. Reports from other hardware are welcome.

## Installation

Run the installer from the source tree:

```sh
git clone https://github.com/w0palphotos/x17blake-linux.git
cd x17blake-linux
./install.sh
```

Without root this installs the `x17blake` command for your user
(package into `~/.local/lib/x17blake`, launcher into
`~/.local/bin/x17blake`). With `sudo ./install.sh` it also installs the
udev permission rule — do that once so your user can talk to the mouse.

Uninstall with `./uninstall.sh` (backups under `~/.config/x17blake/`
are user data and are kept).

### Immutable distros (Silverblue, Aeon, SteamOS, ...)

Never copy the rule into `/usr/lib/udev/rules.d/` — on image-based
distros that path is read-only. Use `/etc/udev/rules.d/`, which stays
writable, takes precedence, and survives OS updates (this is what
`sudo ./install.sh` does):

```sh
sudo cp udev/70-x17blake.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

On NixOS, add the rule line from `udev/70-x17blake.rules` to
`services.udev.extraRules` instead.

Run without installing anything:

```sh
python3 -m x17blake show
```

An editable install (`pip install -e .`) gives you the `x17blake` command.
If that command ever behaves like an older version, [TESTING.md](TESTING.md)
has the stale-copy diagnosis.

## Usage

```sh
x17blake show                  # status panel (--json for scripts)
x17blake info                  # list hidraw nodes

x17blake dpi 1600              # dpi of the ACTIVE stage (200-10000)
x17blake stage 3 2000          # set stage 1-7 individually
x17blake polling 500           # set polling rate (125/250/500/1000)

# lighting: chroma, neon, custom_breathe, breathe, tail, steady, off
x17blake led steady --color FF0000 --brightness 4
x17blake led chroma
x17blake led off

# buttons: keyboard keys or built-in functions
x17blake keys                              # show current bindings
x17blake keys bind forward --key b         # Forward types 'b'
x17blake keys bind back --special mute     # volume_up/down, mute,
x17blake keys bind dpi_plus --special next_track   # play_pause, prev/next,
x17blake keys bind dpi_minus --special scroll_down  # scroll_up/down, led_cycle
x17blake keys bind left --special right_click      # real clicks work too,
x17blake keys clear --all                  # even on the main buttons

# macros: record, build or import, then bind to any button
x17blake macro record ctrl-saver           # record real keystrokes
                                           # (combos work; esc esc or
                                           # ctrl+c finishes)
x17blake macro create my-combo             # interactive text builder
                                           # (also offers record mode)
x17blake macro import x.mly                # import a Windows OemDrv
                                           # macro export
x17blake macro list                        # saved macros
x17blake macro compile my-combo            # inspect the wire encoding
x17blake keys bind dpi_minus --macro-file ~/.config/x17blake/macros/my-combo.macro
x17blake keys bind forward --macro 1       # or a built-in macro ID

x17blake backup [label]        # snapshot state to ~/.config/x17blake/
x17blake restore latest.json   # dry-run diff; add --yes to apply
x17blake reset --yes           # factory reset (recovery path)

# presets capture device state and bindings together
x17blake preset list                       # bundled + your saved ones
x17blake preset apply initial-factory      # dry-run diff; add --yes
x17blake preset save my-setup -d "my daily driver"
```

One color tip: the LED channels are effectively ON/OFF on this firmware,
so use `--brightness 0-4` for darker shades instead of dark hex values.

Every command that writes something saves a backup first and refuses
fields that have not been proven safe on real hardware. Run
`x17blake help <command>` for the full option list of anything.

## Device specifications

Consensus from Fantech regional distributors, retail listings and review
aggregators, cross-checked against the vendor driver config (`Cfg.ini`,
sensor id `0x3325`):

| Spec              | Value                                        |
| ----------------- | -------------------------------------------- |
| Sensor            | PixArt PMW3325 optical                       |
| DPI               | 200-10,000, on-the-fly adjustable            |
| Polling rate      | 125 / 250 / 500 / 1000 Hz                   |
| Tracking          | 100 IPS / 20 G acceleration                  |
| Switches          | Huano, 20 million click lifetime             |
| Buttons           | 7, independently programmable                |
| Lighting          | RGB (4 zones), 7 modes, onboard memory       |
| Cable             | 1.8 m nylon braided                          |
| Dimensions        | 125 × 62 × 42 mm                             |
| Weight            | ~91 g without cable (~96 g with cable)       |

Some marketplace listings advertise a PixArt 3360 sensor, 12,000 DPI,
250 IPS / 50 G tracking and Omron switches. Most retailers and the
driver's own config disagree, and the vendor DPI table exposed by this
driver tops out at 10,000. The seven lighting modes match what we
decoded exactly.

## Requirements and code layout

Linux only today (the transport opens `/dev/hidraw*` directly), Python
3.9+, any USB host controller.

| File                   | What lives there                                 |
| ---------------------- | ------------------------------------------------ |
| `x17blake/hidraw.py`   | OS transport (hidraw ioctls, frame exchange)     |
| `x17blake/protocol.py` | frame builders/parsers, binding codec, DPI tables |
| `x17blake/device.py`   | transaction layer + safety validation            |
| `x17blake/state.py`    | backup/restore, mutation guardrails              |
| `x17blake/cli.py`      | argparse CLI                                     |
| `tools/explore_bindings.py` | relocate-and-press protocol decoder         |
| `tools/probe_slots.py` | one-shot slot to button mapper                   |
| `tools/macro_monitor.py` | live view of macro keystroke output            |
| `tools/macro_watch.py` | dual-interface watcher (button + macro output)   |
| `tools/mly_dump.py`    | debug dump for Windows `.mly` macro files        |

## Roadmap

- [x] Macro support (record / text builder / `.mly` import, multi-frame
      upload; `macro record` is the newest path and still on testing)
- [ ] TUI frontend (on top of the CLI library layer)
- [ ] RPM packaging, COPR

Done already: lighting (all modes), DPI/polling rate, full button
remapping (keyboard keys, built-in functions and real mouse clicks,
including the main clicks themselves), presets, backup/restore/reset.
Evidence for each lives in the [verification log](docs/verify/README.md).

For research work start at [REVERSING.md](REVERSING.md); the wire-level
reference is [PROTOCOL.md](PROTOCOL.md).
