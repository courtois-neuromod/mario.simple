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

      backdrop   sky blue    everything non-interactive
      terrain    brown       ground, stairs, hard blocks, pipes, tree/mushroom
                             ledges, cloud terrain, cannons, bridges, used
                             blocks, moving platforms, springboards, vines
      brick      grey        breakable bricks
      ?-block    orange      question blocks (and the sprite of a bumped block)
      coin       yellow      coins in the level, coins popping out of blocks,
                             floating score numbers
      item       green       super mushroom
      1-up       dark green  1-up mushroom
      star       cyan        starman
      enemy      red         every enemy and enemy projectile
      Mario      white       the player (flashes white/green/orange when
                             invincible)
      fire Mario pale pink   Mario after a fire flower, his fireballs, and
                             the fire flower itself
      goal       purple      flagpole, ball and flag, axe, flagpole score

* A few *shapes* carry state that colour cannot (see the sets after HITBOX):
      Mario has a 2x2 "eye" hole on the side he faces;
      Koopa/Buzzy shells and dying Mario are hollow (2-px ring);
      Spiny, Spiny eggs and Piranha Plants (cannot be stomped) have a
      toothed top edge;
      a Paratroopa carries a 8x2 wing bar just above its box;
      a squished Goomba is a 16x4 bar, the springboard is striped.

How the ROM is changed
----------------------
* CHR-ROM (tile graphics) is rewritten from the tables below.
* PRG-ROM: only *presentation data* is patched, never code paths or level
  data:
    - the 4 area palette sets, the day/night snow and mushroom palette
      variants, the Bowser palette, the player palette rows, the
      backdrop-colour table, and the palette-3 rotation tables the game uses
      to make ?-blocks and coins flash (all are copied verbatim into the PPU
      write buffer);
    - 4 bytes of the metatile graphics lookup table so pipe shafts stop
      sharing tile $26 with the (transparent) hills, and 28 bytes of it so the
      end-of-level castle (decoration) is drawn with blank tiles instead of
      brick tiles;
    - 2 bytes of the enemy graphics table (Bloober frame 2) and the 4-byte
      power-up attribute table;
    - 7 immediate operands that choose the sprite palette of fireballs, coins
      popping out of blocks, bumped blocks, vines, floating score numbers,
      and that stop the fire flower / star palette cycling.
  These bytes only feed the PPU write buffer ($0300-$03FF) and the sprite
  buffer ($0200-$02FF), which game logic never reads.  RAM outside those two
  buffers, .bk2 replays and savestates therefore stay identical to the
  original ROM (verified on participant replays, see verify_replays.py).

Usage: simplify_rom.py ORIGINAL.nes OUTPUT.nes [--no-hitbox] [--no-marks] [--no-pipes] [--no-palette]
  --no-hitbox : draw every sprite tile as a full 8x8 square (v5 look)
  --no-marks  : no eye / hollow / teeth / wing / stripe shapes
