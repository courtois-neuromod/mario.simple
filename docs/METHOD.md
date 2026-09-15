# Building a visually simplified Super Mario Bros with identical game logic

This document describes how the simplified ROM in this repository was made,
why the approach preserves gameplay exactly, how that was verified, and what
its limitations are. It is written to be reusable as the methods section of a
paper.

## 1. Goal

The Courtois NeuroMod *mario* dataset contains hours of Super Mario Bros
gameplay recorded from human participants (as frame-by-frame controller
recordings, `.bk2` files, replayable in a deterministic emulator) together
with fMRI. The same levels are also played by reinforcement-learning agents.
We wanted a second version of the game in which the visual scene is reduced
to its functional content, in order to manipulate visual complexity while
keeping every other aspect of the task constant:

* everything that has no effect on gameplay (clouds, bushes, hills, trees,
  fences, castle decoration, water surface, sea plants, ropes and pulleys,
  fireworks, brick debris) is removed, i.e. rendered as the uniform backdrop;
* everything the player can interact with is drawn as a flat, single-colour
  square, and the colour is a semantic category (terrain, brick, ?-block,
  coin, item, enemy, player, goal) that is identical in every level, whatever
  the original day / night / underground / water palette;
* the game logic, physics, level layouts, enemy behaviour, RAM layout and
  randomness must be untouched, so that existing recordings, savestates and
  RAM-derived variables remain valid on the new ROM, and so that agents and
  humans face exactly the same task.

## 2. Why this is possible: how the NES draws Super Mario Bros

An NES cartridge holds two memories. **PRG-ROM** (32 KB here) contains the
6502 program, the level data, and small data tables. **CHR-ROM** (8 KB)
contains the pixel shapes of 512 8x8 tiles in 2 bits per pixel: 256 tiles for
sprites (moving objects) and 256 for the background. Colour is not stored in
the tiles. Each tile pixel is an index 0-3 into one of eight 4-colour palettes
(4 for background, 4 for sprites) held by the graphics chip (PPU); index 0 is
transparent for sprites and the shared backdrop colour for the background.

The game never reads CHR-ROM: it only tells the PPU which tile to draw where.
Collision, movement, scoring and every other rule operate on *metatile* ids
and object ids in RAM, not on pixels. Palettes are likewise only *written* by
the game (at level load and for a few animations) from small tables in
PRG-ROM, through a write buffer in RAM (`$0300-$03FF`) that is flushed to the
PPU during vertical blank. Nothing in the game reads the palette back.

Two consequences follow. Rewriting CHR-ROM changes what is seen and nothing
else. Rewriting the *palette tables* (and one table that maps metatiles to
tiles) in PRG-ROM changes only the bytes that pass through the PPU write
buffer, again with no effect on game state.

## 3. What was changed

### 3.1 Background tiles (CHR-ROM, pattern table `$1000`)

Super Mario Bros composes the background from 16x16 *metatiles*, each made of
four tiles listed in four tables in PRG-ROM (one table per background
palette; found at CPU `$8B10-$8CC0`). We dumped those tables from the original
ROM and used them to assign every background tile to the block it belongs to
(ground, brick, question block, pipe, cloud, bush, ...), rather than guessing
from its picture. Each tile was then rewritten as either

* **transparent** (all pixels index 0) for decoration, or
* **a solid square** of a chosen palette index (1, 2 or 3) for interactive
  blocks; the index selects the semantic colour through the palettes of
  section 3.3.

The flagpole shaft keeps its thin shape but is recoloured. Text and HUD tiles
are untouched. The full classification is the `BG` table in
`code/simplify_rom.py`.

Two tiles are shared between categories. Tile `$26` is both the fill of the
decorative hills and the inner column of every pipe shaft, and tile `$47` is
both the breakable brick and the wall of the end-of-level castle, so neither
can be both transparent and solid. We therefore also edited the
metatile-graphics table: the two pipe-shaft metatiles use the pipe-edge tile
instead of `$26` (4 bytes), and the seven castle metatiles use the blank tile
(28 bytes), which makes the castle, a purely decorative object, disappear.
This table is read only when the game writes a new screen column into the
PPU write buffer (section 5 confirms that these are the only RAM bytes that
differ).

