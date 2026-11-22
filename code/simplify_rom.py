#!/usr/bin/env python3
"""Build the "simplified" Super Mario Bros ROM from the original ROM.

Design
------
* Anything the player cannot interact with (clouds, bushes, hills, trees,
  fences, castle decoration, water surface, sea plants, ropes, fireworks,
  brick debris, Lakitu's cloud, Paratroopa wings...) becomes transparent,
  i.e. shows the uniform backdrop.
* Every background object the player interacts with becomes a flat square,
  and every sprite object becomes a flat rectangle the exact size and
  position of its collision box (the game computes that box from the
  object's position plus a 4-byte offset entry, so it never depends on the
  art; see HITBOX below).  Colour is a semantic category, identical in every
  level:

      backdrop    black        everything non-interactive (also the WORLD x-y screens)
      immutable   white        ground, stairs, hard blocks, pipes, tree/mushroom
                               ledges, cloud terrain, bridges, used blocks (also
                               while they bounce), cannon pedestals and columns,
                               moving platforms
      breakable   grey         bricks (also while they bounce)
      interactive dark orange  question blocks, springboards, vines
      collectible light yellow coins in the level, coins popping out of blocks,
                               the HUD coin icon, floating score numbers
      item        green        super mushroom
      1-up        dark green   1-up mushroom
      star        pale pink    starman
      launcher    dark red     the barrel of a Bullet Bill cannon
      enemy       red          every enemy and enemy projectile
      Mario       light blue   the player (flashes blue/green/grey when
                               invincible)
      fire Mario  deep blue    Mario after a fire flower, his fireballs, and
                               the fire flower itself
      goal        purple       flagpole, ball and flag, flagpole score

* A few *shapes* carry state that colour cannot (see the sets after HITBOX):
      Mario has a 2x2 "eye" hole on the side he faces;
      Koopa/Buzzy shells and dying Mario are hollow (2-px ring);
      Spiny, Spiny eggs and Piranha Plants (cannot be stomped) have a
      toothed top edge;
      a Paratroopa carries a 8x2 wing bar just above its box;
      a squished Goomba is a 16x4 bar, the springboard is striped.

* Sound follows the same rule.  All music is removed (silence), except the
  star-power tune, which becomes a low continuous hum while Mario is
  invincible.  Every sound effect that carries game information becomes one
  constant tone (a pitch, a duration, a square duty or a noise period) per
  category, and the decorative ones (fireworks, the end-of-level timer
  count, pipe entry) are removed.  The tunes that the game itself waits for
  (death, level clear, game over, time warning) become one to three plain
  tones followed by silence and keep their exact length.  See CUES / TUNES.

How the ROM is changed
----------------------
* CHR-ROM (tile graphics) is rewritten from the tables below.
* Sound (PRG-ROM $F2D0-$FFFF, the sound engine): the three sound-effect
  handlers are replaced by one table-driven routine assembled at build time,
  the tune data and headers are rewritten for the music handler, and five
  1-6 byte operands are changed (the area-music selection table, the queue
  bit of the swim stroke, of pipe entry and of fireworks, and two envelope
  constants).  The music handler is unchanged but for three places where it
  would silence a cue that is playing (a cue writes its channel once, the
  original effects rewrite theirs on every frame): the silent drum beats no
  longer write the noise channel, the end of a tune no longer silences a
  square channel that is playing an effect, and the death tune clears the
  effect of square 2 instead of only stopping it (see SOUND_SITES, TUNE_END
  and SFX_CALLS).  All of this is gameplay-neutral because game logic only
  ever writes the sound queues and reads back one byte, EventMusicBuffer,
  to wait for the death and level-clear tunes, whose lengths are preserved
  (asserted).  The sound engine's RAM ($F0-$FF, $07B0-$07CA) does differ
  from the original ROM and is masked by verify_replays.py; every other
  byte still matches.
* PRG-ROM otherwise: only *presentation data* is patched, never code paths
  or level data:
    - the 4 area palette sets, the day/night snow and mushroom palette
      variants, the Bowser palette, the player palette rows, the
      backdrop-colour table, and the palette-3 rotation tables the game uses
      to make ?-blocks and coins flash (all are copied verbatim into the PPU
      write buffer);
    - bytes of the metatile graphics lookup table: 4 so pipe shafts stop
      sharing tile $26 with the (transparent) hills, 28 so the end-of-level
      castle (decoration) is drawn with blank tiles instead of brick tiles,
      6 so the vertical ropes of balance lifts (decoration) stop being drawn
      with the flagpole-shaft tiles (and 4 immediate operands of the routine
      that draws the same rope tiles as a lift moves), and 4 so the solid
      base of a springboard is drawn with a terrain tile instead of the brick
      tile;
    - 6 bytes of the enemy graphics table (Bloober frame 2; one tile per
      quadrant of the Spiny egg), the 4-byte power-up attribute table, 7
      bytes of the 27-byte enemy attribute table (Buzzy Beetle, Goomba,
      Bloober and Bullet Bill leave sprite palette 3 for palette 2, the
      three springboard frames enter it) and the seven 4-byte hammer tables
      (one tile on the box, palette 3 -> 2);
    - immediate operands that choose the sprite palette of fireballs, coins
      popping out of blocks, bumped blocks, vines, floating score numbers,
      cannon-fired Bullet Bills, and that stop the fire flower / star
      palette cycling;
    - two instructions of the drawing code, each replaced by one of the
      same size and timing: the shift that halved the palette number of a
      bumped block outside ground areas (now a no-operation) and the
      decrement that raised the cannon-fired Bullet Bill by one pixel (now
      decrements a dead byte);
    - the fire bars of the castle levels are drawn by a copy of the routine
      they share with Mario's fireballs, with another tile and palette
      (FIREBAR): the operand of one "jsr", and 25 bytes in the space freed
      by the sound-effect handlers (so not with --no-sound).
  These bytes only feed the PPU write buffers ($0300-$03FF while a buffer is
  queued) and the sprite buffer ($0200-$02FF), through zero-page scratch
  $0002 and $0004 (the row and the palette of the sprite being drawn), which
  game logic never reads back.  RAM outside those buffers and the sound
  engine's own bytes, .bk2 replays and savestates therefore stay identical
  to the original ROM (verified on participant replays, see
  verify_replays.py; audit_colours.py checks the rendering itself).

Usage: simplify_rom.py ORIGINAL.nes OUTPUT.nes [--no-hitbox] [--no-marks] [--no-pipes] [--no-palette] [--no-sound] [--summary]
  --no-hitbox : draw every sprite tile as a full 8x8 square (v5 look)
  --no-marks  : no eye / hollow / teeth / wing / stripe shapes
  --no-sound  : keep the original music and sound effects (and the fire bars in the fireball colour: see FIREBAR)
  --summary   : also print how many bytes changed, per kind of change
"""
import sys, hashlib

# ---------------------------------------------------------------- colours --
# NES master-palette indices.  Change these to retune the look.
C = dict(
    backdrop=0x0F, terrain=0x30, brick=0x10, qblock=0x17, coin=0x38,
    item=0x2A, oneup=0x1A, star=0x35, enemy=0x16, cannon=0x06, mario=0x21, mario_fire=0x12,
    goal=0x24, text=0x30,
)
# 'qblock' is the colour of everything interactive (hit it or use it: ?-blocks, springboards,
# vines), 'terrain' of everything immutable, 'brick' of everything breakable, 'coin' of the
# collectible coins and 'cannon' of the barrel a Bullet Bill is fired from.