"""
import sys, hashlib

# ---------------------------------------------------------------- colours --
# NES master-palette indices.  Change these to retune the look.
C = dict(
    backdrop=0x22, terrain=0x17, brick=0x10, qblock=0x27, coin=0x28,
    item=0x2A, oneup=0x1A, star=0x2C, enemy=0x16, mario=0x30, mario_fire=0x36,
    goal=0x24, text=0x30,
)

# Each palette group holds 3 usable colours (index 1..3).  The tile tables
# below choose an index; these rows choose what colour each index means.
BG_PAL = [
    [C['backdrop'], C['item'],   C['terrain'], C['goal']],   # BG0: pipes, ledges, flagpole
    [C['backdrop'], C['brick'],  C['terrain'], C['goal']],   # BG1: ground, bricks, castle, cannons
    [C['backdrop'], C['text'],   C['terrain'], C['goal']],   # BG2: HUD text, cloud terrain
    [C['backdrop'], C['qblock'], C['terrain'], C['coin']],   # BG3: ?-blocks, used blocks, coins
]
SPR_PAL = [
    [C['backdrop'], C['mario'],  C['star'],    C['mario_fire']],  # SPR0: Mario, star, fire flower, fireballs (overridden by PLAYER_PAL)
    [C['backdrop'], C['oneup'],  C['enemy'],   C['goal']],   # SPR1: koopas, hammer bros, piranha, lakitu, flag, 1-up, flagpole score
    [C['backdrop'], C['item'],   C['enemy'],   C['terrain']],# SPR2: spiny, cheeps, red koopas, mushroom, platforms, vine, bumped brick
    [C['backdrop'], C['qblock'], C['enemy'],   C['coin']],   # SPR3: goomba, buzzy, bullet bill, hammers, bumped ?-block, coins, score numbers
]
PLAYER_PAL = [                      # rows used by the game: Mario / Luigi / fire Mario
    [C['backdrop'], C['mario'],      C['star'], C['mario_fire']],
    [C['backdrop'], C['mario'],      C['star'], C['mario_fire']],
    [C['backdrop'], C['mario_fire'], C['star'], C['mario_fire']],
]
# Star power makes the game cycle Mario's sprite through the 4 sprite palettes
# (it rotates the attribute bits, not the colours).  Mario's tiles use index 1
# so that this flashes white / green / green / orange, never enemy red.

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
_set(range(0xC6, 0xCE), 2)                         # bullet bill cannon     (terrain)
_set([0x2A, 0x40], 2)                              # cannon base            (terrain)
_set([0xC1], 2)                                    # bridge                 (terrain)
_set([0x52], 2)                                    # green ledge stump      (terrain)
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
_set([0x7B, 0x7C, 0x7D, 0x7E], 3)                  # axe                    (goal)
_set([0x77, 0x79], 2)                              # Bowser bridge          (terrain)

# --------------------------------------------------- sprite tiles ($0000) --
# Ownership measured from 66 participant replays (OAM buffer vs object slots).
SPR = {i: 2 for i in range(0x00, 0xF6)}            # default: enemy colour index
def _spr(ids, v):
    for i in ids: SPR[i] = v
_spr(list(range(0x00, 0x50)) + list(range(0x58, 0x60)) + list(range(0x90, 0x94)) + [0x9E, 0x9F], 1)  # Mario (SPR0 idx1)
_spr(list(range(0x76, 0x7A)), 1)                   # mushroom (SPR2 idx1 = item) / 1-up (SPR1 idx1 = 1-up colour)
_spr([0x8D, 0xE4], 2)                              # star (moved to SPR0 idx2 = star colour)
_spr([0xD6, 0xD9], 3)                              # fire flower (moved to SPR0 idx3 = fire-Mario colour)
_spr([0xE0, 0xE1], 3)                              # vine (moved to SPR2 idx3 = terrain)
_spr(list(range(0x60, 0x64)), 3)                   # coin popping out of a block (moved to SPR3 idx3 = coin)
_spr([0x64, 0x65], 3)                              # Mario's fireball (moved to SPR0 idx3 = fire-Mario colour)
_spr([0x87], 1)                                    # bumped ?-block sprite (SPR3 idx1 = ?-block)
_spr([0x85, 0x86], 3)                              # bumped brick sprite (moved to SPR2 idx3 = terrain)
_spr([0x84], 0)                                    # brick debris: transparent
_spr([0x5B, 0x75] + list(range(0xF0, 0xF4)), 3)    # moving platforms, springboard (SPR2 idx3 = terrain)
_spr([0x50, 0x7E, 0x7F], 3)                        # flagpole flag (SPR1 idx3 = goal)
_spr([0x66, 0x67, 0x68, 0x54, 0x55, 0x56, 0x57], 0)  # fireworks, castle flag: transparent
_spr(list(range(0xF6, 0xFC)) + [0xFD, 0xFE], 'text3')  # floating score digits and "1UP": glyph kept, index 3 (moved to SPR3 = coin colour)

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
# Spiny and Spiny egg (10x6)
    0x8E:(-3,-4,10,6), 0x8F:(-3,2,10,6), 0x94:(-3,-4,10,6), 0x95:(-3,2,10,6), 0x96:(-3,-6,10,6), 0x97:(5,-6,10,6),
    0x98:(-3,2,10,6), 0x99:(5,2,10,6), 0x9A:(-3,-6,10,6), 0x9B:(5,-6,10,6), 0x9C:(-3,2,10,6), 0x9D:(5,2,10,6),
# Cheep-cheep (10x6)
    0xB2:(-3,-6,10,6), 0xB3:(5,-6,10,6), 0xB4:(-3,2,10,6), 0xB5:(5,2,10,6), 0xB6:(-3,-6,10,6), 0xB7:(-3,2,10,6),
# Bullet Bill (cannon variant; frenzy variant is drawn 1 px lower)
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
# hammers (8x8 box, tile offset 4px)
    0x80:(4,0,8,8), 0x81:(-4,0,8,8), 0x82:(0,4,8,8), 0x83:(0,-4,8,8),
# mushroom / 1-up (12x12; rows -1/7)
    0x76:(-2,-1,12,12), 0x77:(6,-1,12,12), 0x78:(-2,7,12,12), 0x79:(6,7,12,12),
# fire flower
    0xD6:(-2,-1,12,12), 0xD9:(-2,7,12,12),
# star
    0x8D:(-2,-1,12,12), 0xE4:(-2,7,12,12),
# not seen in the dataset, placed from the graphics tables (swimming Mario, Bloober)
    0x2E:(-2,8,12,24), 0x2F:(6,8,12,24), 0x30:(6,8,12,24), 0x31:(-2,16,12,24),
    0x46:(-3,4,10,12), 0x47:(5,4,10,12), 0x48:(-3,4,10,12), 0x49:(5,4,10,12),
    0xDC:(-3,-6,10,6), 0xDD:(5,-6,10,6), 0xDE:(-3,2,10,6), 0xDF:(5,2,10,6),
# squished Goomba: no collision; drawn as a 16x4 bar on the ground
    0xEF:(0,-4,8,8),
}
MARIO_TILES = {t for t in HITBOX if t < 0x50 or 0x58 <= t < 0x60 or 0x90 <= t < 0x94 or t in (0x9E, 0x9F)}
HOLLOW   = {0x6D, 0x6E, 0x6F, 0xF4, 0xF5, 0x9E, 0x9F}          # Koopa/Buzzy shells, dying Mario: 2-px ring
SERRATED = set(range(0x96, 0x9E)) | {0x8E, 0x8F, 0x94, 0x95, 0xE5, 0xE6, 0xEB, 0xEC, 0xED, 0xEE}  # Spiny, egg, Piranha: toothed top edge
WINGS    = {0x69, 0x6B}                                        # Paratroopa wing tiles (row above the box): 8x2 bar
STRIPED  = set(range(0xF0, 0xF4))                              # springboard: 2-px horizontal stripes

# ------------------------------------------------------ PRG data patches --
HDR, PRG, CHR = 16, 0x8000, 0x2000
ORIG_MD5 = "811b027eaf99c2def7b933c5208636de"
PIPE_PATCH = {  # metatile graphics table (file offset: expected -> new)
    0x0B20 + 4*0x15: (bytes([0x26,0x26,0x6A,0x6A]), bytes([0x69,0x69,0x6A,0x6A])),  # vertical pipe shaft, right half
    0x0B20 + 4*0x20: (bytes([0x26,0x93,0x26,0x93]), bytes([0x93,0x93,0x93,0x93])),  # sideways pipe shaft, bottom half
}
CASTLE_METATILES = 0x0BBC + 4*0x05                  # metatile graphics table, palette-1 entries #05-#0B: the end-of-level castle
SPRITE_PATCHES = {  # file offset: (expected bytes, new bytes) - immediate operands that pick an object's sprite palette
    0x6D0C: (bytes([0xA9, 0x02, 0x90, 0x02, 0x09, 0xC0]), bytes([0xA9, 0x00, 0x90, 0x02, 0x09, 0xC0])),  # fireball: palette 2 -> 0
    0x66C1: (bytes([0xA9, 0x02, 0x99, 0x02, 0x02]),       bytes([0xA9, 0x03, 0x99, 0x02, 0x02])),        # coin from block: palette 2 -> 3
    0x6BEB: (bytes([0xA9, 0x03, 0x85, 0x04, 0x4A]),       bytes([0xA9, 0x02, 0x85, 0x04, 0x4A])),        # bumped brick: palette 3 -> 2
    0x6C2E: (bytes([0xF0, 0x01, 0x4A, 0xA6, 0x08]),       bytes([0xF0, 0x01, 0xEA, 0xA6, 0x08])),        # bumped ?-block: always palette 3 (was 1 outside ground areas)
    0x66DE: (bytes([0x02, 0x01, 0x02, 0x01]),             bytes([0x02, 0x00, 0x00, 0x01])),              # PowerUpAttributes: mushroom 2, flower 1->0, star 2->0, 1-up 1
    0x6724: (bytes([0x4A, 0x29, 0x03, 0x0D, 0xCA, 0x03]), bytes([0x4A, 0x29, 0x00, 0x0D, 0xCA, 0x03])),  # flower/star top row: stop cycling the 4 palettes, use palette 0
    0x6471: (bytes([0xA9, 0x21, 0x99, 0x02, 0x02]),       bytes([0xA9, 0x22, 0x99, 0x02, 0x02])),        # vine: palette 1 -> 2 (behind-background bit kept)
    0x055B: (bytes([0xA9, 0x02, 0x99, 0x02, 0x02, 0x99, 0x06, 0x02]), bytes([0xA9, 0x03, 0x99, 0x02, 0x02, 0x99, 0x06, 0x02])),  # floating score numbers: palette 2 -> 3
    0x6790: (bytes([0xDC, 0xDC, 0xDD, 0xDD, 0xDE, 0xDE]), bytes([0xFC, 0xFC, 0xDD, 0xDD, 0xDE, 0xDE])),  # enemy graphics table, Bloober frame 2: blank top row (tile $DC is a body tile in frame 1)
}
AREA_PALETTES = [0x0CB4, 0x0CD8, 0x0CFC, 0x0D20]   # water, ground, underground, castle: "3F 00 20" + 32 bytes
PLAYER_COLORS = 0x05E7                              # 3 rows x 4
BACKGROUND_COLORS = 0x05DF                          # 8 backdrop colours by area type / bg-colour control
BG0_VARIANTS = [0x0D44, 0x0D4C, 0x0D54]             # day snow, night snow, mushroom: "3F 00 04" + 4 bytes (BG palette 0)
BOWSER_PALETTE = 0x0D5C                             # "3F 14 04" + 4 bytes (sprite palette 1)
PALETTE3_DATA = 0x09E1                              # 4 rows (water/ground/underground/castle) x 4: BG palette 3 rewritten every 8 frames
COLOR_ROTATE = 0x09D3                               # 6 colours the game cycles into BG palette 3 index 1 (the ?-block/coin flash)

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
            bx, by = dx + c, dy + r
            if not (0 <= bx < w and 0 <= by < h): continue
            v = idx
            if marks:
                if t in HOLLOW and 2 <= bx < w-2 and 2 <= by < h-2: v = 0
                if t in SERRATED and by < 2 and (bx // 2) % 2: v = 0
                if t in MARIO_TILES and t not in HOLLOW and w-4 <= bx < w-2 and 2 <= by < 4: v = 0
            px[r][c] = v
    if marks and t in WINGS:
        for r in (6, 7): px[r] = [idx]*8
    return pack(px)

def _expect(rom, off, header):
    assert bytes(rom[off:off+len(header)]) == bytes(header), f"unexpected bytes at {off:#x}"

def build(rom: bytes, patch_pipes=True, patch_palette=True, hitbox=True, marks=True) -> bytes:
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
        for off, (old, new) in PIPE_PATCH.items():
            _expect(rom, off, old); rom[off:off+4] = new
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
    return bytes(rom)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, dst = args
    rom = open(src, "rb").read()
    if hashlib.md5(rom).hexdigest() != ORIG_MD5:
        print("warning: input is not the original SMB ROM used by mario.stimuli", file=sys.stderr)
    out = build(rom, patch_pipes="--no-pipes" not in sys.argv, patch_palette="--no-palette" not in sys.argv,
                hitbox="--no-hitbox" not in sys.argv, marks="--no-marks" not in sys.argv)
    open(dst, "wb").write(out)
    print(f"wrote {dst}  md5={hashlib.md5(out).hexdigest()}  rom.sha={hashlib.sha1(out[HDR:]).hexdigest()}")
