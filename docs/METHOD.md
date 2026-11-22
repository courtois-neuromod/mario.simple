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
* colour is a semantic category that is identical in every level, whatever
  the original day / night / underground / water palette, on a black
  backdrop. Blocks are coloured by what the player can do with them: nothing
  (immutable terrain), break them (bricks), hit or use them (interactive:
  question blocks, springboards, vines), collect them (coins); the other
  categories are item, 1-up, star, launcher (the barrel of a cannon), enemy,
  player, fire player and goal;
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
palette; found at CPU `$8B10-$8CA3`). We dumped those tables from the original
ROM and used them to assign every background tile to the block it belongs to
(ground, brick, question block, pipe, cloud, bush, ...), rather than guessing
from its picture. Each tile was then rewritten as either

* **transparent** (all pixels index 0) for decoration, or
* **a solid square** of a chosen palette index (1, 2 or 3) for interactive
  blocks; the index selects the semantic colour through the palettes of
  section 3.4.

The flagpole shaft keeps its thin shape but is recoloured, and so is the coin
icon of the status bar, which takes the coin colour (it shared the palette
index of the question blocks). Text and the other HUD tiles are untouched.
The full classification is the `BG` table in `code/simplify_rom.py`.

A Bullet Bill cannon is made of three metatiles: the barrel, from which the
bullets come out, a pedestal and a column. They use background palette 1,
like the ground and the bricks, and its third colour is free: the barrel has
a colour of its own (launcher), the pedestal and the column are terrain.

Some tiles are shared between categories, so that no tile rewrite can serve
both. For those we edited the metatile-graphics table instead (42 bytes):

* tile `$26` is both the fill of the decorative hills and the inner column of
  every pipe shaft: the two pipe-shaft metatiles use the pipe-edge tile
  instead (4 bytes);
* tile `$47` is the breakable brick, the wall of the end-of-level castle and
  the base of the springboard. The seven castle metatiles use the blank tile
  (28 bytes), which makes the castle, a purely decorative object, disappear;
  the two half-block metatiles that the game puts under a springboard, which
  are solid and cannot be broken, use a terrain tile (4 bytes);
* tiles `$A2`/`$A3` are the flagpole shaft and the vertical rope of the
  balance lifts, which is decoration: the rope and pulley metatiles use the
  blank tile (6 bytes).

This table is read only when the game writes a new screen column into the
PPU write buffer (section 5 confirms that these are the only RAM bytes that
differ). The rope is the one piece of background that the game also draws
without a metatile: while a balance lift moves down, a routine queues the two
rope tiles above it directly (and blank tiles while it moves up). Its four
immediate operands now name the blank tile.

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
blue / dark green / green / grey rather than enemy red.

Four palettes with three indices each give twelve sprite colours, but the
game's own palette assignments crowd some categories into the same palette.
Where that prevented a category from having its own colour, we changed the
palette the game assigns to the object. The game chooses a sprite's palette
in three ways, all of them presentation data that reaches nothing but the
sprite buffer:

* *an immediate operand* in the drawing routine of the object. The fireball
  uses sprite palette 0 (Mario's) and index 3; the coin popping out of a
  block (two sprites) and the "200" that follows it use palette 3 and
  index 3, as do the floating score numbers (coin colour); the vine uses
  palette 3 and index 2 (interactive); the fire flower and the star use
  palette 0 (index 3, the fire-Mario deep blue, and index 2, pale pink) and
  the routine that cycles their top row through the four palettes every two
  frames now always selects palette 0;
* *the enemy attribute table*, one byte per enemy graphic, which the enemy
  drawing routine ORs into the sprite attribute. Buzzy Beetle, Goomba,
  Bloober and Bullet Bill leave palette 3 for palette 2 (4 bytes; both hold
  the enemy colour at index 2), which frees index 2 of palette 3 for the
  interactive colour, and the three springboard frames enter palette 3
  (3 bytes). Two special cases of that routine bypass the table and needed
  their own operand changed: the cannon-fired Bullet Bill (hard-coded
  palette 3) and the two lower rows of the springboard (hard-coded
  palette 2);
* *small per-object tables*: the power-up attribute table (the 1-up and the
  super mushroom share their tiles and are told apart by the game with the
  palette, 1 vs 2, so index 1 of palette 1 is a dedicated 1-up colour) and
  the hammer attribute table (palette 3 to 2).

One object could not be given its colour in any of these ways. The fire bars
of the castle levels are drawn by the routine that draws Mario's fireballs,
with the same tiles and the same operand, so they had his colour. That routine
is 25 bytes long and contains no jump: the build puts a copy of it in the
space freed by the sound-effect handlers (section 3.5), with a tile of the
enemy category (`$82`/`$83`, two former hammer frames) and sprite palette 2,
and the one call in the fire-bar code goes to the copy. The copy executes the
same instructions in the same time, and what it writes is a tile number and an
attribute byte of the sprite buffer.

A block that is hit from below is drawn as a sprite while it bounces, by one
routine (`DrawBlock`): it draws the brick tiles and, if the block is turning
into a used block (a question block, a brick that held an item, a hidden
block), redraws it with the used-block tile. The bouncing block is thus
already what it becomes, and is coloured accordingly: the used block uses
palette 2 and index 3 (terrain; one operand), the brick keeps the game's own
palette 3, whose index 1 is the brick colour.

The brick debris, the fireworks, the castle flag and the air bubbles of the
underwater areas are transparent. Sprite 0, two rows of pixels that complete
the coin icon of the status bar and that the game uses to time the screen
split below the status bar, keeps its shape (the timing depends on it) and
takes the coin colour. The floating score digits keep their glyph, including
the "00" of the scores of 1000 and more, a tile also used by the flagpole
score.

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
of `code/simplify_rom.py` (187 tiles); the tiles of big swimming Mario, who
never appears in the dataset, were placed from the graphics tables, and castle
objects (Bowser, Podoboo, flames, fire bars) were left as full squares. Every
drawn rectangle was then compared with its box on the simplified ROM
(`code/audit_colours.py`, section 5), which corrected the entries of four
objects that the survey had not placed or that no carving could fit: the
Bloober, the hammer, the Bullet Bill and the Spiny egg (see below). The box
sizes that result, with the size of the drawn sprite for comparison:

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

Three objects needed more than a tile rewrite to be drawn on their box.

* The **hammer** is a pair of sprites that spins around a 8x8 box located at
  the object's position: in every frame half of one sprite lies in the box and
  the other sprite lies outside it, and each tile takes both roles in turn, so
  no carving fits. The seven 4-byte tables that give, per animation frame, the
  offsets, tiles and attributes of the two sprites now put one full tile on
  the box and make the other sprite blank (15 bytes, read by the hammer's
  drawing routine only).
* The **Spiny egg**, i.e. the Spiny while it falls from Lakitu, is made of
  four quadrants. The game draws its left column as is and its right column
  mirrored both ways, and the original graphics table used two tiles, each
  once on the left and once on the right at the other height, so no carving
  fits either. The table entries of the egg (one per animation frame) now
  name one tile per quadrant, the same four in both frames (4 bytes), and the
  two tiles of the right column are carved mirrored. The egg is drawn exactly
  like the walking Spiny.
* The **Bullet Bill** exists in two variants that share their tiles and their
  box: the one fired by a cannon, which a special case of the enemy routine
  draws one pixel above its position (`dec $02`, the zero-page byte that
  holds the row being drawn), and the one that flies in from off screen in
  levels 5-3 and 6-3, drawn at its position. One carving cannot fit both. The
  decrement now applies to `$04`, a byte that the same special case overwrites
  four instructions later: same size, same timing, and both variants are drawn
  at their position. The only side effect is that `$02` is left one higher
  than on the original ROM (section 5.1).

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
| 1 | (item) | brick | text (white) | interactive | Mario | 1-up | item | brick |
| 2 | terrain | terrain | terrain | terrain | star | enemy | enemy | interactive |
| 3 | goal | launcher | (goal) | coin | fire Mario | goal | terrain | coin |

(The two entries in parentheses are not used by any tile.) The backdrop is
black in every area, on the "WORLD x-y" screens included. Terrain is white
rather than the natural brown so that it sits far from enemy red (the two
were adjacent NES hues of similar brightness), and the player is blue. NES
colour indices: backdrop `$0F`, terrain `$30`, brick `$10`, interactive `$17`
(dark orange), coin `$38` (light yellow), item `$2A`, 1-up `$1A`, star `$35`,
launcher `$06` (dark red), enemy `$16`, Mario `$21` (light blue), fire Mario,
fireballs and fire flower `$12` (a deep blue, so the change of state is
visible without breaking the "player" family), goal `$24`. HUD text shares
the terrain white; the HUD is outside the play area. They are the `C`
dictionary at the top of `code/simplify_rom.py`.

Two of these choices are a compromise. The interactive dark orange is the
NES hue next to the enemy red, at the same brightness; the two never share a
shape (question blocks are static 16x16 squares, enemies smaller moving
rectangles). The colour of the previous version, orange `$27`, sat next to
the coin yellow `$28`, and question blocks read as coins; the coins moved to
a lighter yellow at the same time. The launcher dark red is in the enemy family on purpose: a barrel is
where enemies come from, and it is solid like terrain. Question blocks and
coins do not pulse as they do in the original: the tables the game rotates
into background palette 3 hold a single colour.

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
  data for the music handler: one to three plain tones followed
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
* **The music handler and the cues.** The original effects rewrite the
  registers of their channel on every frame. A cue writes them once, so
  whatever the music handler writes to the same channel afterwards silences
  the cue. The handler is unchanged except in the three places where that
  happened. (i) On a silent drum beat, the only kind left (the star-power
  tune has a drum track), it wrote a zero volume to the noise channel, which
  cut the brick cue: the two branches it takes for a silent beat now go to
  its return (2 operand bytes). (ii) When a tune is over, it silences both
  square channels: the four instructions that do it become a jump to 17 bytes
  placed after the sound-effect routine, which make the same writes but skip
  a channel on which an effect is playing. (iii) When the death tune starts,
  the original stops the effect of square 2 but leaves its buffer set, and
  the handler skips a tune note that starts while that buffer is set; the
  death tune is a single tone here, and was lost whenever an effect was
  playing as Mario died. That call now clears the buffer as well (the
  operand of one `jsr`).

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
| PRG-ROM sound engine | 976 | sound-effect handler region (731, of which 267 bytes of new code and tables, the 17 bytes of the tune-end code and the 25-byte copy of the fire-bar routine, the rest `$FF`), its call sites (12), the music handler (11: two branch operands, and the nine bytes that became a jump), tune headers (95) and data (84), envelope tables (32) and constants (5), area-tune selection table (6) |
| PRG-ROM presentation data | 226 | palette tables (136), metatile-graphics table (42), rope tile operands (4), sprite palette, tile and position tables and operands (44) |
| CHR-ROM | 5511 | tile shapes (255 sprite tiles and 152 background tiles rewritten) |

The 44 bytes of the last group of presentation data are the power-up
attribute table (2), the enemy attribute table (7), the enemy-graphics table
(6: the top row of the second Bloober frame is blanked, because its tile is
a body tile in the first frame, and the Spiny egg gets one tile per
quadrant), the seven hammer tables (15) and fourteen bytes of the drawing
routines: the immediate values that select a sprite palette for the fireball,
the two sprites of a block coin, its score, the bumped used block (and the
shift that followed it, now a no-operation), the vine, the floating score
numbers, the cannon-fired Bullet Bill (and the operand of the decrement that
raised it) and the lower rows of the springboard, the mask of the
palette-cycling routine of the fire flower and star, and the address called
by the fire-bar code. `simplify_rom.py --summary` prints these counts.

## 4. Reproducibility

`code/simplify_rom.py ORIGINAL.nes OUTPUT.nes` rebuilds the ROM
deterministically from the original ROM (md5 `811b027eaf99c2def7b933c5208636de`)
and the tables in the script; every PRG patch asserts the original bytes
before writing. The current ROM has md5 `2158c12f805918e359b69160299f11d8`
(`ac5251830e8b9a3a3c3f3443d41d2e08` with `--no-sound`, i.e. with the original
sound; that build keeps the fire bars in the fireball colour, since the copy
of their routine lives in the space the sound patch frees). The sound-effect
handler is written as assembly text in the script and assembled at build time
by a 40-line assembler that covers the fifteen instructions it uses; the two
other pieces of code are given as bytes. No external tool is needed.
The tool used for the earlier, hand-made versions of this ROM (SMB Utility)
is no longer needed. The figures of this document and of the manuscript are
regenerated by `code/make_figures.py`.

## 5. Verification

Three tools replay recordings with the same emulator (stable-retro 0.9.8,
`fceumm` core) and check that the game logic is untouched (5.1), that the
picture is what the legend says (5.2) and that the sound is (5.3). Section 5.4
is about savestates. The reference set is the 3374 recordings of the mario
dataset (18,132,655 frames, 5 participants, 22 levels), which also reach the
bonus rooms of those levels (underground, cloud and underwater) and, in one
recording that runs on after the flagpole of 3-3, a castle.

### 5.1 Game logic: `verify_replays.py`

A recording is replayed on the original and on the simplified ROM, from the
recording's own initial savestate, and the 2 KB of console RAM are compared
after every frame. A savestate taken halfway through the run on the original
ROM is then loaded into the simplified ROM and the rest of the inputs is
replayed, to check that it tracks the original run.

*When RAM is compared.* The emulator returns once per video frame. On almost
every frame the CPU is then parked in the game's idle loop (`$8057`, a jump to
itself, with an empty stack): the interrupt handler has uploaded the graphics,
run the sound engine and run all the game logic of the frame, so RAM is a
complete state. On the frames where the logic is not finished (the game takes
more than one frame to wipe its memory when an area loads, and a few frames of
heavy play overrun), the two ROMs can be a few CPU cycles apart, because their
sound code differs, and a snapshot is not comparable: those frames are skipped
and counted. A divergence would persist and show on the next frame.