# Each palette group holds 3 usable colours (index 1..3).  The tile tables
# below choose an index; these rows choose what colour each index means.
BG_PAL = [
    [C['backdrop'], C['item'],   C['terrain'], C['goal']],   # BG0: pipes, ledges, flagpole (index 1 is not used by any tile)
    [C['backdrop'], C['brick'],  C['terrain'], C['cannon']], # BG1: ground, bricks, hard blocks, cannons
    [C['backdrop'], C['text'],   C['terrain'], C['goal']],   # BG2: HUD text, cloud terrain (index 3 is not used by any tile)
    [C['backdrop'], C['qblock'], C['terrain'], C['coin']],   # BG3: ?-blocks, used blocks, coins, HUD coin icon, axe
]
SPR_PAL = [
    [C['backdrop'], C['mario'],  C['star'],    C['mario_fire']],  # SPR0: Mario, star, fire flower, fireballs (overridden by PLAYER_PAL)
    [C['backdrop'], C['oneup'],  C['enemy'],   C['goal']],   # SPR1: koopas, hammer bros, piranha, lakitu, flag, 1-up, flagpole score
    [C['backdrop'], C['item'],   C['enemy'],   C['terrain']],# SPR2: every other enemy, hammers, mushroom, platforms, bumped used block
    [C['backdrop'], C['brick'],  C['qblock'],  C['coin']],   # SPR3: bumped brick, springboard, vine, coins, score numbers
]
PLAYER_PAL = [                      # rows used by the game: Mario / Luigi / fire Mario
    [C['backdrop'], C['mario'],      C['star'], C['mario_fire']],
    [C['backdrop'], C['mario'],      C['star'], C['mario_fire']],
    [C['backdrop'], C['mario_fire'], C['star'], C['mario_fire']],
]
# Star power makes the game cycle Mario's sprite through the 4 sprite palettes
# (it rotates the attribute bits, not the colours).  Mario's tiles use index 1
# so that this flashes light blue / dark green / green / grey, never enemy red.
# No enemy is drawn with sprite palette 3 (see ENEMY_ATTRIBUTES below), which is
# what frees its index 2 for the interactive colour.

# ----------------------------------------------- background tiles ($1000) --
# None -> transparent; 1/2/3 -> solid square of that palette index;
# 'remap3' -> keep the original pixel shape but paint it in index 3.
# Unlisted tiles keep their original pixels (text, HUD...).
BG = {}
def _set(ids, v):
    for i in ids: BG[i] = v
_set([0x25, 0x26, 0x27], None)                     # solid fills: bush, hill/pipe interior, black (castle windows/door)
_set(range(0x30, 0x3D), None)                      # hill outlines, bushes, clouds
_set([0x7F, 0xC0], None)                           # chain, bridge guard rail
_set(range(0xB8, 0xC0), None)                      # background trees
_set([0x80, 0x81, 0xA0, 0xA1], None)               # fence
_set([0x9B, 0x9C, 0x9D, 0x9E, 0xA9, 0xAA], None)   # castle roof / entrance top
_set([0x41], None)                                 # water / lava surface line
_set([0xA4, 0xE9, 0xEA, 0xEB], None)               # sea plant
_set([0x99, 0x3E, 0x3F, 0x5B, 0x5C], None)         # balance-lift ropes and pulleys
_set([0x75, 0x76], None)                           # mushroom stump top (non solid)
_set([0xB4, 0xB5, 0xB6, 0xB7], 2)                  # ground                 (terrain)
_set(range(0xAB, 0xAF), 2)                         # hard / stair block     (terrain)
_set([0x5D, 0x5E, 0x82, 0x83, 0x84, 0x85], 2)      # white-wall solid block (terrain)
_set(range(0xC6, 0xCA), 3)                         # bullet bill cannon barrel, where the bullets come out (cannon)
_set(range(0xCA, 0xCE), 2)                         # cannon pedestal        (terrain)
_set([0x2A, 0x40], 2)                              # cannon column          (terrain)
_set([0xC1], 2)                                    # bridge                 (terrain)
_set([0x52], None)                                 # green ledge stump under tree ledges: decoration, never in the block buffer
_set(range(0x60, 0x6B), 2)                         # vertical pipes         (terrain)
_set(range(0x86, 0x95), 2)                         # sideways pipes         (terrain)
_set(range(0x4B, 0x52), 2)                         # tree-top ledges        (terrain)
_set(list(range(0x6B, 0x75)) + [0x2C, 0x2D], 2)    # giant mushroom platforms (terrain)
_set([0xB0, 0xB1, 0xB2, 0xB3], 2)                  # cloud terrain          (terrain)
_set(range(0x57, 0x5B), 2)                         # used (empty) block     (terrain)
_set([0x45, 0x47], 1)                              # bricks                 (brick)
_set(range(0x53, 0x57), 1)                         # ? block                (qblock)
_set(range(0xA5, 0xA9), 3)                         # coin                   (coin)
_set(range(0xC2, 0xC6), 3)                         # underwater coin        (coin)
_set([0x2F, 0x3D], 3)                              # flagpole ball          (goal)
_set([0xA2, 0xA3], 'remap3')                       # flagpole shaft, kept thin (goal)
_set([0x7B, 0x7C, 0x7D, 0x7E], 3)                  # axe: its metatile uses BG palette 3, so index 3 is the coin colour (no goal slot there)
_set([0x77, 0x79], 2)                              # Bowser bridge          (terrain)
_set([0x2E], 'remap3')                             # HUD coin icon: shape kept, painted in the coin colour (it shared the ?-block index)

# --------------------------------------------------- sprite tiles ($0000) --
# Ownership measured from 66 participant replays (OAM buffer vs object slots).
SPR = {i: 2 for i in range(0x00, 0xF6)}            # default: enemy colour index
def _spr(ids, v):
    for i in ids: SPR[i] = v
_spr(list(range(0x00, 0x50)) + list(range(0x58, 0x60)) + list(range(0x90, 0x94)) + [0x9E, 0x9F], 1)  # Mario (SPR0 idx1)
_spr(list(range(0x76, 0x7A)), 1)                   # mushroom (SPR2 idx1 = item) / 1-up (SPR1 idx1 = 1-up colour)
_spr([0x8D, 0xE4], 2)                              # star (moved to SPR0 idx2 = star colour)
_spr([0xD6, 0xD9], 3)                              # fire flower (moved to SPR0 idx3 = fire-Mario colour)
_spr([0xE0, 0xE1], 2)                              # vine (moved to SPR3 idx2 = interactive)
_spr(list(range(0x60, 0x64)), 3)                   # coin popping out of a block (moved to SPR3 idx3 = coin)
_spr([0x64, 0x65], 3)                              # Mario's fireball (moved to SPR0 idx3 = fire-Mario colour)
_spr([0x82, 0x83], 2)                              # fire-bar segment (castle levels; SPR2 idx2 = enemy).  The original draws it with the fireball tiles;
                                                   # see FIREBAR below.  These two tiles were hammer frames, which the hammer no longer uses
_spr([0x87], 3)                                    # bumped block that turns into a used block: it is drawn as the used block (moved to SPR2 idx3 = terrain)
_spr([0x85, 0x86], 1)                              # bumped brick that stays a brick (SPR3 idx1 = brick)
_spr([0x84], 0)                                    # brick debris: transparent
_spr([0x5B, 0x75], 3)                              # moving platforms (SPR2 idx3 = terrain)
_spr(list(range(0xF0, 0xF4)), 2)                   # springboard (moved to SPR3 idx2 = interactive)
_spr([0x7E, 0x7F], 3)                              # flagpole flag (SPR1 idx3 = goal)
_spr([0x66, 0x67, 0x68, 0x54, 0x55, 0x56, 0x57], 0)  # fireworks, castle flag: transparent
_spr([0x74], 0)                                    # air bubbles of the water areas: transparent (decoration)
_spr([0xFF], 'text3')                              # sprite 0: the two rows that complete the HUD coin icon (SPR3 idx3 = coin). Its shape must not
                                                   # change: the game waits for it to overlap the icon to split the screen below the status bar
_spr(list(range(0xF6, 0xFC)) + [0xFD, 0xFE, 0x50], 'text3')  # floating score digits, "1UP" and the "00" of 1000+ ($50, also used by the flagpole score): glyph kept, index 3 (SPR3 = coin colour, SPR1 = goal)