### 3.2 Sprite tiles (CHR-ROM, pattern table `$0000`)

Every sprite tile below `$F6` becomes a solid square (the floating score
digits `$F6-$FF` are kept). Which index a tile gets depends on which object
draws it, and that was *measured* rather than assumed: the game builds its
sprite list in RAM (`$0200-$02FF`) and keeps, for the player, each enemy
slot, the power-up, fireballs, bumped blocks and misc objects, the offset of
their entries (`$06E4-$06FB`). Replaying 66 participant recordings (3 per
level, all 22 levels of the dataset) on the original ROM and reading these
locations every third frame gives, for each of the 512 sprite tiles, the
object that drew it and the sprite palette it was drawn with
(`code/survey_sprite_tiles.py`). The resulting map covers Mario, 14 enemy
types, the four power-ups, fireballs, coins, hammers, the flag, vines,
platforms, springboards, fireworks and the castle flag.

Because a sprite's palette is chosen by the game per object, tiles of
different categories can share a palette (e.g. the mushroom and the Spiny both
use sprite palette 2). Categories are therefore separated by *index* within a
palette: enemies use index 2, items index 1, platforms index 3, and the
palettes of section 3.3 give each index its colour. Mario's tiles use index 1
because the star-power effect rotates Mario's palette *attribute* through the
four sprite palettes; with index 1 he flashes white / green / green / orange
rather than enemy red.