*Which bytes may differ.* Everything the game logic computes must be equal.
The bytes that only describe what is drawn or played are tolerated:

* `$0200-$02FF`, the sprite buffer: the tile and the attribute byte of each
  sprite. The two position bytes must be equal, because the simplified ROM is
  meant to draw every sprite where the original does, with three exceptions: a
  sprite that is off screen or shows the blank tile on both ROMs, whose bytes
  are left over from an earlier object; the sprites of a hammer, which is
  drawn as one square on its collision box, 4 px to the left or 4 px up; and
  those of a Bullet Bill while one fired by a cannon exists, 1 px lower
  (section 3.3). One position byte must be equal whatever the sprite shows:
  `$0207`, the horizontal position of Mario's first sprite, is the only byte
  of the buffer that game logic reads (the fire bars of the castle levels test
  a hit against it);
* `$0301-$033F` and `$0341-$0362`, the two PPU write buffers: tile numbers,
  palette and attribute bytes queued for the graphics chip. Their length bytes
  (`$0300`, `$0340`) must be equal;
* `$0363-$03FF`, only where the second buffer reaches. During play these
  addresses hold game variables (relative positions, off-screen flags, the
  block being bumped) and are compared. While an area loads, the game queues
  four columns of the first screen per frame and the buffer grows over them; a
  byte there may differ if it lies inside the length queued on that frame, or
  has not been written since it did;