# ------------------------------------------------- collision-box geometry --
# tile: (dx, dy, w, h).  The game computes an object's collision box as its
# screen position plus one of 12 four-byte offset entries (BoundBoxCtrlData),
# and draws its tiles at fixed offsets from the same position.  (dx, dy) is
# the position of the tile's top-left pixel relative to the top-left corner of
# the box and (w, h) the box size (right/bottom edges exclusive); a tile then
# only keeps the pixels that fall inside the box.  Measured on 66 participant
# replays by reading the live boxes at $04AC-$04DB together with the sprite
# buffer (code/hitbox_survey.py); horizontal/vertical flips folded.  Tiles
# not listed keep their full 8x8 square.
HITBOX = {
# Koopa (12x12 box; rows -9/-1/7); shells 6E,6F
    0x6E:(-2,-5,12,12), 0x6F:(-2,3,12,12), 0xA0:(6,-9,12,12), 0xA1:(-2,-1,12,12), 0xA2:(6,-1,12,12), 0xA3:(-2,7,12,12),
    0xA4:(6,7,12,12), 0xA5:(6,-9,12,12), 0xA6:(-2,-1,12,12), 0xA7:(6,-1,12,12), 0xA8:(-2,7,12,12), 0xA9:(6,7,12,12),
# Buzzy Beetle and its shell
    0xAA:(-2,-1,12,12), 0xAB:(6,-1,12,12), 0xAC:(-2,7,12,12), 0xAD:(6,7,12,12), 0xAE:(-2,-1,12,12), 0xAF:(6,-1,12,12),
    0xB0:(-2,7,12,12), 0xB1:(6,7,12,12), 0xF4:(-2,3,12,12), 0xF5:(-2,-5,12,12),
# red Koopa shell
    0x6D:(-2,-5,12,12),
# Hammer Bro (8x24 box; rows -4/4/12)
    0x7C:(4,-4,8,24), 0x7D:(-4,-4,8,24), 0x88:(4,4,8,24), 0x89:(-4,4,8,24), 0x8A:(4,12,8,24), 0x8B:(-4,12,8,24),
    0x8C:(4,4,8,24), 0xD1:(-4,4,8,24), 0xD2:(4,12,8,24), 0xD3:(-4,12,8,24), 0xD4:(4,-4,8,24), 0xD5:(-4,-4,8,24),
    0xE2:(4,4,8,24), 0xE3:(-4,4,8,24),
# Goomba (10x6 box; rows -6/2)
    0x70:(-3,-6,10,6), 0x71:(5,-6,10,6), 0x72:(-3,2,10,6), 0x73:(5,2,10,6),
# Piranha Plant (10x6 box; rows -14/-6/2)
    0xE5:(-3,-14,10,6), 0xE6:(-3,-6,10,6), 0xEB:(-3,2,10,6), 0xEC:(-3,-14,10,6), 0xED:(-3,-6,10,6), 0xEE:(-3,2,10,6),
# Paratroopa wing tiles
    0x69:(-2,-9,12,12), 0x6A:(-2,-1,12,12), 0x6B:(-2,-9,12,12), 0x6C:(-2,-1,12,12),
# Lakitu (12x12)
    0xB8:(6,-9,12,12), 0xB9:(-2,-9,12,12), 0xBA:(6,-1,12,12), 0xBB:(-2,-1,12,12), 0xBC:(-2,7,12,12), 0xBD:(-2,-1,12,12),
# Spiny (10x6; rows -6/2)
    0x96:(-3,-6,10,6), 0x97:(5,-6,10,6), 0x98:(-3,2,10,6), 0x99:(5,2,10,6), 0x9A:(-3,-6,10,6), 0x9B:(5,-6,10,6), 0x9C:(-3,2,10,6), 0x9D:(5,2,10,6),
# Spiny egg, i.e. the Spiny while it falls from Lakitu (same box, same rows).  The game draws its left column as is and its right
# column mirrored both ways (MIRRORED below), and the original table used each tile once on the left and once on the right, at
# another height, which no carving can fit.  SPRITE_PATCHES gives each of the four quadrants its own tile in both animation
# frames: $8E top left, $8F top right, $95 bottom left, $94 bottom right.
    0x8E:(-3,-6,10,6), 0x8F:(5,-6,10,6), 0x95:(-3,2,10,6), 0x94:(5,2,10,6),
# Cheep-cheep (10x6)
    0xB2:(-3,-6,10,6), 0xB3:(5,-6,10,6), 0xB4:(-3,2,10,6), 0xB5:(5,2,10,6), 0xB6:(-3,-6,10,6), 0xB7:(-3,2,10,6),
# Bullet Bill (10x6 box; rows -6/2).  The original enemy routine drew the one fired by a cannon a pixel above its position
# ("dec $02" at $E8C2) and the one of the frenzy levels (5-3, 6-3) at its position, with the same tiles and the same box, so no
# carving fitted both.  SPRITE_PATCHES makes that instruction decrement a dead byte instead: both are drawn at their position.
    0xE7:(5,-6,10,6), 0xE8:(-3,-6,10,6), 0xE9:(5,2,10,6), 0xEA:(-3,2,10,6),
# fireball (8x8)
    0x64:(0,0,8,8), 0x65:(0,0,8,8),
# big Mario (12x24 box, rows at -8/0/8/16)
    0x00:(-2,-8,12,24), 0x01:(6,-8,12,24), 0x02:(-2,0,12,24), 0x03:(6,0,12,24), 0x04:(-2,8,12,24), 0x05:(6,8,12,24),
    0x06:(-2,16,12,24), 0x07:(6,16,12,24), 0x08:(-2,-8,12,24), 0x09:(6,-8,12,24), 0x0A:(-2,0,12,24), 0x0B:(6,0,12,24),
    0x0C:(-2,8,12,24), 0x0D:(6,8,12,24), 0x0E:(-2,16,12,24), 0x0F:(6,16,12,24), 0x10:(-2,-8,12,24), 0x11:(6,-8,12,24),
    0x12:(-2,0,12,24), 0x13:(6,0,12,24), 0x14:(-2,8,12,24), 0x15:(6,8,12,24), 0x16:(-2,16,12,24), 0x17:(6,16,12,24),
    0x18:(-2,-8,12,24), 0x19:(6,-8,12,24), 0x1A:(-2,0,12,24), 0x1B:(6,0,12,24), 0x1C:(-2,8,12,24), 0x1D:(6,8,12,24),
    0x1E:(-2,16,12,24), 0x1F:(6,16,12,24), 0x20:(-2,-8,12,24), 0x21:(6,-8,12,24), 0x22:(-2,0,12,24), 0x23:(6,0,12,24),
    0x24:(-2,8,12,24), 0x25:(6,8,12,24), 0x26:(-2,16,12,24), 0x27:(6,16,12,24), 0x28:(-2,0,12,24), 0x29:(6,0,12,24),
    0x2A:(-2,8,12,24), 0x2B:(6,8,12,24), 0x4A:(-2,8,12,24), 0x4B:(-2,16,12,24), 0x4C:(-2,0,12,24), 0x4D:(6,0,12,24),
    0x5C:(-2,16,12,24), 0x5D:(6,16,12,24), 0x5E:(-2,16,12,24), 0x5F:(6,16,12,24),
# small Mario (10x12 box, rows at -4/4)
    0x2C:(-3,4,10,12), 0x2D:(5,4,10,12), 0x32:(-3,-4,10,12), 0x33:(5,-4,10,12), 0x34:(-3,4,10,12), 0x35:(5,4,10,12),
    0x36:(-3,-4,10,12), 0x37:(5,-4,10,12), 0x38:(-3,4,10,12), 0x39:(5,4,10,12), 0x3A:(-3,-4,10,12), 0x3B:(-3,4,10,12),
    0x3C:(5,4,10,12), 0x3D:(-3,-4,10,12), 0x3E:(5,-4,10,12), 0x3F:(-3,4,10,12), 0x40:(5,4,10,12), 0x41:(5,-4,10,12),
    0x42:(-3,4,10,12), 0x43:(5,4,10,12), 0x44:(-3,4,10,12), 0x45:(5,4,10,12), 0x4E:(-3,4,10,12), 0x4F:(-3,4,10,12),
    0x90:(-3,4,10,12), 0x91:(5,4,10,12), 0x92:(-3,4,10,12), 0x93:(5,4,10,12), 0x9E:(-3,-4,10,12), 0x9F:(-3,4,10,12),
# crouching Mario (12x12)
    0x58:(-2,-4,12,12), 0x59:(6,-4,12,12), 0x5A:(-2,4,12,12),
# hammer: tile $80 is drawn as a full 8x8 square on its 8x8 box (see SPRITE_PATCHES); $81-$83 are no longer drawn
# mushroom / 1-up (12x12; rows -1/7)
    0x76:(-2,-1,12,12), 0x77:(6,-1,12,12), 0x78:(-2,7,12,12), 0x79:(6,7,12,12),
# fire flower
    0xD6:(-2,-1,12,12), 0xD9:(-2,7,12,12),
# star
    0x8D:(-2,-1,12,12), 0xE4:(-2,7,12,12),
# swimming Mario: the big one was not seen in the dataset and is placed from the graphics tables
    0x2E:(-2,8,12,24), 0x2F:(6,8,12,24), 0x30:(6,8,12,24), 0x31:(-2,16,12,24),
    0x46:(-3,4,10,12), 0x47:(5,4,10,12), 0x48:(-3,4,10,12), 0x49:(5,4,10,12),
# Bloober (10x6 box; in the underwater bonus rooms of 5-2 and 6-2).  Each row is one tile, drawn as is on the left and mirrored on
# the right.  Frame 1: rows -3 ($DD) and 5 ($DE), its top row being blanked (SPRITE_PATCHES); frame 2: rows -6 ($DC) and 2 ($DF)
    0xDC:(-3,-6,10,6), 0xDD:(-3,-3,10,6), 0xDE:(-3,5,10,6), 0xDF:(-3,2,10,6),
# squished Goomba: no collision; drawn as a 16x4 bar on the ground
    0xEF:(0,-4,8,8),
}
MARIO_TILES = {t for t in HITBOX if t < 0x50 or 0x58 <= t < 0x60 or 0x90 <= t < 0x94 or t in (0x9E, 0x9F)}
HOLLOW   = {0x6D, 0x6E, 0x6F, 0xF4, 0xF5, 0x9E, 0x9F}          # Koopa/Buzzy shells, dying Mario: 2-px ring
SERRATED = set(range(0x96, 0x9E)) | {0x8E, 0x8F, 0x94, 0x95, 0xE5, 0xE6, 0xEB, 0xEC, 0xED, 0xEE}  # Spiny, egg, Piranha: toothed top edge
WINGS    = {0x69, 0x6B}                                        # Paratroopa wing tiles (row above the box): 8x2 bar
MIRRORED = {0x8F, 0x94}                                        # tiles the game only draws flipped both ways (right column of the Spiny egg): carved mirrored
STRIPED  = set(range(0xF0, 0xF4))                              # springboard: 2-px horizontal stripes

