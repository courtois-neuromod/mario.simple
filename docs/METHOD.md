# Building a visually simplified Super Mario Bros with identical game logic

This document describes how the simplified ROM in this repository was made,
why the approach preserves gameplay exactly, how that was verified, which
semantic information the simplification keeps or loses, and what its
limitations are. It is written to be reusable as the methods section of a
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
  fireworks, brick debris, tree trunks and ledge stumps, mushroom stems, Lakitu's cloud, Paratroopa wings) is removed, i.e.
  rendered as the uniform backdrop;
* every interactive block is drawn as a flat, single-colour square, and every
  sprite object (the player, enemies, items, projectiles) as a flat rectangle
  that is exactly its collision box, so that what is seen is what the game
  reacts to;
* colour is a semantic category (terrain, brick, ?-block, coin, item, 1-up,
  star, enemy, player, fire player, goal) that is identical in every level,
  whatever the original day / night / underground / water palette, on a black
  backdrop;
* the game states that matter for play but that colour cannot carry (the
  side Mario faces, dying, a kickable shell, an enemy that cannot be stomped,
  a winged enemy) are encoded by a few simple shapes;
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
else. Rewriting the *palette tables* (and the few tables that map objects to
tiles and palettes) in PRG-ROM changes only the bytes that pass through the
PPU write buffer and the sprite buffer, again with no effect on game state.

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
  section 3.4.

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

### 3.2 Sprite tiles: which object draws them (CHR-ROM, pattern table `$0000`)

Which colour index a sprite tile gets depends on which object draws it, and
that was *measured* rather than assumed: the game builds its sprite list in
RAM (`$0200-$02FF`) and keeps, for the player, each enemy slot, the power-up,
fireballs, bumped blocks and misc objects, the offset of their entries
(`$06E4-$06FB`). Replaying 66 participant recordings (3 per level, all 22
levels of the dataset) on the original ROM and reading these locations every
third frame gives, for each of the 256 sprite tiles, the object that drew it
and the sprite palette it was drawn with (`code/survey_sprite_tiles.py`). The
resulting map covers Mario, 14 enemy types, the four power-ups, fireballs,
coins, hammers, the flag, vines, platforms, springboards, fireworks and the
castle flag.

Because a sprite's palette is chosen by the game per object, tiles of
different categories can share a palette (e.g. the mushroom and the Spiny both
use sprite palette 2). Categories are therefore separated by *index* within a
palette, and the palettes of section 3.4 give each index its colour. Mario's
tiles use index 1 because the star-power effect rotates Mario's palette
*attribute* through the four sprite palettes; with index 1 he flashes light
blue / dark green / green / orange rather than enemy red.

