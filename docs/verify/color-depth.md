# Characterized: effective color resolution

**Status:** ✅ characterized · **Date:** 2026-08-24

## Finding

The interface accepts full 8-bit-per-channel RGB (the "16.8 million
colors" marketing figure), but **rendered output is quantized: each
channel behaves as effectively ON/OFF**. The real dimmer is the
global brightness byte (0-4).

## Experiment

`tools/exp_color_ladder.py` alternates color pairs in steady mode
(3 flips x 2 s per side, full vendor session per flip), covering:

* red axis: FF0000 / 7F0000 / 3F0000 / 000000
* green axis: 00FF00 / 007F00
* blue axis: 0000FF / 00007F
* hue step: FF8000 / FF0000

Result on hardware: every dim variant rendered identically to its
full-scale version (FF = 8B = 7F = 3F for the same channel), while
on/off flips and mode animations remained clearly visible. A follow-up
flip test with per-write re-arming confirmed writes land (transitions
blink) but the rendered color does not change — i.e. quantization
happens in the LED engine, not the transport.

## Consequences

* Effective palette ~= 2^3 channel states x 5 brightness levels.
* Darker shades must come from `--brightness`, not dark hex values
  (README carries this tip).
* The CLI still accepts 24-bit hex; the hardware snaps values.

## Reproduce

```sh
python3 tools/exp_color_ladder.py     # watch each pair, note same/different
```