# ------------------------------------------------------ PRG data patches --
HDR, PRG, CHR = 16, 0x8000, 0x2000
ORIG_MD5 = "811b027eaf99c2def7b933c5208636de"
MT0, MT1 = 0x0B20, 0x0BBC                           # metatile graphics table (4 tiles per metatile: top left, bottom left, top right, bottom right), BG palette 0 and 1 entries
METATILE_PATCH = {  # file offset: (expected, new)
    MT0 + 4*0x15: (bytes([0x26,0x26,0x6A,0x6A]), bytes([0x69,0x69,0x6A,0x6A])),  # $15 vertical pipe shaft, right half: stop sharing tile $26 with the hills
    MT0 + 4*0x20: (bytes([0x26,0x93,0x26,0x93]), bytes([0x93,0x93,0x93,0x93])),  # $20 sideways pipe shaft, bottom half: idem
    MT1 + 4*0x00: (bytes([0xA2,0xA2,0xA3,0xA3]), bytes([0x24,0x24,0x24,0x24])),  # $40 vertical rope of a balance lift (decoration): it used the flagpole-shaft tiles
    MT1 + 4*0x02: (bytes([0x24,0xA2,0x3E,0x3F]), bytes([0x24,0x24,0x3E,0x3F])),  # $42 left pulley: idem
    MT1 + 4*0x03: (bytes([0x5B,0x5C,0x24,0xA3]), bytes([0x5B,0x5C,0x24,0x24])),  # $43 right pulley: idem
    MT1 + 4*0x28: (bytes([0x24,0x47,0x24,0x47]), bytes([0x24,0xB4,0x24,0xB4])),  # $68 solid base of the springboard: a terrain tile instead of the (breakable) brick tile
    MT1 + 4*0x2A: (bytes([0x24,0x47,0x24,0x47]), bytes([0x24,0xB4,0x24,0xB4])),  # $6A same graphic, solid as well
}
CASTLE_METATILES = MT1 + 4*0x05                     # metatile graphics table, palette-1 entries #05-#0B: the end-of-level castle
ROPE_OPERANDS = {   # DrawEraseRope ($D4E0): when a balance lift moves down, the game queues the two rope tiles above it straight into
                    # the PPU write buffer (not through a metatile); queue blank tiles instead, as it does when the lift moves up
    0x54FA: (bytes([0xA9,0xA2,0x9D,0x04,0x03,0xA9,0xA3,0x9D,0x05,0x03]), bytes([0xA9,0x24,0x9D,0x04,0x03,0xA9,0x24,0x9D,0x05,0x03])),
    0x552B: (bytes([0xA9,0xA2,0x9D,0x09,0x03,0xA9,0xA3,0x9D,0x0A,0x03]), bytes([0xA9,0x24,0x9D,0x09,0x03,0xA9,0x24,0x9D,0x0A,0x03])),
}
SPRITE_PATCHES = {  # file offset: (expected bytes, new bytes) - tables and immediate operands that pick an object's sprite palette
    0x6D0C: (bytes([0xA9, 0x02, 0x90, 0x02, 0x09, 0xC0]), bytes([0xA9, 0x00, 0x90, 0x02, 0x09, 0xC0])),  # fireball: palette 2 -> 0
    0x66C1: (bytes([0xA9, 0x02, 0x99, 0x02, 0x02, 0xA9, 0x82, 0x99, 0x06, 0x02]),
             bytes([0xA9, 0x03, 0x99, 0x02, 0x02, 0xA9, 0x83, 0x99, 0x06, 0x02])),                       # coin from block, both of its sprites: palette 2 -> 3
    0x667D: (bytes([0xA9, 0x02, 0x99, 0x02, 0x02, 0x99, 0x06, 0x02, 0xA9, 0xF7]),
             bytes([0xA9, 0x03, 0x99, 0x02, 0x02, 0x99, 0x06, 0x02, 0xA9, 0xF7])),                       # the "200" that follows it: palette 2 -> 3
    # DrawBlock ($EBD1) draws a bumped block with the brick tiles and its original palette 3 (index 1 = brick), unchanged;
    # when the block is turning into a used block it redraws it with the used-block tile $87:
    0x6C28: (bytes([0xA9, 0x03, 0xAE, 0x4E, 0x07]),       bytes([0xA9, 0x02, 0xAE, 0x4E, 0x07])),        # bumped used block: palette 3 -> 2 (index 3 = terrain)
    0x6C2E: (bytes([0xF0, 0x01, 0x4A, 0xA6, 0x08]),       bytes([0xF0, 0x01, 0xEA, 0xA6, 0x08])),        # ... in every area type (the original halved the palette number outside ground areas)
    0x66DE: (bytes([0x02, 0x01, 0x02, 0x01]),             bytes([0x02, 0x00, 0x00, 0x01])),              # PowerUpAttributes: mushroom 2, flower 1->0, star 2->0, 1-up 1
    0x6724: (bytes([0x4A, 0x29, 0x03, 0x0D, 0xCA, 0x03]), bytes([0x4A, 0x29, 0x00, 0x0D, 0xCA, 0x03])),  # flower/star top row: stop cycling the 4 palettes, use palette 0
    0x6471: (bytes([0xA9, 0x21, 0x99, 0x02, 0x02]),       bytes([0xA9, 0x23, 0x99, 0x02, 0x02])),        # vine: palette 1 -> 3 (behind-background bit kept)
    0x055B: (bytes([0xA9, 0x02, 0x99, 0x02, 0x02, 0x99, 0x06, 0x02]), bytes([0xA9, 0x03, 0x99, 0x02, 0x02, 0x99, 0x06, 0x02])),  # floating score numbers: palette 2 -> 3
    0x6790: (bytes([0xDC, 0xDC, 0xDD, 0xDD, 0xDE, 0xDE]), bytes([0xFC, 0xFC, 0xDD, 0xDD, 0xDE, 0xDE])),  # enemy graphics table, Bloober frame 2: blank top row (tile $DC is a body tile in frame 1)
    # EnemyAttributeData ($E85B), one byte per enemy graphic, OR-ed into the sprite attribute through scratch $04:
    # Buzzy Beetle ($02), Goomba ($06), Bloober ($07) and Bullet Bill ($08) leave sprite palette 3 for palette 2 (same
    # enemy colour), and the three springboard frames ($18-$1A) enter palette 3, whose index 2 is the interactive colour.
    0x686B: (bytes([0x01,0x02,0x03,0x02,0x01,0x01,0x03,0x03,0x03,0x01,0x01,0x02,0x02,0x21,0x01,0x02,0x01,0x01,0x02,0xFF,0x02,0x02,0x01,0x01,0x02,0x02,0x02]),
             bytes([0x01,0x02,0x02,0x02,0x01,0x01,0x02,0x02,0x02,0x01,0x01,0x02,0x02,0x21,0x01,0x02,0x01,0x01,0x02,0xFF,0x02,0x02,0x01,0x01,0x03,0x03,0x03])),
    0x68D4: (bytes([0xA9, 0x03, 0xBC, 0x8A, 0x07]),       bytes([0xA9, 0x02, 0xBC, 0x8A, 0x07])),        # cannon-fired Bullet Bill ($E8C4, hard-coded in a special case of the enemy routine): palette 3 -> 2
    # ... and the instruction just before it, "dec $02", which raised that Bullet Bill by one pixel ($02 holds the row being drawn):
    # it becomes "dec $04", same size and timing.  $04 is rewritten 4 instructions later ("sta $04" at $E8CD) on both paths, and
    # the flags it sets are overwritten by the "lda" that follows.  Side effect: $02 ends the routine one higher than on the
    # original ROM (see verify_replays.py).
    0x68D2: (bytes([0xC6, 0x02]),                         bytes([0xC6, 0x04])),
    # enemy graphics table, Spiny egg, frames 1 and 2 (rows of 2 tiles; the first row is blank).  One tile per quadrant, and the
    # same four in both frames (see HITBOX):
    0x677E: (bytes([0xFC,0xFC,0x8F,0x8E,0x8E,0x8F, 0xFC,0xFC,0x95,0x94,0x94,0x95]),
             bytes([0xFC,0xFC,0x8F,0x8E,0x94,0x95, 0xFC,0xFC,0x8F,0x8E,0x94,0x95])),
    0x6B64: (bytes([0xA9, 0x82, 0x99, 0x0A, 0x02]),       bytes([0xA9, 0x83, 0x99, 0x0A, 0x02])),        # springboard, its two lower rows ($EB54, hard-coded): palette 2 -> 3
    # Hammer ($E4C0, seven 4-byte tables indexed by animation frame, read only by DrawHammer): X and Y offsets of its first sprite,
    # X and Y offsets from the first to the second sprite, tile of each, attributes.  The original spins a 8x16 hammer around a 8x8
    # collision box that sits at the object's position: half of the first sprite lies in the box, the second sprite lies outside.
    # Now the first sprite is one full tile exactly on the box in every frame, the second sprite is blank, and the palette is 2.
    0x64D0: (bytes([0x04,0x00,0x04,0x00, 0x00,0x04,0x00,0x04, 0x00,0x08,0x00,0x08, 0x08,0x00,0x08,0x00, 0x80,0x82,0x81,0x83, 0x81,0x83,0x80,0x82, 0x03,0x03,0xC3,0xC3]),
             bytes([0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x00, 0x00,0x08,0x00,0x08, 0x08,0x00,0x08,0x00, 0x80,0x80,0x80,0x80, 0xFC,0xFC,0xFC,0xFC, 0x02,0x02,0xC2,0xC2])),
}
AREA_PALETTES = [0x0CB4, 0x0CD8, 0x0CFC, 0x0D20]   # water, ground, underground, castle: "3F 00 20" + 32 bytes
PLAYER_COLORS = 0x05E7                              # 3 rows x 4
BACKGROUND_COLORS = 0x05DF                          # 8 backdrop colours by area type / bg-colour control
BG0_VARIANTS = [0x0D44, 0x0D4C, 0x0D54]             # day snow, night snow, mushroom: "3F 00 04" + 4 bytes (BG palette 0)
BOWSER_PALETTE = 0x0D5C                             # "3F 14 04" + 4 bytes (sprite palette 1)
PALETTE3_DATA = 0x09E1                              # 4 rows (water/ground/underground/castle) x 4: BG palette 3 rewritten every 8 frames
COLOR_ROTATE = 0x09D3                               # 6 colours the game cycles into BG palette 3 index 1 (the ?-block/coin flash)

