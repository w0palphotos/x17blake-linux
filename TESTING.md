# Testing without installing

Everything here runs straight from the source tree. The driver is pure
Python stdlib — there is nothing to compile.

## Portability notes for other machines

- **OS**: Linux only today. The transport opens `/dev/hidraw*` and reads
  `/sys/class/hidraw` directly. Porting elsewhere means swapping
  `x17blake/hidraw.py` for a hidapi backend; everything above it
  (`protocol.py`, `device.py`, `state.py`, `cli.py`) is OS-neutral.
- **WSL2**: stock kernels lack hidraw, but `usbipd-win` can attach the
  mouse to WSL and it then appears as a normal hidraw device. Same udev
  rule applies inside WSL if you run udev there.
- **Python**: >= 3.9, no third-party packages.
- **Permissions**: without the udev rule every device open fails with
  EACCES — that is expected; install the rule or run under sudo for a
  one-off test.

Everything below assumes Linux with the mouse plugged in.

## 0. One-time prerequisite: udev rule

HID raw devices are root-only by default. Install the shipped rule once
so your user can talk to the mouse:

```sh
sudo cp udev/70-x17blake.rules /usr/lib/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

(Re-plug the mouse afterwards if permission is still denied.)

## 1. Run directly from the source tree (recommended)

```sh
cd ~/Projects/x17blake-linux
python3 -m x17blake show
```

That's it. `python3 -m x17blake <command>` always executes YOUR working
tree — every edit applies instantly, nothing is copied anywhere.

## 2. Isolated environment (venv)

If you want isolation from system packages:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .          # editable: tracks the working tree
x17blake show
deactivate                # when done; system stays untouched
```

`pip install -e .` needs `setuptools` available; on minimal Fedora
images use method 1 instead.

## 3. Checking which code your `x17blake` command runs

If you ever installed with `pip install .`, the console script uses a
FROZEN COPY in site-packages — it will not see later edits. Symptoms:
your fixes "don't work". Diagnose:

```sh
which x17blake                                   # ~/.local/bin/x17blake ?
python3 - <<'EOF'
import x17blake, inspect
print(inspect.getfile(x17blake))
EOF
```

- Path inside `~/Projects/x17blake-linux/` -> working tree (good)
- Path inside `site-packages` -> stale copy; remove it:

```sh
rm -rf ~/.local/lib/python3.*/site-packages/x17blake*
echo "$HOME/Projects/x17blake-linux" > ~/.local/lib/python3.*/site-packages/x17blake.pth
```

(The `.pth` file makes site-packages point at your working tree — an
editable install without pip.)

## 4. Safety model — what commands may write

Currently writable (verified safe):

```sh
x17blake dpi <200..10000>      # active stage
x17blake stage <1-7> <dpi>
x17blake lod <1|2|3>
x17blake backup [label]
x17blake restore <file> [--yes]
x17blake reset --yes           # factory reset (recovery path)
```

Deliberately absent: `led` / `color` / `profile`. On this firmware those
fields are NOT controlled by the settings frame — writing them corrupts
the lighting engine until `reset`. They return once the true lighting
opcodes are decoded (see REVERSING.md).

Every mutating command auto-saves a backup to
`~/.config/x17blake/` before touching the device.

## 5. Quick smoke test checklist

```sh
python3 -m x17blake info        # two hidraw nodes listed?
python3 -m x17blake show        # parses without error?
python3 -m x17blake probe --roundtrip   # "roundtrip: OK"?
python3 -m x17blake dpi $(python3 -c "import sys;sys.path.insert(0,'.');from x17blake import protocol;print(1200)")
```

If all four pass, transport, parser, guardrails and write+verify work.
