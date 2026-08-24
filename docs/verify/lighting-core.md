# Verified: lighting core (chroma / neon / breathe / steady / off)

**Status:** ✅ tested end-to-end · **Date:** 2026-08-24

## Protocol facts

| Field | Byte | Values |
|---|---|---|
| Effect id | [37] | 0 chroma, 1 neon, 3 breathe, 5 steady, 6 off |
| Speed | [38] | 0-2 observed |
| Brightness | [39] | 0-4 (0 = dark) |
| Enable | [40] | write 1 |
| Color-slot mask | [41] | 0x7F = all seven slots |
| Palette | [42..62] | 7 x RGB |

Session choreography required per command:

1. INIT handshake: `A1 02 {00,01,02,03}`, sent twice
2. Parameter bank: `A4 03` frames for params 1..6 then 0
   (param 0 payload = enable + brightness; templates captured
   verbatim from OemDrv in `protocol.LED_PARAM_TEMPLATES`)
3. Settings-frame SET carrying effect/speed/brightness/en/mask/palette
4. Commit frame `04 A0 01 02 | 02 02 A5 | zeros + B5/B6/C8`

Without step 2 the engine keeps rendering its previous state — bare
follow-up SETs update storage but not the render.

## Test procedure & evidence

```sh
x17blake led chroma                                  # rainbow cycle seen
x17blake led neon                                    # seen
x17blake led breathe --brightness 4                  # pulse seen
x17blake led steady --color FF0000 --brightness 4    # solid red seen
x17blake led off                                     # dark seen
x17blake led steady --color 00FF00 --brightness 3    # dim green seen
```

Every command printed read-back verification matching the request;
each visual change was confirmed by eye at the time of writing.
Palette changes persist across unplug/replug (onboard memory).

## Root-cause note

First-generation attempts used the Sharkoon Light2 200 effect table,
whose ids 5-9 do not exist on Blake. Writing invalid id 9 was what
originally wedged the engine. Ids are now hard-validated to 0..6 so
this class of failure cannot recur through the CLI.