# ------------------------------------------------------------------ sound --
# The sound engine ($F2D0-$FFFF) runs inside the NMI handler.  Game logic
# talks to it through six queue bytes ($FA-$FF) and reads back exactly one
# thing: EventMusicBuffer ($07B1), polled for zero while Mario falls into a
# hole (death tune must end) and in the end-of-level sequence (level-clear
# tune must end).  Everything else the engine touches is its own state
# ($F0-$F9, $07B0-$07CA) and the APU registers.  So:
#   * sound effects can be anything, as long as the queue bits keep their
#     meaning (the three sfx handlers are replaced by one table-driven one);
#   * event tunes are rewritten as data for the unchanged music handler and
#     keep their exact frame count (asserted against the original data);
#   * area music is silenced by queueing "Silence" instead of a tune, and the
#     star-power tune becomes a looping hum;
#   * four gameplay sites get a 1-2 byte operand change so that the swim
#     stroke shares the jump cue, and pipe entry and fireworks land on unused
#     noise-channel bits that map to silence; each site overwrites the
#     register right after the store, so nothing else sees the new value.
def _cpu(a): return a - 0x8000 + HDR                # CPU address -> file offset

# Cues.  A cue is one constant tone: (frames, pitch, control byte).  pitch indexes the game's
# FreqRegLookupTbl (even values; 4 is a rest); the control byte is duty<<6 | $30 | volume for the
# square channels and $30 | volume for noise, whose "pitch" is the noise period (0-15).
NOTE = dict(G2=0x5A, C3=0x5C, D3=0x5E, E3=0x06, G3=0x0C, A3=0x62, C4=0x14, E4=0x1C, G4=0x22, A4=0x26,
            C5=0x2C, E5=0x34, G5=0x3A, A5=0x40, B5=0x42, D6=0x48, E6=0x44, REST=0x04)