* `$0004`, a zero-page scratch byte through which the drawing routines pass a
  sprite's palette;
* `$0002`, the scratch byte through which the enemy drawing routine passes the
  row it draws. The original ROM raises a cannon-fired Bullet Bill by one
  pixel there and the simplified ROM does not (section 3.3), so the byte is
  left one higher. Only that is tolerated: simplified = original + 1, on a
  frame where such a Bullet Bill exists or existed on the frame before, and
  for as long as neither run writes the byte again (a paused game). Nothing
  reads the byte before writing it, or the difference would spread to bytes
  that are compared;
* `$00F0-$00FF` and `$07B0-$07CA`, the sound engine's own state. Game logic
  only writes the queues and reads one byte back, `EventMusicBuffer`, to wait
  for the death and level-clear tunes; the rewritten tunes keep their frame
  counts, so a difference there would desynchronise the logic and show
  everywhere else;
* `$0160-$01FF`, the CPU stack (the game itself excludes this range when it
  wipes RAM). In the idle loop the stack is empty and what these bytes hold is
  left over from routines that have returned.

*Result.* On the 3374 recordings, no other byte differs on any of the
18,123,537 frames compared, and the savestate check, done for one recording in
eight (422), tracks to the end in each. 12,492 frames (0.069 %) were not in
the idle loop and were skipped: 12,376 inside the memory-wiping routine and
116 elsewhere, in 40 recordings. The latter are frames of heavy play on which
the logic overran, 98 of them while the game was building a new column of the
level; the two ROMs were at the same instruction on 42 of them and a few CPU
cycles apart on the others.

What does differ, by number of recordings: the sound engine's state and the
PPU write buffers in all of them; the sprite buffer in 3269, of which a
position byte in 801 (a hammer or a cannon-fired Bullet Bill on screen, or
left-over bytes of hidden sprites); the second buffer over `$0363-$03B0` in
2950 (the first screen of a level contains a castle, a pipe shaft or a
springboard, whose tiles changed); scratch `$0004` in 724; scratch `$0002` in
724, the recordings in which a cannon fires; and one byte of the stack page,
`$01F7`, in 1880 (in 4 of them `$01F5` as well). `$01F7` is where the original
sound-effect routines leave the low byte of a return address when they call a
helper three levels deep; the replacement routine jumps to the helper instead
of calling it. `$01F5` is the same thing one level deeper, seen while an
effect of the original plays on the game-over screen. Game logic overwrites
these bytes whenever its own calls go as deep, which is on most frames, so the
difference shows only while the logic is shallow (between levels). No code
reads the stack page by address.

Three more runs: (i) with `--no-sound`, i.e. the original sound code, on the
two longest recordings of each level (44 recordings, 161,362 frames), the
sound engine's state and the stack are identical as well, and only the sprite
buffer, the write buffers, `$0004` and `$0002` differ; (ii) the 26 level
states of this repository, each played for 1500 frames with scripted input
(run right, jump periodically), give identical RAM on both ROMs; (iii) with
`--fix-state`, which starts the simplified ROM from the recording's initial
state as rewritten by `fix_state.py` (section 5.4), the run is identical to
the untouched one on the original ROM (68 recordings, among them 24 that start
in gameplay).

With tile changes only (the CHR-ROM), RAM is byte-identical on every frame,
which was checked on the earlier versions of the ROM; the collision-box
carving of section 3.3 is a CHR-only change.

### 5.2 Picture: `audit_colours.py`