Four palettes with three indices each give twelve sprite colours, but the
game's own palette assignments crowd some categories into the same palette
(coins popping out of blocks, fireballs, the mushroom and the Spiny all use
sprite palette 2). Where that prevented a category from having its own
colour, we changed the palette the game assigns to the object. Each of these
is a single immediate operand in the drawing routine of that object: the
fireball now uses sprite palette 0 (Mario's) and index 3, coins popping out
of blocks use palette 3 and index 3, the bumped brick uses palette 2 and
index 3 (terrain colour, since no sprite palette has a slot left for the
brick grey), and the bumped question block always uses palette 3 (the
original used palette 1 outside ground areas). The brick debris sprites are
transparent.

### 3.3 Palettes (PRG-ROM data tables)

The game keeps four 32-byte palette sets (water, ground, underground,
castle), three 4-byte variants for snow and mushroom areas, a 12-byte player
palette table (Mario, Luigi, fire Mario), an 8-byte backdrop-colour table, and
two small tables used to animate question blocks and coins by rewriting
background palette 3 every 8 frames. All of these were overwritten so that
every palette index means the same category everywhere:

| index | BG pal 0 | BG pal 1 | BG pal 2 | BG pal 3 | SPR pal 0 | SPR pal 1 | SPR pal 2 | SPR pal 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | item | brick | text (white) | ?-block | Mario | item | item | ?-block |
| 2 | terrain | terrain | terrain | terrain | item | enemy | enemy | enemy |
| 3 | goal | goal | goal | coin | fire Mario | goal | terrain | coin |

The backdrop is sky blue in every area, including underground and night
levels. NES colour indices: backdrop `$22`, terrain `$17`, brick `$10`,
?-block `$27`, coin `$28`, item `$2A`, enemy `$16`, Mario `$30`, fire Mario
and fireballs `$36` (a pale pink, close to Mario's white so the change of
state is visible without breaking the "player" family), goal `$24`. They are
the `C` dictionary at the top of `code/simplify_rom.py`.

### 3.4 Summary of the binary changes

| Region | Bytes changed | Nature |
|---|---|---|
| iNES header | 0 | |
| PRG-ROM code and level data | 0 | |
| PRG-ROM presentation data | 194 | palette tables (158), metatile-graphics table (32), sprite-palette operands (4) |
| CHR-ROM | 5545 | tile shapes |

## 4. Reproducibility

`code/simplify_rom.py ORIGINAL.nes OUTPUT.nes` rebuilds the ROM
deterministically from the original ROM (md5 `811b027eaf99c2def7b933c5208636de`)
and the tables in the script; every PRG patch asserts the original bytes
before writing. The current ROM has md5 `6d5c5d9971098043967715b6e86d8cce`.
The tool used for the earlier, hand-made versions of this ROM (SMB Utility)
is no longer needed.

## 5. Verification

`code/verify_replays.py` replays a participant recording on the original and
the simplified ROM with the same emulator (stable-retro 1.0, `fceumm` core),
starting from the recording's own initial savestate, and compares the full
emulator RAM after every frame. It also saves a state halfway through the run
on the original ROM, loads it into the simplified ROM and replays the
remaining inputs.

Results on recordings from levels 1-1 (including one with fire Mario, star
power and a completed level), 1-2, 1-3, 3-1, 4-2, 5-1 and 8-2 (2800 to 6000
frames each):

* with tile changes only, RAM is byte-identical on every frame;
* with the pipe, castle and palette patches, the only bytes that ever differ
  lie in the PPU write buffer (`$0304-$0359`), on the frames where a screen
  column or a palette is queued;
* with the sprite-palette operands as well, differences also appear in the
  sprite buffer (`$0200-$02FF`, the attribute byte of the affected sprites)
  and in one zero-page scratch byte (`$0004`) in which the block-drawing
  routine hands the palette to a shared helper; nothing outside these
  regions differs on any frame. The sprite buffer, the write buffer and that
  scratch byte are written by the graphics path and never read by game logic;
* savestates taken on either ROM load on the other and track the original
  run to the end; the fceumm savestate contains no tile data and no ROM
  checksum, and states saved on both ROMs at the same frame are
  byte-identical when only tiles differ;
* all RAM-derived variables of `data.json` are therefore identical between
  ROMs, and `.bk2` recordings need no conversion (the recording names the
  game `SuperMarioBros-Nes`, which both integrations use).

Visual checks were made on every level state and on replay frames covering
day, night, underground, water, tree-top, bonus and castle-exterior areas,
including coins, power-ups, star power and fire Mario.

Two pitfalls met during verification are worth recording. First, the NES
core exposes nine buttons (`B, -, SELECT, START, UP, DOWN, LEFT, RIGHT, A`);
a replay script that reads eight drops the A button and produces plausible
but wrong runs. Second, the game animates question blocks and coins by
rewriting background palette 3 from its own tables; patching only the area
palettes leaves those tiles with the original colours.

## 6. Limitations and design decisions

* **Castle.** The end-of-level castle is decoration and is now fully
  transparent; the level visibly ends at the flagpole.
* **Fire Mario** is pale pink, close to Mario's white, and his fireballs share
  that colour. Star power shows as white / green / orange flashing, because
  the game rotates Mario's palette attribute and index 1 of each sprite
  palette is what it is.
* **Bumped bricks** are drawn in terrain brown for the ~10 frames of the bump
  animation: no sprite palette has a slot left for the brick grey. Bumped
  ?-blocks stay orange. Brick debris is transparent.
* **Shared tiles within a category** cannot be told apart: the 1-up and the
  mushroom, the green and the red Koopa, all enemies in general, all share the
  category colour by design.
* **HUD.** The status line uses the text and ?-block entries, so the coin
  icon is orange and the text white, like Mario.
* **Shape information is gone.** Objects are distinguished by colour and by
  the size of their bounding box only (a Goomba and small Mario are both
  16x16; a Koopa is 16x24; big Mario 16x32).
* **Mid-level savestates.** Palettes are only rewritten when an area loads,
  so a savestate captured mid-level on the original ROM keeps the original
  colours until the next area change. The level states used by the dataset
  start on the black "WORLD x-y" screen and are unaffected;
  `code/fix_state_palette.py` rewrites the palette inside a state or a
  `.bk2`'s `Core.bin` if scene-level states are ever needed.
* **Castle levels.** The `Level?-4.state` files, inherited from
  `mario.stimuli`, are not savestates (they are an 813-byte JSON file) and
  cannot be loaded; castle levels are not part of the dataset.
* **Sprite classification** comes from what occurs in the dataset's 22
  levels. Objects that never appear there (Bloopers, Cheep-cheeps in water
  levels, Bowser, Podoboos, Lakitu's cloud in some poses) fall back to the
  enemy colour.