def sq(frames, note, duty, vol=8): return (frames, NOTE[note], (duty << 6) | 0x30 | vol)
def noise(frames, period, vol=8):  return (frames, period, 0x30 | vol)
SILENT = (1, 0, 0x30)
CUES = dict(                       # name: cue                  visual category / meaning
    jump      = sq(6,  'E4', 2),   # Mario: jump (small and big) and swim stroke
    bump      = sq(4,  'G3', 0),   # terrain / block hit from below, fireball explodes, shell bumps
    enemy     = sq(6,  'C5', 1),   # enemy defeated (stomped, hit by fireball or shell, Bowser falls)
    injury    = sq(24, 'C3', 2),   # Mario shrinks
    fireball  = sq(3,  'A5', 0, 6),# fire Mario throws a fireball
    goal      = sq(64, 'A4', 2, 6),# flagpole slide
    coin      = sq(5,  'B5', 1),   # coin collected
    item      = sq(16, 'G4', 0, 6),# item emerges from a block, vine grows
    powerup   = sq(16, 'E5', 2),   # mushroom / flower / star collected
    oneup     = sq(16, 'G5', 1),   # extra life
    hazard    = sq(8,  'G2', 0),   # Bullet Bill fired (also Bowser's bridge collapsing)
    brick     = noise(12, 8),      # brick shatters
    flame     = noise(24, 12, 6),  # Bowser's flame
)
SFX_BITS = {                       # queue bit -> cue, per channel (bit order of the original engine)
    1: ['jump', 'bump', 'enemy', 'enemy', 'injury', 'fireball', 'goal', 'jump'],      # $FF: big jump, bump, stomp/swim, smack, pipe-injury, fireball, flagpole, small jump
    2: ['coin', 'item', 'item', 'hazard', None, 'powerup', 'oneup', 'enemy'],          # $FE: coin, power-up reveal, vine, blast, timer tick, power-up grab, 1-up, Bowser fall
    3: ['brick', 'flame', None, None, None, None, None, None],                         # $FD: brick shatter, Bowser flame, (pipe entry), (fireworks)
}
CHANNEL = {  # queue, buffer, sfx length counter, first APU register, $4015 mask with the channel off, SetFreq helper
    1: dict(QUEUE=0xFF, BUF=0xF1, CNT=0x07BB, REG=0x4000, MASK=0x0E, SETFREQ=0xF38B),
    2: dict(QUEUE=0xFE, BUF=0xF2, CNT=0x07BD, REG=0x4004, MASK=0x0D, SETFREQ=0xF3A9),
    3: dict(QUEUE=0xFD, BUF=0xF3, CNT=0x07BF, REG=0x400C, MASK=0x07, SETFREQ=None),
}
SFX_CODE = (0xF3B1, 0xF691)        # CPU range of the three original sfx handlers (SwimStompEnvelopeData .. ContinueMusic), replaced
SFX_CODE_SHA1 = "8b205259690963863a944d7073675d1568d8c202"
SFX_CALLS = {                      # file offset: (expected jsr operands, new targets by label)
    0x735B: ("20 1B F4 20 7C F5 20 67 F6", ['H1', 'H2', 'H3']),   # RunSoundSubroutines: Square1SfxHandler, Square2SfxHandler, NoiseSfxHandler
    0x76BB: ("20 A7 F4 20 71 F5",          ['S1', 'S2']),         # LoadEventMusic (death): StopSquare1Sfx, StopSquare2Sfx.  The original leaves the buffer of
                                                                  # square 2 set there, and the music routine skips a note that starts while it is set:
                                                                  # the death tune is one tone here, and was lost if an effect was playing.  Clear it (S2)
    0x76DC: ("20 A7 F4",                   ['S1']),               # LoadAreaMusic (underground): StopSquare1Sfx
}
SOUND_SITES = {  # file offset: (expected, new) - gameplay sites that queue a sound, and music data
    0x3510: ("A9 04 85 FF", "A9 01 85 FF"),   # swim stroke: queue the (big) jump bit instead of the stomp bit
    0x5DE3: ("A0 10 84 FF", "A0 04 84 FD"),   # sideways pipe entry: noise bit 2 (silent) instead of pipe/injury
    0x5F13: ("A9 10 85 FF", "A9 04 85 FD"),   # vertical pipe entry: idem
    0x52D1: ("A9 08 85 FE", "A9 08 85 FD"),   # fireworks: noise bit 3 (silent) instead of the blast
    0x10F7: ("02 01 04 08 10 20", "80 80 80 80 80 80"),   # MusicSelectData: water, ground, underground, castle, cloud, pipe intro -> Silence
    0x78E8: ("AD B1 07 29 08 F0 04 A9 04 D0 0C A5 F4 29 7D F0 04 A9 08 D0 02 A9 28",   # LoadControlRegs: no castle special case,
             "AD B1 07 29 00 F0 04 A9 04 D0 0C A5 F4 29 7D F0 04 A9 27 D0 02 A9 27"),  # every note starts at envelope index $27
    0x7904: ("AD B1 07 29 08 F0 04 B9 96 FF", "AD B1 07 29 00 F0 04 B9 96 FF"),       # LoadEnvelopeData: castle uses the usual tables too
    0x77B5: ("29 91 D0 13", "29 90 D0 13"),   # square 2 music: death tune goes through the envelope table like the others
    0x78A3: ("F0 24", "F0 2F"),               # noise music ($F893, $F89F): the two branches taken for a silent drum beat go straight to the
    0x78AF: ("F0 18", "F0 23"),               # routine's rts instead of writing a zero volume to the noise channel, which cut the brick cue short
}
# Two pieces of code are added after the sound-effect handler, in the space the three original handlers leave free:
#  * TUNE_END.  When a tune is over, the music routine silences both square channels ("lda #$90 / sta $4000 / sta $4004 / rts" at
#    $F76B).  The original effects rewrite their channel on every frame; a cue writes it once and was cut off.  Those four
#    instructions become a jump to the same writes, each skipped while an effect is playing on its channel (buffers $F1, $F2).
#  * FIREBAR.  The fire bars of the castle levels are drawn by the routine that draws Mario's fireballs (DrawFirebar, $ECED, 25
#    bytes, no jump inside), so they had his colour.  A copy of it with two other operands (tile $82/$83 instead of $64/$65, sprite
#    palette 2 instead of 0: the enemy colour) is assembled here, and the one "jsr DrawFirebar" of the fire-bar code calls the copy:
#    same instructions, same timing, and what it writes is a tile and an attribute byte of the sprite buffer.
TUNE_END = (0x777B, "A9 90 8D 00 40 8D 04 40 60")
TUNE_END_CODE = "A9 90 A6 F1 D0 03 8D 00 40 A6 F2 D0 03 8D 04 40 60"   # lda #$90 / ldx $F1 / bne +3 / sta $4000 / ldx $F2 / bne +3 / sta $4004 / rts
FIREBAR = (0xECED, "A5 09 4A 4A 48 29 01 49 64 99 01 02 68 4A 4A A9 02 90 02 09 C0 99 02 02 60")   # DrawFirebar in the original ROM
FIREBAR_TILE, FIREBAR_PALETTE = 0x82, 0x02
FIREBAR_CALL = (0x4E18, "20 ED EC")                # FirebarCollision ($CE08): jsr DrawFirebar
ENV_TABLES = 0xFF96                # EndOfCastleMusicEnvData(4) + AreaMusicEnvData(8) + WaterEventMusEnvData(40): volume per envelope index
MUSIC_VOL = 6                      # constant volume of every tune note (index 0 stays silent: rests)
MHD = 0xF90D                       # MusicHeaderData; headers are (length row, data lo, data hi, triangle offset, square-1 offset[, noise offset])
LEN_TBL, LEN_ROW = 0xFF66, 0x10    # MusicLengthLookupTbl; row $10 = [3, 6, 12, 24, 48, 18, 36, 8] frames
STAR_DATA = 0xF9B8                 # Star_CloudMData: replaced by the hum track followed by the silent-loop track
AREA_HEADERS = {0x69: 6, 0x6F: 6, 0x75: 6, 0x7B: 6, 0x81: 6, 0x87: 6, 0x8D: 6, 0x93: 6, 0x99: 6, 0x9F: 6,  # ground music sections
                0x5E: 6, 0x46: 5, 0x4F: 5}                                                                 # water, underground, castle
STAR_HEADER = 0x36
R = 'REST'
TUNES = {  # header offset from MHD: (name, length row, notes [(note, frames)...]); total frames are asserted against the original tune
    0xA5: ('death',        0x10, [('C3', 24), (R, 156)]),
    0x59: ('game over',    0x10, [('G2', 36), (R, 180)]),
    0x3C: ('level clear',  0x10, [('C4', 12), ('E4', 12), ('G4', 12), (R, 288)]),
    0x64: ('castle clear', 0x10, [('C4', 12), ('E4', 12), ('G4', 12), (R, 328)]),
    0x54: ('victory',      0x10, [('C4', 12), ('E4', 12), ('G4', 12), (R, 348)]),
    0x31: ('time warning', 0x08, [('A5', 6), (R, 6), ('A5', 6), (R, 6), ('A5', 6), (R, 138)]),  # row $08 + the engine's +8 = row $10
}
HUM = [('C3', 24)]                 # star power: this note, looped

def _hex(s): return bytes(int(b, 16) for b in s.split())

def asm(src, org, sym):
    """Two-pass assembler for the handful of 6502 instructions used by the sfx handler."""
    OPS = {('lda', 'imm'): 0xA9, ('lda', 'abs'): 0xAD, ('lda', 'abx'): 0xBD, ('sta', 'abs'): 0x8D,
           ('ldx', 'imm'): 0xA2, ('stx', 'abs'): 0x8E, ('inx', 'imp'): 0xE8, ('lsr', 'imp'): 0x4A,
           ('dec', 'abs'): 0xCE, ('jsr', 'abs'): 0x20, ('jmp', 'abs'): 0x4C, ('rts', 'imp'): 0x60,
           ('bcc', 'rel'): 0x90, ('beq', 'rel'): 0xF0, ('bne', 'rel'): 0xD0}
    SIZE = dict(imp=1, imm=2, rel=2, abx=3, abs=3)
    def mode(op, arg):
        if arg is None: return 'imp'
        if arg.startswith('#'): return 'imm'
        if op in ('bcc', 'beq', 'bne'): return 'rel'
        return 'abx' if arg.lower().endswith(',x') else 'abs'
    lines = []
    for raw in src.splitlines():
        raw = raw.split(';')[0].strip()
        if not raw: continue
        label, raw = (s.strip() for s in raw.split(':', 1)) if ':' in raw else (None, raw)
        parts = raw.split(None, 1)
        lines.append((label, parts[0].lower() if parts else None, parts[1].strip() if len(parts) > 1 else None))
    labels, pc = {}, org
    for label, op, arg in lines:
        if label: labels[label] = pc
        if op: pc += SIZE[mode(op, arg)]
    def val(s):
        s = s.lstrip('#'); s = s[:-2] if s.lower().endswith(',x') else s
        if s.startswith('$'): return int(s[1:], 16)
        assert s in labels or s in sym, f"unknown symbol {s}"
        return labels[s] if s in labels else sym[s]
    out, pc = bytearray(), org
    for label, op, arg in lines:
        if not op: continue
        m = mode(op, arg); out.append(OPS[(op, m)]); pc += SIZE[m]
        if m == 'imm': out.append(val(arg))
        elif m == 'rel':
            d = val(arg) - pc; assert -128 <= d < 128, arg; out.append(d & 0xFF)
        elif m in ('abs', 'abx'): v = val(arg); out += bytes([v & 0xFF, v >> 8])
    return bytes(out), labels