RAM identity says nothing about the picture. This tool replays recordings on
the simplified ROM and, on every Nth frame, checks the picture object by
object, using the game's own memory to know what each thing on screen is. Its
expectations are written from the game's logic, not from the tile tables of
`simplify_rom.py`.

* *Sprites.* Every sprite of the sprite buffer is attributed to the object
  that drew it (player, enemy slot, power-up, fireball, bumped block, coin,
  hammer) through the game's sprite-offset tables, and the colours of its
  opaque pixels (tile pixels through the palette held by the PPU) must be
  those of that object's category.
* *Background.* Every visible 16x16 cell of the name table must be drawn in
  the category colour of the block that the game holds at that place in its
  block buffer, and every cell where it holds nothing must be empty, or be
  text. A mismatch counts once it has lasted 8 frames (the name table lags the
  block buffer by a few frames when a block changes).
* *Collision boxes.* The rectangle drawn for each object that has a live box
  is compared with that box, edge by edge; for Mario, the side of the hole in
  his rectangle is compared with the side he faces.
* *Colours.* Every pixel of the rendered frame must have a legend colour.

It was run on the final ROM on the same 3374 recordings: 18,132,655 frames,
every second one audited.

* Background: the 101 metatiles of the ROM are drawn in their expected
  category; in play, 1,395,268,521 cells are as expected, 26,418 are text (the
  warp-zone messages), 20,153 are a block changing, and one is unexpected: in
  one recording of 6-3, a coin that Mario has just collected stays on screen
  for 368 frames. This is the original game's doing, and the original ROM
  shows it on the same frames. The game queues the erasure of a collected coin
  in its second write buffer; the first one had not been sent to the screen
  for four frames, because the second was in use each time (two columns of the
  level, their colours, another coin), and what had piled up in it (three rope
  updates of a balance lift, the score and the coin counter twice, the timer)
  ran two bytes over its end, into the start of the second, which was
  therefore never sent.
* Sprites: all 113,349,784 sprites are in the colour of their object's
  category, the fire bars and Podoboos of the castle included.
* Collision boxes, as the percentage of frames in which the drawn rectangle is
  exactly the live box:

  | Object | Frames | Rectangle = box |
  |---|---|---|
  | Mario, small (10x12) | 4,158,782 | 97.4 % |
  | Mario, big (12x24) | 858,081 | 96.0 % |
  | Mario, crouching (12x12) | 5091 | 92.8 % |
  | Goomba | 1,181,092 | 100 % |
  | Piranha Plant | 908,353 | all but 2 frames |
  | Cheep-cheeps | 393,066 | 100 % |
  | Bloober | 14,010 | 100 % |
  | Bullet Bill, cannon-fired | 323,290 | 100 % |
  | Bullet Bill, frenzy | 144,748 | 100 % |
  | Spiny and its egg | 398,900 | 100 % |
  | Koopas and Buzzy Beetle, walking or as a shell | 1,343,094 | 90.7 % |
  | Paratroopas | 580,785 | 100 % |
  | Lakitu (12x12 box) | 310,146 | 100 % |
  | Lakitu (4x4 box) | 15,310 | 0.0 % |
  | Hammer Bro | 148,498 | 0.0 % |
  | Hammer | 191,838 | 100 % |
  | Mario's fireball | 25,828 | 100 % |
  | Super mushroom | 89,708 | 99.7 % |
  | 1-up mushroom | 30,811 | 100 % |
  | Fire flower | 14,169 | 100 % |
  | Star | 20,988 | 100 % |
  | Lifts | 640,416 | 0.0 % |
  | Podoboo (castle) | 324 | 0.0 % |

  The other frames are the cases of section 7: the box lags the rectangle by a
  pixel or two while the object moves, the resting shell, Hammer Bro's and the
  lifts' taller boxes, the re-created Lakitu. Three rarer ones were traced,
  and the original ROM draws the same sprites at the same places in each. Big
  Mario in the falling state with the crouch flag still set (he walked off a
  ledge while crouching) has the crouching box, and the game draws him
  standing: 161 frames. A hammer in flight is drawn in two sprite slots that
  lie among the six of an enemy or of the power-up, and after them, so that
  object is drawn without one of its sprite rows while the hammer flies: 254
  frames (a super mushroom in 240 of them, a Buzzy Beetle in 12, a Piranha
  Plant in 2). A Koopa shell that a block bumped from below has turned over is
  drawn from the same two tiles as a stomped shell, 3 px lower relative to its
  box; the tiles are fitted to the stomped shell, so the turned-over one has
  its rectangle 4 px below its box: 856 frames.
* Mario's hole is on the side he faces in all 4,879,634 frames checked.
* No rendered frame contains a colour outside the legend.

