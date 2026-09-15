# Mario stimuli, simplified

A copy of the gym-retro integration for Super Mario Bros (NES) used in the
Courtois NeuroMod *mario* dataset, with the same level savestates, scenario and
RAM variable map, but a **visually simplified ROM**: every non-interactive
background detail is transparent, and every object the player interacts with
is drawn as a flat square whose colour encodes its semantic category.

The ROM plays exactly like the original. Participant replays (`.bk2`) and
savestates recorded on the original ROM run byte-for-byte identically on it
(only the rendered image differs), so the simplified version can be used as a
visual-complexity control for both human and AI gameplay.

![original vs simplified](docs/original_vs_simplified.png)

See [docs/METHOD.md](docs/METHOD.md) for the full description of the method,
its verification and its known limitations.

## Colour legend

| Category | Colour | Objects |
|---|---|---|
| background | sky blue | everything non-interactive (transparent) |
| terrain | brown | ground, stairs, hard blocks, pipes, tree and mushroom ledges, cloud terrain, cannons, bridges, used blocks, moving platforms, springboards |
| brick | grey | breakable bricks |
| ?-block | orange | question blocks, sprite of a bumped block |
| coin | yellow | coins in the level and coins popping out of blocks |
| item | green | mushroom, 1-up, fire flower, star, vine |
| enemy | red | every enemy and enemy projectile |
| Mario | white | the player (flashes white / green / orange with star power) |
| fire Mario | pale pink | Mario after a fire flower, and his fireballs |
| goal | purple | flagpole, ball, flag, axe |

## Contents

| Path | What it is |
|---|---|
| `SuperMarioBros-Nes/rom.nes` | the simplified ROM (git-annex) |
| `SuperMarioBros-Nes/rom.sha` | sha1 of the ROM body (without iNES header), as gym-retro expects |
| `SuperMarioBros-Nes/Level*.state` | level savestates, unchanged from `mario.stimuli` |
| `SuperMarioBros-Nes/data.json`, `scenario.json`, `metadata.json` | RAM variables, reward/done definition, agent benchmarks, unchanged |
| `code/simplify_rom.py` | builds the simplified ROM from the original ROM (the tile and colour tables live here) |
| `code/verify_replays.py` | replays `.bk2` recordings on two ROMs and checks RAM identity and savestate portability |
| `code/survey_sprite_tiles.py` | measures which sprite tile belongs to which object, used to build the sprite table |
| `code/fix_state_palette.py` | rewrites the palette stored inside a mid-level savestate (not needed for the states here) |
| `generate_sublevels.py` | original helper that regenerates level states |

## Rebuilding the ROM

```
python code/simplify_rom.py /path/to/original/rom.nes SuperMarioBros-Nes/rom.nes
tail -c +17 SuperMarioBros-Nes/rom.nes | sha1sum | cut -d' ' -f1 > SuperMarioBros-Nes/rom.sha
```

The original ROM is the one annexed in `mario.stimuli`
(md5 `811b027eaf99c2def7b933c5208636de`). The current simplified ROM has md5
`6d5c5d9971098043967715b6e86d8cce`.

## Checking a ROM against recordings

```
python code/verify_replays.py integrations/SuperMarioBros-Nes-orig integrations/SuperMarioBros-Nes-simple sub-01_ses-001_task-mario_level-w1l1_rep-000.bk2
```

where each integration folder holds a `rom.nes` next to copies of this repo's
`*.json` and `*.state` files. Requires stable-retro.