def sfx_handler(c):
    """One channel's handler: start the cue of the lowest queued bit, else count the playing cue down and stop it.
    Entry points: H<c> (per frame), S<c> (stop and clear the buffer), T<c> (stop, keep the buffer; the original calls it for square 2
    when the death tune starts, this build calls S2), as in the original."""
    p = CHANNEL[c]
    play = (f"jmp ${p['SETFREQ']:04X}" if p['SETFREQ'] else       # squares: A = pitch -> period registers, then rts
            "sta $400E\n lda #$08\n sta $400F\n rts")              # noise: A = period
    return f"""
H{c}:  lda ${p['QUEUE']:02X}
       beq C{c}
       sta ${p['BUF']:02X}
       ldx #$FF
F{c}:  inx
       lsr
       bcc F{c}                  ; X = index of the lowest set queue bit
       lda LEN{c},x
       sta ${p['CNT']:04X}
       lda CTRL{c},x
       sta ${p['REG']:04X}
       lda #$7F
       sta ${p['REG'] + 1:04X}    ; sweep off (negate set so no note is muted); harmless on the noise channel
       lda PITCH{c},x
       {play}
C{c}:  lda ${p['BUF']:02X}
       beq X{c}
       dec ${p['CNT']:04X}
       bne X{c}
S{c}:  ldx #$00
       stx ${p['BUF']:02X}     ; X only: the music handler calls S/T and keeps using A afterwards
T{c}:  ldx #${p['MASK']:02X}
       stx $4015
       ldx #$0F
       stx $4015                 ; switching the channel off and on clears its length counter: silence
X{c}:  rts
"""

def build_sfx(org):
    """Assemble the three handlers and their tables at CPU address org; return (code bytes, labels)."""
    src = "".join(sfx_handler(c) for c in (1, 2, 3))
    names = [f"{n}{c}" for c in (1, 2, 3) for n in ('LEN', 'PITCH', 'CTRL')]
    size = len(asm(src, org, {n: 0 for n in names})[0])         # the tables follow the code
    sym, tables = {}, b""
    for c in (1, 2, 3):
        cues = [CUES[n] if n else SILENT for n in SFX_BITS[c]]
        for k, name in enumerate(('LEN', 'PITCH', 'CTRL')):
            sym[f"{name}{c}"] = org + size + len(tables)
            tables += bytes(cue[k] for cue in cues)
    code, labels = asm(src, org, sym)
    assert len(code) == size
    return code + tables, labels

def decompose(frames, lens):
    """Split a duration into the fewest available note lengths (exact)."""
    best = {0: []}
    for t in range(1, frames + 1):
        opts = [best[t - L] + [L] for L in lens if t - L in best]
        if opts: best[t] = min(opts, key=len)
    assert frames in best, f"{frames} frames cannot be made from {lens}"
    return best[frames]

def track(notes, lens):
    """Square-2 track bytes for [(note, frames)...]: length bytes, notes, terminator, plus a $00 for the triangle offset."""
    out, cur = [], None
    for note, frames in notes:
        for L in decompose(frames, lens):
            if lens.index(L) != cur: cur = lens.index(L); out.append(0x80 | cur)
            out.append(NOTE[note])
    return bytes(out + [0, 0])

def tune_frames(rom, hdr, lens_all, adder=0):
    """Total frames of the square-2 track an original header points to (the tune's lifetime in EventMusicBuffer)."""
    row = rom[hdr] + adder                                        # the engine adds 8 for the time-running-out tune
    data = _cpu(rom[hdr + 1] | rom[hdr + 2] << 8); total = cur = 0; i = 0
    while rom[data + i]:
        b = rom[data + i]; i += 1
        if b & 0x80: cur = lens_all[row + (b & 7)]
        else: total += cur
    return total

def patch_sound(rom, firebar=True):
    lo, hi = map(_cpu, SFX_CODE)
    assert hashlib.sha1(rom[lo:hi]).hexdigest() == SFX_CODE_SHA1, "sfx handler region is not the original"
    code, labels = build_sfx(SFX_CODE[0])
    stop = SFX_CODE[0] + len(code); code += _hex(TUNE_END_CODE)
    _expect(rom, TUNE_END[0], _hex(TUNE_END[1]))
    rom[TUNE_END[0]:TUNE_END[0] + 9] = bytes([0x4C, stop & 0xFF, stop >> 8]) + b"\xEA" * 6      # jmp to the new code; the rest is never reached
    if firebar:
        copy = SFX_CODE[0] + len(code); fb = bytearray(_hex(FIREBAR[1]))
        assert bytes(rom[_cpu(FIREBAR[0]):_cpu(FIREBAR[0]) + 16]) == bytes(fb[:16]) and bytes(rom[_cpu(FIREBAR[0]) + 17:_cpu(FIREBAR[0]) + 25]) == bytes(fb[17:]), "DrawFirebar is not the original"
        fb[8], fb[16] = FIREBAR_TILE, FIREBAR_PALETTE
        assert (copy + 0x13) >> 8 == (copy + 0x15) >> 8, "the branch of the copy would cross a page: one more cycle than the original"
        code += bytes(fb)
        _expect(rom, FIREBAR_CALL[0], _hex(FIREBAR_CALL[1])); rom[FIREBAR_CALL[0] + 1:FIREBAR_CALL[0] + 3] = bytes([copy & 0xFF, copy >> 8])
    assert len(code) <= hi - lo
    rom[lo:hi] = code + b"\xFF" * (hi - lo - len(code))
    for off, (old, targets) in SFX_CALLS.items():
        _expect(rom, off, _hex(old))
        for k, t in enumerate(targets): rom[off + 3*k + 1:off + 3*k + 3] = bytes([labels[t] & 0xFF, labels[t] >> 8])
    for off, (old, new) in SOUND_SITES.items():
        _expect(rom, off, _hex(old)); rom[off:off + len(_hex(new))] = _hex(new)
    env = _cpu(ENV_TABLES)
    _expect(rom, env, [0x98, 0x99, 0x9A, 0x9B, 0x90, 0x94]); _expect(rom, env + 12, [0x90, 0x91, 0x92, 0x92])
    for base, n in ((0, 4), (4, 8), (12, 40)):
        rom[env + base:env + base + n] = bytes([0x90] + [0x90 | MUSIC_VOL] * (n - 1))
    lens_all = list(rom[_cpu(LEN_TBL):_cpu(LEN_TBL) + 48]); lens = lens_all[LEN_ROW:LEN_ROW + 8]
    hum, loop = track(HUM, lens), track([('REST', lens[3])], lens)
    hum += bytes([0x01, 0x00]); loop += bytes([0x01, 0x00])        # noise track: one silent beat, loop (a $00 first would spin the engine)
    _expect(rom, _cpu(STAR_DATA), [0x84, 0x2C, 0x2C, 0x2C]); rom[_cpu(STAR_DATA):_cpu(STAR_DATA) + len(hum + loop)] = hum + loop
    for off, size in list(AREA_HEADERS.items()) + [(STAR_HEADER, 6)]:
        hdr = _cpu(MHD) + off; data = STAR_DATA if off == STAR_HEADER else STAR_DATA + len(hum)
        rom[hdr:hdr + size] = bytes([LEN_ROW, data & 0xFF, data >> 8, 2, 0, 4][:size])   # triangle -> $00, square 1 off, noise -> silent beat
    for off, (name, row, notes) in TUNES.items():
        hdr = _cpu(MHD) + off; want = tune_frames(rom, hdr, lens_all, 8 if off == 0x31 else 0)
        assert sum(f for _, f in notes) == want, f"{name}: {sum(f for _, f in notes)} frames, original {want}"
        t = track(notes, lens); data = _cpu(rom[hdr + 1] | rom[hdr + 2] << 8)
        rom[data:data + len(t)] = t
        rom[hdr:hdr + 5] = bytes([row, rom[hdr + 1], rom[hdr + 2], len(t) - 2, 0])
    return rom