The collision-box results of earlier builds are what led to the corrections of
the hammer, the Bloober, the Bullet Bill and the Spiny egg (section 3.3).
Objects without a collision box (the fire bars, a defeated enemy, the
flagpole) are not covered by this comparison; that they are drawn where the
original ROM draws them follows from the position bytes of 5.1.

### 5.3 Sound: `audit_sound.py`

The fceumm savestate holds the registers of the sound chip, so what each
channel does on a frame can be read exactly, without analysing audio. On every
frame, the tool checks that a sound effect that starts sets its channel to the
pitch, duty and volume that `CUES` gives it, keeps sounding with those values
on every frame and lasts the number of frames it gives; that a channel is
audible only while an effect or a tune plays on it (the triangle never); that
a tune sounds only the notes `TUNES` gives it; and that every event tune that
starts sounds those notes for their number of frames, unless an effect takes
the channel meanwhile.

On the same 3374 recordings (18,132,655 frames): 159,805 audible cues started,
all with the expected pitch, duty and volume; 150,982 lasted their full number
of frames, 8206 were replaced by a later cue of the same channel, 600 were
stopped when a tune started (the death tune silences the effects, as in the
original), 7 by an area change and 10 by the end of the recording. None was
cut off or silenced by the music handler (section 3.5): in particular, all 99
bricks broken under star power sound in full. A channel kept a tone for one
frame at the start of a recording or across an area change 153 times.

The star-power hum sounds its note and nothing else. Of the event tunes that
started, all 564 level-clear tunes sounded in full; of the 8046 death tones,
7999 sounded in full, 43 were shortened by an effect that started on the same
channel while they sounded (each time the sound of a Bullet Bill being fired,
32 of them in 5-3) and 4 were cut by the end of the recording; of the 1889
game-over tunes, 1868 sounded in full and 21 were cut by the end of the
recording; of the 96 time-warning tunes, 88 sounded in full, 4 lost a beep to
a coin sound and 4 were replaced by the tune of another event. Nothing else
was unexpected.

The audio of a replay can also be written to a `.wav` (`verify_replays.py
--wav`).

### 5.4 Savestates, and pitfalls

Four pitfalls met during verification are worth recording. First, the NES core
exposes nine buttons (`B, -, SELECT, START, UP, DOWN, LEFT, RIGHT, A`); a
replay script that reads eight drops the A button and produces plausible but
wrong runs. Second, the game animates question blocks and coins by rewriting
background palette 3 from its own tables; patching only the area palettes
leaves those tiles with the original colours. Third, the emulator returns a
240x224 picture, the NES picture without 8 pixels on each side: an overlay
drawn from the game's coordinates must be shifted by 8. Fourth, a savestate
carries more than the game's memory, and three parts of it are what the ROM it
was saved on had produced.

*The palette.* A recording's initial savestate (`Core.bin`) carries the PPU
palette of the moment it was captured, i.e. the original colours, and the game
only rewrites the palette when an area loads. 3231 of the 3374 dataset
recordings start on the "WORLD x-y" screen, so the level palette is written
about 120 frames later; but that first screen itself is drawn with the stored
palette (original Mario icon colours), whereas every later intermission (after
a death) is drawn by the simplified ROM (light-blue icon). The other 143, all
of level 4-1, whose level state was saved in gameplay, keep the original
colours on the simplified ROM until the next area change, which makes, for
instance, Lakitu white and pipes green. `code/fix_state.py` rewrites the 32
palette bytes inside a state or `Core.bin` (it locates the fceumm `PRAM` chunk
structurally, so it applies whatever palette is stored and can be re-run after
a colour change). The intermission backdrop comes from the same table entry as
the underground backdrop, which is why one backdrop colour is used for both.