Four palettes with three indices each give twelve sprite colours, but the
game's own palette assignments crowd some categories into the same palette.
Where that prevented a category from having its own colour, we changed the
palette the game assigns to the object. Each of these is a single immediate
operand or table byte in the drawing routine of that object: the fireball now
uses sprite palette 0 (Mario's) and index 3; coins popping out of blocks use
palette 3 and index 3; the bumped brick uses palette 2 and index 3 (terrain
colour, since no sprite palette has a slot left for the brick grey); the
bumped question block always uses palette 3 (the original used palette 1
outside ground areas); the vine uses palette 2 and index 3 (terrain: it is a
climbable solid); floating score numbers use palette 3 and index 3 (coin
colour); the fire flower and the star use palette 0 (index 3, the fire-Mario
deep blue, and index 2, pale pink) and the routine that cycles their top row through
the four palettes every two frames now always selects palette 0. The 1-up and
the super mushroom share their tiles and are told apart by the game with the
palette (1 vs 2), so index 1 of palette 1 is a dedicated 1-up colour. The
brick debris sprites are transparent.

### 3.3 Sprite tiles: rectangles that fit the collision box

Super Mario Bros does not derive collisions from the art. For every sprite
object it computes a collision box as the object's relative screen position
plus one of 12 four-byte entries (left, top, right, bottom offsets) of a table
in PRG-ROM (`BoundBoxCtrlData`), selected by a per-object control byte that
its initialisation routine sets (small Mario, big Mario, crouching Mario,
"tall" enemy, "small" enemy, fireball, hammer, Bowser flame, Bowser, three
sizes of lift). The boxes live in RAM at `$04AC-$04DB`, and the sprite-sprite
collision routine compares them with inclusive edges. The tiles of the same
object are drawn at fixed offsets from the same position (one, two or three
rows of two 8x8 tiles). Hence for each tile there is a fixed set of pixels
that lie inside the box, and a tile can be *carved* to those pixels: opaque
inside the box, transparent outside.

The geometry was measured rather than transcribed from the disassembly:
`code/hitbox_survey.py` replays the same 66 recordings on the original ROM
and, every second frame, reads the sprite buffer, the object-to-sprite offset
tables and the live boxes, and records for each drawn tile the owner object
and state, the tile's offset from the top-left corner of the owner's box, and
the box size, with the sprite's horizontal and vertical flip bits folded back
into tile space (the game mirrors the right-hand copy of symmetric tiles with
the flip bit, so a tile used on both sides of an object is consistent once
flips are folded). Objects whose state disables collisions (defeated enemies
falling off screen, squished Goombas) and frames during the grow/shrink
animation were excluded. The dominant geometry per tile is the `HITBOX` table
of `code/simplify_rom.py` (182 tiles); tiles that never appear in the dataset
(swimming Mario, Bloober) were placed from the graphics tables, and castle
objects (Bowser, Podoboo, flames, fire bars) were left as full squares. The
box sizes that result, with the size of the drawn sprite for comparison:

| Object | Collision box | Drawn sprite |
|---|---|---|
| Mario big / small / crouching | 12x24 / 10x12 / 12x12 | 16x32 / 16x16 / 16x16 |
| Goomba, Piranha Plant, Cheep-cheep, Bullet Bill, Spiny and its egg, Bloober | 10x6 | 16x16 or 16x24 |
| Koopas, Paratroopas, Buzzy Beetle, shells, Lakitu, all power-ups | 12x12 | 16x24 or 16x16 |
| Fireball, hammer | 8x8 | 8x8, 8x16 |
| Hammer Bro | 8x24 | 16x24 |
| Lifts | 24, 32 or 48 wide x 13 | same width x 8 |

For every object of the first four rows the box lies inside the drawn sprite,
so the carve is exact. The exceptions are listed in section 7.

We used the exclusive convention (a box of width `right - left`), which gives
the familiar sizes; because the game compares edges inclusively, two boxes
also register a collision when they merely touch, i.e. the effective box is
one pixel larger on each side than drawn. Mario's collisions with the
*terrain* are not box-based at all: the game probes points at `x+2` and
`x+13`, and at `y+4` (big) or `y+18` (small) for the head and `y+32` for the
feet, so the terrain-relevant region is a few pixels larger than the enemy
box.

The visual consequence is that objects become noticeably smaller than their
sprites (a Goomba is a 10x6 sliver at the bottom of its former 16x16 body,
small Mario a 10x12 block whose top is 4 px below the top of his head). This
is faithful to what the game reacts to, and it is the purpose of the change;
`--no-hitbox` rebuilds the ROM with full-size squares if the other look is
wanted.

A few *shapes* were then added within the same rectangles to carry game
states that colour cannot (section 6 says why each was needed):

* **facing direction**: every Mario tile has a 2x2 transparent hole 2 px in
  from the front edge and 2 px below the top of the box. The tiles are drawn
  facing right and the game sets the horizontal flip bit when Mario faces
  left, so the hole moves with him;
* **hollow rectangle** (2 px ring): Koopa and Buzzy shells, and Mario's death
  pose, i.e. "an empty or inert body";
* **toothed top edge** (2 px teeth, 2 px apart): Spiny, Spiny egg and Piranha
  Plant, the enemies that hurt when stomped;
* **wing bar**: the two Paratroopa wing tiles, which sit in the row above the
  box, carry an 8x2 bar 1 px above the box. This is the only opaque pixel
  drawn outside a collision box; it is on one side of the enemy only because
  the other tile of that row is the Koopa head shared with the walking Koopa;
* **squished Goomba**: a 16x4 bar on the ground (it has no collision);
* **springboard**: 2 px horizontal stripes (it is drawn with its own tiles
  and has no sprite box; the game handles it by position).

`--no-marks` rebuilds the ROM without these shapes.

### 3.4 Palettes (PRG-ROM data tables)

The game keeps four 32-byte palette sets (water, ground, underground,
castle), three 4-byte variants for snow and mushroom areas, a 12-byte player
palette table (Mario, Luigi, fire Mario), an 8-byte backdrop-colour table, and
two small tables used to animate question blocks and coins by rewriting
background palette 3 every 8 frames. All of these were overwritten so that
every palette index means the same category everywhere:

| index | BG pal 0 | BG pal 1 | BG pal 2 | BG pal 3 | SPR pal 0 | SPR pal 1 | SPR pal 2 | SPR pal 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | item | brick | text (white) | ?-block | Mario | 1-up | item | ?-block |
| 2 | terrain | terrain | terrain | terrain | star | enemy | enemy | enemy |
| 3 | goal | goal | goal | coin | fire Mario | goal | terrain | coin |

The backdrop is black in every area, on the "WORLD x-y" screens included.
Terrain is white rather than the natural brown so that it sits far from enemy
red (the two were adjacent NES hues of similar brightness), and the player is
blue. NES colour indices: backdrop `$0F`, terrain `$30`, brick `$10`,
?-block `$27`, coin `$28`, item `$2A`, 1-up `$1A`, star `$2C`, enemy `$16`,
Mario `$21` (light blue), fire Mario, fireballs and fire flower `$12` (a deep
blue, so the change of state is visible without breaking the "player"
family), goal `$24`. HUD text shares the terrain white; the HUD is outside
the play area. They are the `C` dictionary at the top of
`code/simplify_rom.py`.

### 3.5 Sound

The sound engine lives at the end of PRG-ROM (`$F2D0-$FFFF`) and runs inside
the NMI handler, after the game logic of the frame. The game logic talks to
it through six *queue* bytes (`$FA-$FF`: which sound effect or tune to
start) and reads back exactly one byte of its state, `EventMusicBuffer`
(`$07B1`), which it polls for zero in two places: while Mario falls off the
screen after dying (the death tune must end before the lose-life routine
runs) and in the end-of-level sequence (the level-clear tune must end before
the next area loads). Everything else the engine touches is its own state
(`$F0-$F9`, `$07B0-$07CA`) and the APU registers, which the CPU cannot read.
The audio was therefore simplified with the same rule as the image, without
touching the game logic:

* **Music.** The six area tunes (ground, underground, water, castle, cloud,
  pipe intro) are replaced by silence: the 6-byte table from which the game
  picks the area tune now holds the "Silence" code for every area. The
  star-power tune becomes a low continuous hum (one 24-frame C3 note that
  loops; the game re-queues the area tune, i.e. silence, when the star
  wears off). The tunes whose length the game logic waits for (death, level
  clear, castle clear, victory, game over, time warning) are rewritten as
  data for the unchanged music handler: one to three plain tones followed
  by rests, on the square-2 channel only, with exactly the frame count of
  the original tune (parsed from the original data and asserted at build
  time; 180, 324, 364, 384, 216 and 168 frames). The volume envelope tables
  are flattened to one constant volume. The headers of the other area tunes
  point to a silent loop, so that a savestate captured while music was
  playing goes silent at the end of its current section.
* **Sound effects.** The three per-channel handlers of the original (about
  730 bytes of code with a hand-written envelope or sweep for each of the 17
  effects) are replaced by one table-driven routine of 267 bytes, assembled
  at build time by a minimal assembler in the script: when a queue bit is
  set, it looks up (length, pitch, control byte) for that bit, writes the
  channel registers once, counts the length down and then switches the
  channel off. Every effect is thus one constant tone. The cues are
  assigned per visual category: jump (also the swim stroke), block hit,
  enemy defeated (stomp and fireball/shell kill share it), Mario shrinks,
  fireball, flagpole slide, coin, item emerging (also the vine), power-up
  collected, extra life, Bullet Bill fired, brick shattered (noise),
  Bowser's flame (noise). The end-of-level timer count, fireworks and pipe
  entry are removed. The pause jingle is untouched. The full legend is in
  the README.
* **Queue sites.** Three of the original effects share a queue bit with an
  unrelated event: pipe entry with injury, fireworks (and Bowser's bridge)
  with the Bullet Bill blast, and the swim stroke with the enemy stomp. At
  the four gameplay sites concerned, the operand that names the queue bit
  (and, for the pipe and fireworks sites, the queue byte) is changed so
  that the swim stroke uses the jump bit and pipe entry and fireworks land
  on unused bits of the noise queue mapped to silence. Each site overwrites
  the register right after the store, so the new value reaches nothing but
  the queue.

The sound-engine RAM (`$F0-$FF`, `$07B0-$07CA`) therefore differs from the
original ROM during play, and `verify_replays.py` masks it; every other RAM
byte, i.e. everything the game logic computes, must still match, and does
(section 5).

### 3.6 Summary of the binary changes

| Region | Bytes changed | Nature |
|---|---|---|
| iNES header | 0 | |
| PRG-ROM level data | 0 | |
| PRG-ROM game logic | 6 | operands at the four sites that queue the swim, pipe-entry and fireworks sounds |
| PRG-ROM sound engine | 966 | sound-effect handler region (731, of which 267 bytes of new code and tables, the rest `$FF`), its call sites (12), tune headers (95) and data (84), envelope tables (32) and constants (5), area-tune selection table (6) |
| PRG-ROM presentation data | 199 | palette tables (156), metatile-graphics table (32), enemy-graphics and power-up-attribute tables (4), sprite-palette operands (7) |
| CHR-ROM | 5528 | tile shapes |

The seven operands are the immediate values that select a sprite palette for
fireballs, block coins, bumped bricks, bumped ?-blocks, vines and floating
score numbers, and the mask of the palette-cycling routine of the fire flower
and star. The enemy-graphics table change blanks the top row of the second
Bloober frame, whose tile is a body tile in the first frame.

## 4. Reproducibility

`code/simplify_rom.py ORIGINAL.nes OUTPUT.nes` rebuilds the ROM
deterministically from the original ROM (md5 `811b027eaf99c2def7b933c5208636de`)
and the tables in the script; every PRG patch asserts the original bytes
before writing. The current ROM has md5 `e0d177c472ea7ca7540fcfd0b6141006`
(`626c679210364593883e8be91dac7f99` with `--no-sound`, i.e. the previous
version with the original sound). The sound-effect handler is written as
assembly text in the script and assembled at build time by a 40-line
assembler that covers the fifteen instructions it uses; no external tool is
needed.
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
power and a completed level), 1-2, 1-3, 3-1, 4-2, 5-1 and 8-2 (1900 to 6000
frames each), for the ROM before the sound change (`--no-sound`):

* the only bytes that ever differ lie in the PPU write buffer
  (`$0300-$03B0`, on the frames where a screen column or a palette is
  queued; the range reaches `$03B0` when the tall castle columns are queued),
  in the sprite buffer (`$0200-$02FF`, the tile and attribute bytes of the
  affected sprites) and in one zero-page scratch byte (`$0004`) in which the
  block-drawing routine hands the palette to a shared helper. Nothing outside
  these regions differs on any frame. The sprite buffer, the write buffer and
  that scratch byte are written by the graphics path and never read by game
  logic; in particular the collision boxes at `$04AC-$04DB`, which are
  compared, are identical;
* savestates taken on either ROM load on the other and track the original
  run to the end; the fceumm savestate contains no tile data and no ROM
  checksum;
* the 26 loadable level savestates of the repository, played with the same
  scripted inputs for 600 frames on both ROMs, give identical RAM outside the
  same three regions;
* all RAM-derived variables of `data.json` are therefore identical between
  ROMs, and `.bk2` recordings need no conversion (the recording names the
  game `SuperMarioBros-Nes`, which both integrations use).

With tile changes only (the CHR-ROM), RAM is byte-identical on every frame,
which was checked on the earlier versions of the ROM; the collision-box
carving of section 3.3 is a CHR-only change.

The sound change (section 3.5) was verified the same way on eight
recordings of a test participant (levels 1-1 and 3-1, 650 to 4250 frames,
including four deaths, two completed levels with the level-clear tune and
the end-of-level wait, an injury, coins, stomps and block hits): outside
the PPU buffers and the sound-engine RAM, no byte differs on any frame
between the original ROM and the current ROM, and the mid-run savestate
tracks. The frames at which `EventMusicBuffer` returns to zero after each
death and after the flag are the same on both ROMs. The star-power hum and
the time-warning tune, absent from these recordings, were exercised by
loading level 1-1, queueing the star tune and setting the game timer to
101 in the emulator RAM after 300 frames, on both ROMs: the warning tune
occupies the same 168 frames on both, the hum resumes after it, and the
rest of RAM stays identical. The two level states captured mid-level (4-1,
6-x) were played with scripted input on both ROMs, before and after the
sound fix of `fix_state.py`: RAM identical outside the masked bytes in every
combination. The audio of each replay was written to a `.wav`
(`verify_replays.py --wav`) and checked frame by frame: it is silent
except for one tone at each queued event (the emulator's output filter
adds a short decaying tail).

Visual checks were made on every level state and on replay frames covering
day, night, underground, tree-top, bonus and castle-exterior areas, including
coins, all four power-ups, star power, fire Mario, dying Mario, shells,
Paratroopas, Spinies, Piranha Plants, Hammer Bros, Lakitu, Bullet Bills and
score numbers.

Three pitfalls met during verification are worth recording. First, the NES
core exposes nine buttons (`B, -, SELECT, START, UP, DOWN, LEFT, RIGHT, A`);
a replay script that reads eight drops the A button and produces plausible
but wrong runs. Second, the game animates question blocks and coins by
rewriting background palette 3 from its own tables; patching only the area
palettes leaves those tiles with the original colours. Third, a recording's
initial savestate (`Core.bin`) carries the PPU palette of the moment it was
captured, i.e. the original colours, and the game only rewrites the palette
when an area loads. 3231 of the 3374 dataset recordings start on the
"WORLD x-y" screen, so the level palette is written about 120 frames later;
but that first screen itself is drawn with the stored palette (original
Mario icon colours), whereas every later intermission (after a death) is
drawn by the simplified ROM (light-blue icon). The other 143
recordings (79 of them the first repetition of a run) start in gameplay and
keep the original colours on the simplified ROM until the next area change,
which makes, for instance, Lakitu white and pipes green.
`code/fix_state.py` rewrites the 32 palette bytes inside a state or
`Core.bin` (it locates the fceumm `PRAM` chunk structurally, so it applies
whatever palette is stored and can be re-run after a colour change); the run
is RAM-identical afterwards, and applying it to every recording makes both
cases consistent. The 26 level savestates of this
repository have been rewritten this way (their game state is untouched; the
600-frame scripted-play check of this section was repeated with them), so new
recordings made on the simplified ROM start with the simplified palette. The
intermission backdrop comes from the same table entry as the underground
backdrop, which is why one backdrop colour is used for both.

The same tool handles the sound counterpart of that pitfall. A state
captured mid-level carries the music that was playing (which tune, and the
engine's position in its data); on the simplified ROM the engine would go
on reading the original tune from there until the end of the current
section. `fix_state.py` clears the sound-effect and music buffers inside
the state's RAM chunk and queues "Silence", which the engine turns into an
idle state on the first frame; these seven bytes are never read by game
logic, so the run is unchanged. The two level states captured mid-level
(4-1 and 6-x) are rewritten this way; the 24 others were captured on the
"WORLD x-y" screen with the engine already idle.

## 6. Semantic information: what is kept, what was added, what is lost

The simplification removes the drawings, so every distinction that the
original conveyed through drawings alone needed a decision. The inventory
below lists the information a player uses, how the original shows it, and
what the simplified ROM does. "Kept" means the cue survives unchanged;
"added" means a colour or shape was introduced for it; "lost" means it is
not visible, with the reason when it could not be done with colour or simple
shapes.

**Player**

| Information | Original cue | Simplified ROM |
|---|---|---|
| small / big / crouching | sprite size and pose | kept: box size 10x12 / 12x24 / 12x12 |
| fire Mario | white-red palette | kept: deep blue |
| star invincibility | palette flashing | kept: blue / green / orange flashing (the game rotates the palette attribute) |
| hurt invulnerability | Mario blinks | kept (the game skips drawing him every other frame) |
| facing direction | drawing | added: 2x2 hole on the front side |
| dying | death pose, then falling | added: hollow rectangle, plus the fall |
| walking / running / jumping / skidding / climbing / swimming pose | animation frames | lost: the frames share tiles with no free colour slot, and the pose is redundant with the motion |
| grow / shrink animation | frames alternate size | kept as in the original; the rectangle and the box disagree during those frames, when collisions are frozen |
| fireballs | orange balls | kept: 8x8 deep-blue squares, the exact box |

**Enemies**

| Information | Original cue | Simplified ROM |
|---|---|---|
| enemy vs anything else | drawing | kept: red |
| enemy species | drawing | lost by design (one category); partly recoverable from box size (10x6 Goomba class, 12x12 Koopa class, 8x24 Hammer Bro) and from behaviour |
| cannot be stomped (Spiny, Spiny egg, Piranha) | spikes, teeth | added: toothed top edge |
| winged (Paratroopa: two stomps, bounces or flies) | wings | added: 8x2 wing bar above the box, on one side |
| red vs green Koopa (turns at ledges vs walks off) | palette | lost: the two share every tile and differ only by palette, and those palettes also serve other enemies; visible from behaviour |
| immune to fireballs (Buzzy Beetle) | drawing | lost: no free colour slot in its palette without colliding with the ?-block or coin colour |
| shell (stomped Koopa / Buzzy), kickable | shell drawing | added: hollow rectangle |
| moving vs resting shell | motion | kept: motion |
| squished Goomba (harmless) | flat drawing | added: 16x4 bar |
| killed by fireball, shell or star | drawn upside down, falls through the floor | kept: the rectangle is mirrored within the sprite frame (it jumps up by a few pixels) and falls |
| hammers | drawing | kept: red 8x8 (half the box lies outside the drawn tile; see section 7) |
| Piranha inside its pipe | hidden behind the pipe | kept (background-priority bit) |
| Lakitu's cloud | drawing | removed (decoration) |
| enemy facing direction | drawing | lost; visible from motion |

**Items and blocks**

| Information | Original cue | Simplified ROM |
|---|---|---|
| super mushroom vs 1-up | palette (red vs green) | added: green vs dark green |
| fire flower | drawing, flashing | added: deep blue, the fire-Mario colour; the flashing is removed |
| star | drawing, flashing | added: pale pink; the flashing is removed |
| coins, coins from blocks | drawing | kept: yellow |
| ?-block vs used block | orange flashing vs brown | kept: orange flashing vs terrain white |
| brick vs hard block | drawing | kept: grey vs white |
| content of a brick or block, hidden blocks | none (invisible in the original) | same as original |
| enterable pipe | none in the original | same as original |
| vine (climbable) | drawing | added: terrain white (was item green) |
| springboard | drawing, compression frames | added: stripes; the compression frames are kept |
| moving / falling lifts | drawing, motion | kept: white bars, motion |
| Bullet Bill cannon | drawing | lost as a "danger source": it is solid terrain and drawn as such |
| flagpole, flag, ball; axe | drawing | kept: purple |
| end-of-level castle | drawing | removed (decoration; the level visibly ends at the flagpole) |
| pits | absence of ground | same as original |
| area theme (day, night, underground, water, castle) | palettes and decoration | removed by design; ceilings and walls remain terrain |

**Events and HUD**

| Information | Original cue | Simplified ROM |
|---|---|---|
| points earned (100, 200, ..., 1UP) | floating white numbers | kept, in coin yellow (they were enemy red in the previous version); the flagpole score is purple |
| coin collected, block bumped | sprite animations | kept |
| brick shattered | debris | lost: debris is decoration and is transparent |
| level completed | fireworks, castle flag | lost: transparent (decoration) |
| score, coins, world, time, lives | HUD text | kept |
| death by falling into a pit | none in the original | same as original |

**Sounds**

| Information | Original cue | Simplified ROM |
|---|---|---|
| area (ground, underground, water, castle, cloud), pipe intro | six tunes | removed (silence) |
| star power active | tune | kept: continuous low hum (also shown by Mario's flashing) |
| time below 100 s | jingle | kept: three short beeps |
| death, level clear, castle clear, game over, victory | jingles | kept: one to three plain tones, then silence, same length |
| jump; big vs small Mario | two jump sounds | one jump tone (size is visible) |
| swim stroke | shares the stomp sound | jump tone |
| enemy defeated: stomped vs killed by fireball/shell; Bowser falls | three sounds | one tone |
| block hit, fireball explodes, shell bumps | one sound | kept, one tone |
| Mario shrinks | shares the pipe-entry sound | own tone |
| pipe entry | shares the injury sound | removed (the transition is visible) |
| fireball thrown, coin, extra life, power-up collected | one sound each | kept, one tone each |
| item emerges from a block; vine grows | two sounds | one tone |
| flagpole slide | sound | kept, sustained tone |
| Bullet Bill fired; Bowser's bridge collapses | share the fireworks sound | one tone |
| fireworks, end-of-level timer count | sounds | removed (decoration) |
| brick shattered | noise | kept, noise burst (the debris is transparent) |
| Bowser's flame | noise | kept, noise burst |
| pause | jingle | untouched |

## 7. Limitations and design decisions

* **Collision boxes that stick out of the drawn sprite.** Hammer Bro's box
  extends 4 px below his feet; lifts have a 5 px landing-tolerance zone under
  the bar; a hammer's 8x8 box is offset 4 px from its 8x8 tile so half of it
  is undrawable; a resting shell has a 1 px strip of box above it; Bowser has
  a box on his front half only. Drawing those pixels would require extra
  sprite entries, i.e. code changes, so they are not drawn.
* **Small residuals.** The cannon-fired Bullet Bill is drawn 1 px higher
  than the frenzy variant relative to its box, so the latter is 1 px off.
  The Spiny egg alternates two frames drawn 2 px apart. Lakitu's box control
  byte switches to the 4x4 Bowser-flame entry in about 12% of his frames
  (not traced). In about 3% of frames the box lags the sprite by 1 px because
  the game computes it before the final position update of the frame.
* **Castle.** The end-of-level castle is decoration and is now fully
  transparent; the level visibly ends at the flagpole.
* **Fire Mario** is deep blue, next to Mario's light blue; his fireballs and
  the fire flower share that colour. Star power shows as blue / green / orange
  flashing, because the game rotates Mario's palette attribute and index 1 of
  each sprite palette is what it is; the star item itself no longer flashes.
* **Bumped bricks** are drawn in terrain white for the ~10 frames of the bump
  animation: no sprite palette has a slot left for the brick grey. Bumped
  ?-blocks stay orange. Brick debris is transparent.
* **Shared tiles within a category** cannot be told apart: the green and the
  red Koopa, the Buzzy Beetle and the other enemies, all share the category
  colour (section 6).
* **HUD.** The status line uses the text and ?-block entries, so the coin
  icon is orange and the text white, like the terrain.
* **Shape information is reduced to the box.** Objects are distinguished by
  colour, by the size of their collision box and by the shape marks of
  section 3.3; pose is gone.
* **Savestates carry a palette and the sound state.** A recording's
  `Core.bin` keeps the original palette until the next area load, which
  shows on its first "WORLD x-y" screen (original Mario icon colours) and,
  for recordings that start mid-level, in the level itself; the latter also
  keep playing the original tune until the end of its current section.
  Rewrite them with `code/fix_state.py` (section 5). The level states of
  this repository are already rewritten.
* **Sound cues are one tone each.** Pitch, length and duty cycle are the
  only differences between cues, so two cues close in pitch (e.g. the coin
  and the extra life) are told apart mainly by their length; the values in
  `CUES` are meant to be tuned by listening. Cues on the same channel
  interrupt each other, as in the original; a tune note that starts while
  an effect plays on square 2 is skipped, as in the original.
* **The sound change is a code change.** Unlike the graphics, which only
  touch data, the sound-effect handler is new code and six gameplay bytes
  name a different queue bit. The argument that this is gameplay-neutral is
  in section 3.5 and was tested in section 5, but it rests on reading the
  code, not only on the emulator's memory map.
* **Castle levels.** The `Level?-4.state` files, inherited from
  `mario.stimuli`, are not savestates (they are an 813-byte JSON file) and
  cannot be loaded; castle levels are not part of the dataset.
* **Objects absent from the dataset** (Bloopers and swimming Mario in the two
  water levels, Bowser, Podoboos, Bowser's flames, fire bars) were placed from
  the graphics tables or left as full squares, and their rendering was not
  verified on recordings.