def solid(idx):
    lo = 0xFF if idx & 1 else 0x00
    hi = 0xFF if idx & 2 else 0x00
    return bytes([lo]*8 + [hi]*8)

def remap(tile, idx):
    """Keep the tile's shape; every non-zero pixel becomes palette index idx."""
    mask = [tile[r] | tile[r+8] for r in range(8)]
    lo = [m if idx & 1 else 0 for m in mask]
    hi = [m if idx & 2 else 0 for m in mask]
    return bytes(lo + hi)

def pack(px):
    lo = [sum(((px[r][c] & 1) << (7 - c)) for c in range(8)) for r in range(8)]
    hi = [sum(((px[r][c] >> 1 & 1) << (7 - c)) for c in range(8)) for r in range(8)]
    return bytes(lo + hi)

def carve(t, idx, hitbox=True, marks=True):
    """Sprite tile t in palette index idx, restricted to its collision box."""
    g = HITBOX.get(t) if hitbox else None
    if g is None and not (marks and t in STRIPED):
        return solid(idx)
    px = [[0]*8 for _ in range(8)]
    if g is None:                                    # striped springboard
        return pack([[idx if (r // 2) % 2 == 0 else 0]*8 for r in range(8)])
    dx, dy, w, h = g
    for r in range(8):
        for c in range(8):
            bx, by = dx + c, dy + r                  # (r, c) is the pixel as it appears on screen
            if not (0 <= bx < w and 0 <= by < h): continue
            v = idx
            if marks:
                if t in HOLLOW and 2 <= bx < w-2 and 2 <= by < h-2: v = 0
                if t in SERRATED and by < 2 and (bx // 2) % 2: v = 0
                if t in MARIO_TILES and t not in HOLLOW and w-4 <= bx < w-2 and 2 <= by < 4: v = 0
            if t in MIRRORED: px[7 - r][7 - c] = v
            else: px[r][c] = v
    if marks and t in WINGS:
        for r in (6, 7): px[r] = [idx]*8
    return pack(px)

def _expect(rom, off, header):
    assert bytes(rom[off:off+len(header)]) == bytes(header), f"unexpected bytes at {off:#x}"

def build(rom: bytes, patch_pipes=True, patch_palette=True, hitbox=True, marks=True, sound=True) -> bytes:
    assert len(rom) == HDR + PRG + CHR, "unexpected ROM size"
    rom = bytearray(rom)
    chr0 = HDR + PRG
    for t, v in SPR.items():
        off = chr0 + 16*t
        if v == 'text3':  rom[off:off+16] = remap(rom[off:off+16], 3)
        elif v:           rom[off:off+16] = carve(t, v, hitbox, marks)
        else:             rom[off:off+16] = bytes(16)
    for t, v in BG.items():
        off = chr0 + 0x1000 + 16*t
        if v is None:       rom[off:off+16] = bytes(16)
        elif v == 'remap3': rom[off:off+16] = remap(rom[off:off+16], 3)
        else:               rom[off:off+16] = solid(v)
    if patch_pipes:
        for off, (old, new) in list(METATILE_PATCH.items()) + list(ROPE_OPERANDS.items()):
            _expect(rom, off, old); rom[off:off+len(new)] = new
        _expect(rom, CASTLE_METATILES, [0x9D, 0x47, 0x9E, 0x47]); rom[CASTLE_METATILES:CASTLE_METATILES+28] = bytes([0x24]*28)
        for off, (old, new) in SPRITE_PATCHES.items():
            _expect(rom, off, old); rom[off:off+len(new)] = new
    if patch_palette:
        pal = bytes(sum(BG_PAL, []) + sum(SPR_PAL, []))
        for off in AREA_PALETTES:
            _expect(rom, off, [0x3F, 0x00, 0x20]); rom[off+3:off+35] = pal
        _expect(rom, PLAYER_COLORS, [0x22, 0x16, 0x27, 0x18])
        rom[PLAYER_COLORS:PLAYER_COLORS+12] = bytes(sum(PLAYER_PAL, []))
        _expect(rom, BACKGROUND_COLORS, [0x22, 0x22, 0x0F, 0x0F])
        rom[BACKGROUND_COLORS:BACKGROUND_COLORS+8] = bytes([C['backdrop']]*8)
        for off in BG0_VARIANTS:
            _expect(rom, off, [0x3F, 0x00, 0x04]); rom[off+3:off+7] = bytes(BG_PAL[0])
        _expect(rom, BOWSER_PALETTE, [0x3F, 0x14, 0x04]); rom[BOWSER_PALETTE+3:BOWSER_PALETTE+7] = bytes(SPR_PAL[1])
        _expect(rom, PALETTE3_DATA, [0x0F, 0x07, 0x12, 0x0F]); rom[PALETTE3_DATA:PALETTE3_DATA+16] = bytes(BG_PAL[3]*4)
        _expect(rom, COLOR_ROTATE, [0x27, 0x27, 0x27, 0x17, 0x07, 0x17]); rom[COLOR_ROTATE:COLOR_ROTATE+6] = bytes([C['qblock']]*6)
    if sound:
        patch_sound(rom, firebar=patch_pipes)
    return bytes(rom)

def summary(orig: bytes, out: bytes) -> dict:
    """Number of bytes that differ between the original and the built ROM, per kind of change."""
    span = lambda table: [(o, o + len(v[0])) for o, v in table.items()]
    groups = {
        "iNES header": [(0, HDR)],
        "PRG: palette tables": [(o, o + 35) for o in AREA_PALETTES] + [(o, o + 7) for o in BG0_VARIANTS] + [(BOWSER_PALETTE, BOWSER_PALETTE + 7),
            (PLAYER_COLORS, PLAYER_COLORS + 12), (BACKGROUND_COLORS, BACKGROUND_COLORS + 8), (PALETTE3_DATA, PALETTE3_DATA + 16), (COLOR_ROTATE, COLOR_ROTATE + 6)],
        "PRG: metatile graphics table": span(METATILE_PATCH) + [(CASTLE_METATILES, CASTLE_METATILES + 28)],
        "PRG: rope tile operands": span(ROPE_OPERANDS),
        "PRG: sprite palette, tile and position tables and operands": span(SPRITE_PATCHES) + [(FIREBAR_CALL[0], FIREBAR_CALL[0] + 3)],
        "PRG: gameplay sites that queue a sound": [(o, o + 4) for o in (0x3510, 0x5DE3, 0x5F13, 0x52D1)],
        "PRG: sound engine": [(_cpu(0xF2D0), HDR + PRG), (0x10F7, 0x10FD)],
        "CHR: tiles": [(HDR + PRG, HDR + PRG + CHR)],
    }
    count = {g: 0 for g in groups}; count["elsewhere"] = 0
    for i in range(len(orig)):
        if orig[i] != out[i]:
            g = next((g for g, spans in groups.items() if any(a <= i < b for a, b in spans)), "elsewhere"); count[g] += 1
    return count

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, dst = args
    rom = open(src, "rb").read()
    if hashlib.md5(rom).hexdigest() != ORIG_MD5:
        print("warning: input is not the original SMB ROM used by mario.stimuli", file=sys.stderr)
    out = build(rom, patch_pipes="--no-pipes" not in sys.argv, patch_palette="--no-palette" not in sys.argv,
                hitbox="--no-hitbox" not in sys.argv, marks="--no-marks" not in sys.argv, sound="--no-sound" not in sys.argv)
    open(dst, "wb").write(out)
    print(f"wrote {dst}  md5={hashlib.md5(out).hexdigest()}  rom.sha={hashlib.sha1(out[HDR:]).hexdigest()}")
    if "--summary" in sys.argv:
        for group, n in summary(rom, out).items(): print(f"  {n:5d} bytes changed  {group}")
