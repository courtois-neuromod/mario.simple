#!/usr/bin/env python3
"""Build the "simplified" Super Mario Bros ROM from the original ROM.

Design
------
* Anything the player cannot interact with (clouds, bushes, hills, trees,
  fences, castle decoration, water surface, sea plants, ropes, fireworks,
  brick debris...) becomes transparent, i.e. shows the uniform backdrop.
* Everything the player interacts with becomes a flat square, and colour is a
  semantic category, identical in every level:

      backdrop   sky blue   everything non-interactive
      terrain    brown      ground, stairs, hard blocks, pipes, tree/mushroom
                            ledges, cloud terrain, cannons, bridges, used
                            blocks, moving platforms, springboards, vines
      brick      grey       breakable bricks (and the castle wall, which
                            shares their tile)
      ?-block    orange     question blocks (and the sprite of a bumped block)
      coin       yellow     coins in the level
      item       green      mushroom, 1-up, fire flower, star, sprite coins
                            popping out of blocks, and Mario's fireballs
      enemy      red        every enemy and enemy projectile
      Mario      white      the player (flashes white/green/orange when
                            invincible; fire Mario is also white)
      goal       purple     flagpole, ball and flag, axe

How the ROM is changed
----------------------
* CHR-ROM (tile graphics) is rewritten from the tables below.
* PRG-ROM: only *presentation data* is patched, never code or level data:
    - the 4 area palette sets, the day/night snow and mushroom palette
      variants, the Bowser palette, the player palette rows, the
      backdrop-colour table, and the palette-3 rotation tables the game uses
      to make ?-blocks and coins flash (all are copied verbatim into the PPU
      write buffer);
    - 4 bytes of the metatile graphics lookup table so pipe shafts stop
      sharing tile $26 with the (transparent) hills.
  These bytes only feed the PPU write buffer ($0300-$03FF).  Game logic, RAM
  outside that buffer, .bk2 replays and savestates therefore stay identical to
  the original ROM (verified on participant replays).

Usage: simplify_rom.py ORIGINAL.nes OUTPUT.nes [--no-pipes] [--no-palette]
"""
import sys, hashlib

# ---------------------------------------------------------------- colours --
# NES master-palette indices.  Change these to retune the look.
C = dict(
    backdrop=0x22, terrain=0x17, brick=0x10, qblock=0x27, coin=0x28,
    item=0x2A, enemy=0x16, mario=0x30, mario_fire=0x30, goal=0x24, text=0x30,
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
    [C['backdrop'], C['mario'],  C['item'],    C['goal']],   # SPR0: Mario (overridden by PLAYER_PAL)
    [C['backdrop'], C['item'],   C['enemy'],   C['goal']],   # SPR1: koopas, hammer bros, piranha, flag, vine, 1-up
    [C['backdrop'], C['item'],   C['enemy'],   C['terrain']],# SPR2: spiny, cheeps, mushroom, star, coins, platforms
    [C['backdrop'], C['qblock'], C['enemy'],   C['goal']],   # SPR3: goomba, buzzy, bullet bill, hammers, bumped block
]
PLAYER_PAL = [                      # rows used by the game: Mario / Luigi / fire Mario
    [C['backdrop'], C['mario'],      C['item'], C['goal']],
    [C['backdrop'], C['mario'],      C['item'], C['goal']],
    [C['backdrop'], C['mario_fire'], C['item'], C['goal']],
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
_spr(list(range(0x76, 0x7A)) + [0x8D, 0xE4, 0xD8, 0xD9, 0xE0, 0xE1], 1)                           # mushroom/1-up, star, flower, vine (item)
_spr([0xD6, 0xD7], 2)                              # fire flower tiles drawn with Mario's palette (SPR0 idx2 = item)
_spr(list(range(0x60, 0x64)) + [0xF7], 1)          # coin popping out of a block (item)
_spr([0x64, 0x65], 1)                              # Mario's fireball (item colour, see docstring)
_spr(list(range(0x84, 0x88)), 1)                   # bumped block sprite (SPR3 idx1 = ?-block)
_spr([0x5B, 0x75] + list(range(0xF0, 0xF4)), 3)    # moving platforms, springboard (SPR2 idx3 = terrain)
_spr([0x50, 0x7E, 0x7F], 3)                        # flagpole flag (SPR1 idx3 = goal)
_spr([0x66, 0x67, 0x68, 0x54, 0x55, 0x56, 0x57], 0)  # fireworks, castle flag: transparent
# $F6-$FF: floating score digits and "1UP", kept as drawn

# ------------------------------------------------------ PRG data patches --
HDR, PRG, CHR = 16, 0x8000, 0x2000
ORIG_MD5 = "811b027eaf99c2def7b933c5208636de"
PIPE_PATCH = {  # metatile graphics table (file offset: expected -> new)
    0x0B20 + 4*0x15: (bytes([0x26,0x26,0x6A,0x6A]), bytes([0x69,0x69,0x6A,0x6A])),  # vertical pipe shaft, right half
    0x0B20 + 4*0x20: (bytes([0x26,0x93,0x26,0x93]), bytes([0x93,0x93,0x93,0x93])),  # sideways pipe shaft, bottom half
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

def _expect(rom, off, header):
    assert bytes(rom[off:off+len(header)]) == bytes(header), f"unexpected bytes at {off:#x}"

def build(rom: bytes, patch_pipes=True, patch_palette=True) -> bytes:
    assert len(rom) == HDR + PRG + CHR, "unexpected ROM size"
    rom = bytearray(rom)
    chr0 = HDR + PRG
    for t, v in SPR.items():
        rom[chr0 + 16*t: chr0 + 16*t + 16] = solid(v) if v else bytes(16)
    for t, v in BG.items():
        off = chr0 + 0x1000 + 16*t
        if v is None:       rom[off:off+16] = bytes(16)
        elif v == 'remap3': rom[off:off+16] = remap(rom[off:off+16], 3)
        else:               rom[off:off+16] = solid(v)
    if patch_pipes:
        for off, (old, new) in PIPE_PATCH.items():
            _expect(rom, off, old); rom[off:off+4] = new
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
    out = build(rom, patch_pipes="--no-pipes" not in sys.argv, patch_palette="--no-palette" not in sys.argv)
    open(dst, "wb").write(out)
    print(f"wrote {dst}  md5={hashlib.md5(out).hexdigest()}  rom.sha={hashlib.sha1(out[HDR:]).hexdigest()}")