*The sound.* A state captured mid-level carries the music that was playing
(which tune, and the engine's position in its data); on the simplified ROM the
engine would go on reading the original tune from there until the end of the
current section. `fix_state.py` clears the sound-effect and music buffers
inside the state's RAM chunk and queues "Silence", which the engine turns into
an idle state on the first frame; these seven bytes are never read by game
logic. (The noise channel can still sound for one frame.)

*The screen.* A state captured mid-level carries the two name tables, i.e. the
tiles of the screen that was already drawn. The simplified ROM draws a few
blocks with other tiles than the original (section 3.1): what the original
drew stays until it scrolls away. Level 4-1 starts next to a large castle,
which the 143 recordings above therefore show as a wall in the brick colour.
`fix_state.py` redraws those cells: it reads what each 16x16 cell is from the
game's block buffer in the same state, redraws the blocks whose tiles changed
(pipe shafts, springboard base), and blanks, where the game holds no block,
the tiles that only the castle and the lift ropes use. Only the PPU's memory
is touched.

The run is RAM-identical after these rewrites (5.1, iii), and applying
`fix_state.py` to every recording makes all of them consistent;
`audit_colours.py` and `audit_sound.py` do it themselves. The 26 level
savestates of this repository are rewritten: the palette in all of them, and
the sound state and the screen in the two that were saved in gameplay (4-1 and
6-x), so that new recordings made on the simplified ROM start with its colours
and without the castle.

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
| star invincibility | palette flashing | kept: light blue / dark green / green / grey flashing (the game rotates the palette attribute; the same flash plays for a moment when he picks up a fire flower) |
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
| hammers | drawing, spinning | kept: a red 8x8 square, exactly the box (the spin is gone; see section 3.3) |
| fire bars (castle levels) | a rotating chain of fireballs | kept: a rotating chain of red 8x8 squares (the original draws them with the art of Mario's fireballs) |
| Piranha inside its pipe | hidden behind the pipe | kept (background-priority bit) |
| Lakitu's cloud | drawing | removed (decoration) |
| enemy facing direction | drawing | lost; visible from motion |

**Items and blocks**

| Information | Original cue | Simplified ROM |
|---|---|---|
| super mushroom vs 1-up | palette (red vs green) | added: green vs dark green |
| fire flower | drawing, flashing | added: deep blue, the fire-Mario colour; the flashing is removed |
| star | drawing, flashing | added: pale pink; the flashing is removed |
| coins, coins from blocks | drawing | kept: light yellow |
| ?-block vs used block | orange flashing vs brown | kept: dark orange vs terrain white (neither pulses) |
| block that has just been hit | bounces, already drawn as what it becomes | kept: the bouncing block is white if it becomes a used block (question block, brick that held an item, hidden block), grey if it stays a brick |
| brick vs hard block | drawing | kept: grey vs white |
| content of a brick or block, hidden blocks | none (invisible in the original) | same as original |
| enterable pipe | none in the original | same as original |
| vine (climbable) | drawing | added: interactive dark orange (the original draws it in the mushroom palette) |
| springboard | drawing, compression frames | added: interactive dark orange, with stripes; the compression frames are kept; its solid base is terrain white |
| moving / falling lifts | drawing, motion | kept: white bars, motion |
| which two lifts are linked (balance lifts) | rope and pulleys | lost: the rope is decoration and is transparent; visible from their motion |
| Bullet Bill cannon | drawing | added: the barrel, where the bullets come out, is dark red (launcher); the pedestal and the column are terrain white |
| flagpole, flag, ball | drawing | kept: purple |
| axe (castle levels) | drawing | drawn in the coin colour: its background palette has no goal colour |
| end-of-level castle | drawing | removed (decoration; the level visibly ends at the flagpole) |
| pits | absence of ground | same as original |
| area theme (day, night, underground, water, castle) | palettes and decoration | removed by design; ceilings and walls remain terrain |

**Events and HUD**

| Information | Original cue | Simplified ROM |
|---|---|---|
| points earned (100, 200, ..., 1UP) | floating white numbers | kept, in the coin colour; the flagpole score is purple |
| coin collected, block bumped | sprite animations | kept (see "block that has just been hit") |
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
  the bar; a resting shell has a 1 px strip of box above it; Bowser has a box
  on his front half only. Drawing those pixels would require extra sprite
  entries, i.e. code changes, so they are not drawn.
* **Small residuals**, as measured by `audit_colours.py` on the dataset
  (section 5). The Paratroopa's wing bar is outside the box on purpose
  (section 3.3). A Lakitu that the game re-creates after one was defeated has
  a 4x4 collision box instead of the 12x12 one, and is still drawn 12x12 (5 %
  of Lakitu's frames in the dataset): his set-up ends in the routine that sets
  up Bowser's flame, which gives him the flame's box (the original game does
  this). A Koopa shell that a block bumped from below has turned over is drawn
  4 px below its box: the game draws it from the same two tiles as a stomped
  shell, 3 px lower relative to the box, and the tiles are fitted to the
  stomped shell, which is far more common (it could be given tiles of its own,
  as the Spiny egg was; this was not done). A hammer in flight takes two of
  the sprite slots of an enemy or of a power-up that is on screen with it,
  which is then drawn with a row missing (the original game does this). The
  box of an object can lag its rectangle by 1 to 3 px, because the game
  computes the box before the final position update of the frame: Mario's
  rectangle is exactly his box in 97.2 % of his frames. A Spiny egg that is
  defeated in the air (by a fireball or under star power) falls as separate
  pieces instead of a rectangle: the game draws a defeated enemy upside down,
  and the four tiles of the egg then no longer line up; on the original ROM
  the two halves of the egg do not either. No egg is defeated in the air in
  the dataset.
* **Castle.** The end-of-level castle is decoration and is transparent. Two
  things that it hid are therefore visible after the flagpole: the brick
  that the game puts in the castle doorway to stop Mario's walk (a lone grey
  block), and Mario himself, who stands beside it while the timer counts
  down instead of disappearing through the door.
* **Ropes.** The ropes and pulleys of the balance lifts are transparent, like
  every other decoration: that two lifts are linked shows only in their
  motion.
* **Fire Mario** is deep blue, next to Mario's light blue; his fireballs and
  the fire flower share that colour. Star power shows as light blue / dark
  green / green / grey flashing, because the game rotates Mario's palette
  attribute and index 1 of each sprite palette is what it is; the star item
  itself no longer flashes.
* **Interactive vs enemy.** The interactive dark orange and the enemy red
  are neighbouring NES hues of the same brightness (section 3.4); they are
  told apart by shape and motion as much as by colour, and may be hard to
  tell apart for observers with a red-green colour-vision deficiency, as may
  the dark red of the cannon barrels.
* **Shared tiles within a category** cannot be told apart: the green and the
  red Koopa, the Buzzy Beetle and the other enemies, all share the category
  colour (section 6).
* **Axe.** The axe of the castle levels is drawn in the coin colour, not in
  the goal colour: its metatile uses background palette 3, which has no slot
  left.
* **HUD.** The status line uses the text and coin entries, so the text is
  white, like the terrain, and the coin icon has the colour of the coins.
* **Shape information is reduced to the box.** Objects are distinguished by
  colour, by the size of their collision box and by the shape marks of
  section 3.3; pose is gone.
* **Savestates carry a palette, the sound state and a drawn screen.** A
  recording's `Core.bin` keeps the original palette until the next area
  load, which shows on its first "WORLD x-y" screen (original Mario icon
  colours) and, for recordings that start mid-level, in the level itself;
  the latter also keep playing the original tune until the end of its
  current section, and keep on screen what the original ROM had already
  drawn (castle, pipes, ropes) until it scrolls away. Rewrite them with
  `code/fix_state.py` (section 5). The level states of this repository are
  already rewritten.
* **Sound cues are one tone each.** Pitch, length and duty cycle are the
  only differences between cues, so two cues close in pitch (e.g. the coin
  and the extra life) are told apart mainly by their length; the values in
  `CUES` are meant to be tuned by listening. Cues on the same channel
  interrupt each other, as in the original; a tune note that starts while
  an effect plays on square 2 is skipped, as in the original. Two details
  of the original are not reproduced: when two effects of a channel are
  queued on the same frame, both ROMs play the lowest queued bit, but the
  original first gives precedence to bit 7 (the small-Mario jump on square 1,
  Bowser's fall on square 2); and the original does not let another effect
  interrupt the extra-life sound.
* **Effects and tunes share a channel.** As in the original, an effect takes
  the square-2 channel from a tune, and a tune note that starts while an
  effect plays there is skipped. With tunes reduced to one to three tones, a
  whole tone can go: the star-power hum is silent from an effect of square 2
  (coin, item, power-up, Bullet Bill shot) until its next note, at most 24
  frames later; a beep of the time warning can be missed; and the death tone
  is shortened when a new effect starts while it sounds (43 of the 8046 death
  tones of the dataset, each time by the sound of a Bullet Bill being fired).
  What the music handler no longer does is silence a cue that is playing: the
  three places where it did are changed (section 3.5).
* **Code changes.** Unlike the tile and palette changes, which only touch
  data, the sound-effect handler is new code, the music handler is changed in
  three places, and six gameplay bytes name a different queue bit. The
  argument that this is gameplay-neutral is in section 3.5 and was tested in
  section 5, but it rests on reading the code, not only on the emulator's
  memory map. In the drawing code, besides operands that name a palette or a
  tile, two instructions are replaced by one of the same size and timing (the
  shift of the palette number of a bumped used block is a no-operation, and
  the decrement that raised the cannon-fired Bullet Bill applies to a dead
  byte, which leaves scratch byte `$0002` one higher, section 5.1), and the
  fire bars are drawn by a copy of their routine (section 3.2).
* **Castle levels.** The `Level?-4.state` files, inherited from
  `mario.stimuli`, are not savestates (they are an 813-byte JSON file) and
  cannot be loaded; castle levels are not part of the dataset.
* **Objects absent from the dataset** (the two water levels, and the castle
  levels: Bowser, Podoboos, Bowser's flames, fire bars, the axe) were placed
  from the graphics tables or left as full squares, and their rendering was
  not verified on recordings, except for the fire bars and the Podoboos of
  3-4, which one recording reaches. A fire bar is a chain of red 8x8 squares,
  the sprites as they are: the game does not test it against Mario with a
  box but by comparing positions (each square against Mario's sprite, 8 px
  either side of a point 4 px right of its left edge, and over the height of
  the sprite rather than of his box), so a square can overlap the edge of his
  rectangle without hurting him and can hurt big Mario from up to 7 px above
  it. The Podoboo is a 16x16 square around a 10x6 box.
