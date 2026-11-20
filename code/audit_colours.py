#!/usr/bin/env python3
"""Check what a simplified ROM draws against the legend of simplify_rom.py.

verify_replays.py shows that the game logic is untouched; it says nothing
about the picture.  This tool replays recordings on the simplified ROM and,
on every Nth frame, checks the picture object by object, using the game's own
memory to know what each thing on screen is:

  sprites     every sprite of the sprite buffer ($0200-$02FF) is attributed
              to the object that drew it (player, enemy slot, power-up,
              fireball, bumped block, coin, hammer...) through the game's
              sprite-offset tables ($06E4-$06FB), and the colours of its
              opaque pixels (tile pixels x the PPU palette of the savestate)
              must be those of that object's category;
  background  every visible 16x16 cell of the name table must be drawn in the
              category colour of the block the game holds at that place in
              its block buffer ($0500-$069F), and every cell the game treats
              as empty must be drawn empty (or be text);
  boxes       the rectangle drawn for each object that has a live collision
              box ($04AC-$04DB) is compared with that box, edge by edge, and
              the side of the hole in Mario's rectangle with the side he
              faces;
  colours     every pixel of the rendered frame must have a legend colour.

It also lists, per level, which blocks and objects were seen, so that the
coverage of a set of recordings is known.  Expectations (EXPECT_BLOCK and
expected_sprite below) are written from the game's logic, independently of the
tile tables of simplify_rom.py, which is the point.

Usage:
    audit_colours.py [--jobs N] [--every N] [--json OUT] MOD_INTEGRATION_DIR REPLAY.bk2 [...]

Recordings made on the original ROM carry its palette in their initial state;
the audit rewrites it first, as fix_state.py does.  Exit status 1 if anything
unexpected was drawn.
"""
import os, sys, json, zipfile, argparse, importlib.util
from collections import Counter, defaultdict
import numpy as np
try:
    import stable_retro as retro
except ImportError:
    import retro

HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sr, fs = _load("simplify_rom"), _load("fix_state")

IDLE = (0x8057, 0xFF)                                   # see verify_replays.py: the frame's logic has run
PERSIST = 8                                             # frames a background mismatch must last to count (see cells below)
NAME = {v: k for k, v in reversed(list(sr.C.items()))}  # NES colour -> category ('terrain' wins over 'text')
LEGEND = set(sr.C.values())

# ------------------------------------------------------------ expectations --
# Background: category of every metatile (16x16 block), from what the game does with it.
# None = decoration or empty (nothing may be drawn).  Metatiles the game does not keep in its
# block buffer (decoration) are drawn from the name table only; see cells().
T, B, Q, K, G, L = "terrain", "brick", "qblock", "coin", "goal", "cannon"
EXPECT_BLOCK = {}
def _blk(ids, cat):
    for i in ids: EXPECT_BLOCK[i] = cat
_blk(range(0x00, 0x10), None)              # blank, bushes, hills, bridge guard rail, chain, trees
_blk(range(0x10, 0x22), T)                 # pipes, tree-top and mushroom ledges, sideways pipes
_blk([0x22, 0x23, 0x26], None)             # sea plant, blank left by a bumped block, blank behind a vine
_blk([0x24, 0x25], G)                      # flagpole ball and shaft
_blk(range(0x40, 0x51), None)              # ropes and pulleys, castle, ledge stump, fence, trunk, mushroom stump
_blk(range(0x51, 0x5F), B)                 # bricks, whatever they hide
_blk([0x54], T)                            # ground
_blk([0x5F, 0x60], None)                   # hidden blocks: invisible until hit
_blk([0x61, 0x62, 0x63], T)                # hard block, white wall, bridge
_blk([0x64], L)                            # Bullet Bill cannon barrel
_blk([0x65, 0x66], T)                      # cannon pedestal and column
_blk([0x67], None)                         # upper half of a springboard (the springboard itself is a sprite)
_blk([0x68, 0x69, 0x6A, 0x6B, 0x6C], T)    # springboard base, underwater rock, water pipes
_blk([0x6D], L)                            # leftover flag ball of BG palette 1: no area uses it
_blk(range(0x80, 0x88), None)              # clouds, water and lava
_blk([0x88, 0x89], T)                      # cloud terrain, Bowser's bridge
_blk([0xC0, 0xC1], Q)                      # ?-blocks
_blk([0xC2, 0xC3], K)                      # coins
_blk([0xC4], T)                            # used block
_blk([0xC5], K)                            # axe: BG palette 3 has no goal colour, see simplify_rom.py

SCORE_TILES = {0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0x50, 0xFD, 0xFE}
ENEMY = {0x00: "Green Koopa", 0x01: "Red Koopa", 0x02: "Buzzy Beetle", 0x03: "Red Koopa", 0x04: "Green Koopa", 0x05: "Hammer Bro",
         0x06: "Goomba", 0x07: "Bloober", 0x08: "Bullet Bill (frenzy)", 0x09: "Green Paratroopa", 0x0A: "Grey Cheep-cheep",
         0x0B: "Red Cheep-cheep", 0x0C: "Podoboo", 0x0D: "Piranha Plant", 0x0E: "Green Paratroopa (jumping)",
         0x0F: "Red Paratroopa", 0x10: "Green Paratroopa (flying)", 0x11: "Lakitu", 0x12: "Spiny", 0x14: "Flying Cheep-cheep",
         0x15: "Bowser's flame", 0x16: "Fireworks", 0x1B: "Fire bar", 0x1C: "Fire bar", 0x1D: "Fire bar", 0x1E: "Fire bar",
         0x1F: "Long fire bar", 0x20: "Fire bar", 0x21: "Fire bar", 0x22: "Fire bar", 0x24: "Balance lift", 0x25: "Up-down lift",
         0x26: "Lift going up", 0x27: "Lift going down", 0x28: "Left-right lift", 0x29: "Dropping lift", 0x2A: "Lift going right",
         0x2B: "Small lift going up", 0x2C: "Small lift going down", 0x2D: "Bowser", 0x2E: "Power-up", 0x2F: "Vine",
         0x30: "Flagpole flag", 0x31: "Castle flag", 0x32: "Springboard", 0x33: "Bullet Bill (cannon)", 0x34: "Warp zone",
         0x35: "Retainer"}
POWERUP = {0: ("Super mushroom", "item"), 1: ("Fire flower", "mario_fire"), 2: ("Star", "star"), 3: ("1-up mushroom", "oneup")}

def expected_sprite(kind, slot, tile, pal, r, star=False):
    """(label, set of allowed categories) for one sprite, from the game's memory r (star: star power was on at the previous audited frame)."""
    if tile in SCORE_TILES and kind in ("ENEMY", "BLOCK", "FREED", "UNKNOWN"):
        return "Score number", {"coin"} if pal == 3 else {"goal"}          # the flagpole score is drawn with the flag's palette
    if kind == "MARIO":
        if pal == 0: return "Mario", {"mario", "mario_fire"}
        cycling = r[0x79F] or star or r[0x0E] == 0x0C            # star power (and the frame it ends), or the moment he picks up a fire flower: his palette is rotated
        return "Mario (star power or fire-flower pickup)", {"oneup", "item", "brick"} if cycling else set()
    if kind == "ENEMY":
        e = int(r[0x16 + slot]); name = f"${e:02X} {ENEMY.get(e, '?')}"
        if e == 0x2E:
            n, c = POWERUP.get(int(r[0x39]), ("Power-up ?", "?")); return n, {c}
        if e in (0x2F, 0x32): return name, {"qblock"}
        if e == 0x30: return name, {"goal"}
        if e in (0x16, 0x31, 0x34): return name, set()
        if 0x24 <= e <= 0x2C: return name, {"terrain"}
        return name, {"enemy"}
    if kind == "BLOCK":
        if tile == 0x87: return "Bumped block (becomes a used block)", {"terrain"}
        if tile in (0x85, 0x86): return "Bumped brick", {"brick"}
        return "Brick debris", set()
    if kind == "FIREBALL": return "Mario's fireball", {"mario_fire"}
    if kind == "MISC": return ("Hammer", {"enemy"}) if r[0x2A + slot] & 0x80 else ("Coin from a block", {"coin"})
    if kind == "BUBBLE": return "Air bubble", set()
    if kind == "FREED": return "Object whose slot has just been freed (last frame)", set(NAME.values())   # its identity is gone: any legend colour
    if r[0x772] != 3 and tile != 0xFF: return "Mario icon of the WORLD x-y screen", {"mario", "mario_fire"}
    if tile == 0xFF: return "Sprite 0 (bottom of the HUD coin icon)", {"coin"}
    return "Unattributed sprite", set()

GLYPHS = set(range(0x00, 0x24)) | {0x28, 0x29, 0x2B, 0xAF, 0xCF}   # digits, letters, - x ! . (c)

# ------------------------------------------------------------------- ROM ----
class Rom:
    def __init__(self, path):
        rom = open(path, "rb").read(); prg, chr_ = rom[16:16 + 0x8000], rom[16 + 0x8000:]
        bits = np.unpackbits(np.frombuffer(chr_, np.uint8).reshape(512, 2, 8, 1), axis=3)       # [tile, bit plane, row, column]
        self.tiles = bits[:, 0] | (bits[:, 1] << 1)                         # [512, 8, 8] palette index per pixel; 0-255 sprites, 256-511 background
        self.idx = [frozenset(int(v) for v in np.unique(t) if v) for t in self.tiles]
        lo, hi = prg[0x0B08:0x0B0C], prg[0x0B0C:0x0B10]                     # MetatileGraphics_Low / _High
        ptr = [l | h << 8 for l, h in zip(lo, hi)]; n = [(ptr[1] - ptr[0]) // 4, (ptr[2] - ptr[1]) // 4, (ptr[3] - ptr[2]) // 4, 6]
        self.metatile = {(p << 6) | k: tuple(prg[ptr[p] - 0x8000 + 4 * k:ptr[p] - 0x8000 + 4 * k + 4]) for p in range(4) for k in range(n[p])}
        self.bbox, self.pts = {}, {}                                        # (tile, hflip, vflip) -> box (x0, y0, x1, y1) and coordinates of the opaque pixels
        for t in range(256):
            for hf in (0, 1):
                for vf in (0, 1):
                    m = self.tiles[t] != 0
                    if hf: m = m[:, ::-1]
                    if vf: m = m[::-1]
                    ys, xs = np.where(m); self.pts[(t, hf, vf)] = (ys, xs)
                    self.bbox[(t, hf, vf)] = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None
        self.bits = np.array([sum(1 << i for i in s) for s in self.idx[256:]], np.uint8)   # background tile -> bit i set if palette index i is used
        # name-table offsets of the four tiles and of the attribute byte of every 16x16 cell [page, row, column]
        page, row, col = np.meshgrid(np.arange(2), np.arange(13), np.arange(16), indexing="ij"); ty, tx = 4 + 2 * row, 2 * col
        self.nt = np.stack([page * 0x400 + (ty + dy) * 32 + tx + dx for dx, dy in ((0, 0), (0, 1), (1, 0), (1, 1))])
        self.at = page * 0x400 + 0x3C0 + (ty // 4) * 8 + tx // 4; self.shift = ((ty & 2) << 1) | (tx & 2)
        self.want = np.full(256, 0xFE, np.uint8)                            # expected NES colour per held metatile: $FF nothing drawn, $FE unknown metatile
        for mt, cat in EXPECT_BLOCK.items(): self.want[mt] = 0xFF if cat is None else sr.C[cat]
    def block_colours(self, mt, palette):
        """Categories a metatile is drawn with, given the 16 BG palette bytes."""
        out = set()
        for t in self.metatile[mt]: out |= {NAME.get(palette[4 * (mt >> 6) + i], f"${palette[4 * (mt >> 6) + i]:02X}") for i in self.idx[256 + t]}
        return out

def static_blocks(rom):
    """Every metatile of the ROM against EXPECT_BLOCK, with the legend palette.  Returns the list of mismatches."""
    pal = sum(sr.BG_PAL, []); bad = []
    for mt in sorted(rom.metatile):
        got = rom.block_colours(mt, pal); want = EXPECT_BLOCK.get(mt, "?")
        if got != (set() if want is None else {want}): bad.append((f"${mt:02X}", sorted(got), want))
    return bad

# ----------------------------------------------------------------- frames ---
class State:
    """Chunks of an fceumm savestate."""
    def __init__(self, raw): self.raw = raw; self.at = {}
    def get(self, name, size):
        if name not in self.at:
            i = self.raw.find(name + size.to_bytes(4, "little")); assert i >= 0, name; self.at[name] = i + 8
        return self.raw[self.at[name]:self.at[name] + size]

def owners(r):
    """OAM entry (0-63) -> (kind, slot), from the sprite-offset tables of the frame."""
    own = {}
    def tag(off, n, v):
        for j in range(n): own.setdefault(((int(off) + 4 * j) & 0xFF) >> 2, v)
    tag(r[0x6E4], 8, ("MARIO", 0))
    for s in range(9):                                                       # only objects that exist: every slot has an offset.  Hammers and coins
        if r[0x2A + s]: tag(r[0x6F3 + s], 2, ("MISC", s))                    # first: their sprites lie inside the range of the last enemy slots,
    for s in range(6):                                                       # and they are drawn after the enemies
        if r[0x0F + s] or (s == 5 and r[0x23]): tag(r[0x6E5 + s], 6, ("ENEMY", s))
    for s in range(2):
        if r[0x24 + s]: tag(r[0x6F1 + s], 1, ("FIREBALL", s))
    if r[0x74E] == 0:                                                        # air bubbles exist in water areas only
        for s in range(3): tag(r[0x6EE + s], 1, ("BUBBLE", s))
    for s in range(2): tag(r[0x6EC + s], 4, ("BLOCK", s))
    for s in range(6): tag(r[0x6E5 + s], 6, ("FREED", s))                    # last: what a slot that has just been freed still draws
    return own

def live_box(kind, slot, r):
    """Index of the object's collision box if the game is using it, else None."""
    if kind == "MARIO": return 0
    if kind == "FIREBALL": return 7 + slot
    if kind == "MISC": return 9 + slot if r[0x2A + slot] & 0x80 else None                 # hammers only
    if kind == "ENEMY":
        e, st = int(r[0x16 + slot]), int(r[0x1E + slot])
        if st & 0x20 or (e == 0x06 and (st & 7) >= 2): return None                        # defeated, or squished Goomba
        if e >= 0x2F and e != 0x33: return None                                           # vine, flags, springboard...: no sprite box
        return 1 + slot
    return None

def audit(game, bk2, rom, every=2):
    env = retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY, use_restricted_actions=retro.Actions.ALL)
    core = fs.fix(zipfile.ZipFile(bk2).read("Core.bin"))[0]; env.initial_state = core; env.reset()
    m = retro.Movie(bk2); m.step()
    rgb = palette_rgb(env, core); legend_rgb = {rgb[c] for c in LEGEND}; env.initial_state = core; env.reset()
    spr, spr_bad, box, eye = Counter(), Counter(), Counter(), Counter()
    cells, cells_bad, blocks, objects, colours_bad, text = Counter(), Counter(), defaultdict(Counter), defaultdict(Counter), Counter(), Counter()
    f = audited = 0; streak = {}; star = False
    while m.step():
        obs, *_ = env.step([m.get_key(i, 0) for i in range(env.num_buttons)]); f += 1
        if f % every: continue
        st = State(env.em.get_state())
        if (int.from_bytes(st.get(b"PC\0\0", 2), "little"), st.get(b"S\0\0\0", 1)[0]) != IDLE: continue
        r = env.get_ram(); audited += 1
        pram = st.get(b"PRAM", 32)
        level = f"{int(r[0x75F]) + 1}-{int(r[0x75C]) + 1} " + ("water", "ground", "underground", "castle")[r[0x74E] & 3] + (", cloud bonus" if r[0x743] else "")
        if audited % 8 == 0:                                                 # ---- rendered colours, on every kind of screen
            flat = obs.reshape(-1, 3).astype(np.uint32); u = np.unique(flat[:, 0] << 16 | flat[:, 1] << 8 | flat[:, 2])
            for v in u:
                if int(v) not in legend_rgb: colours_bad[(f"#{int(v):06X}", level)] += 1
        if r[0x770] != 1: continue                                           # OperMode: the objects are audited while a level is running or loading
        # ---- sprites
        own = owners(r); oam = r[0x200:0x300].reshape(64, 4); groups = defaultdict(list)
        for i in range(64):
            y, t, a, x = (int(v) for v in oam[i])
            if y >= 0xEF: continue
            kind, slot = own.get(i, ("UNKNOWN", 0)); label, allowed = expected_sprite(kind, slot, t, a & 3, r, star)
            got = frozenset(NAME.get(pram[16 + 4 * (a & 3) + k], f"${pram[16 + 4 * (a & 3) + k]:02X}") for k in rom.idx[t])
            key = (label, f"{t:02X}", a & 3, "+".join(sorted(got)) or "-")
            spr[key] += 1
            if not got <= allowed: spr_bad[key + ("+".join(sorted(allowed)) or "-", level)] += 1
            objects[level][label] += 1
            if t not in SCORE_TILES and t not in sr.WINGS: groups[(kind, slot)].append((x, y, t, a))   # the wing bar is a mark drawn outside the box on purpose
        star = bool(r[0x79F])
        # ---- collision boxes
        if r[0x0E] == 8:
            for (kind, slot), sprites in groups.items():
                k = live_box(kind, slot, r)
                if k is None: continue
                ulx, uly, lrx, lry = (int(v) for v in r[0x4AC + 4 * k:0x4B0 + 4 * k])
                if not (8 <= ulx < lrx <= 247 and 8 <= uly < lry <= 231): continue          # off-screen or wrapped box
                bb = [rom.bbox[(t, a >> 6 & 1, a >> 7 & 1)] for x, y, t, a in sprites]
                pts = [(x + b[0], y + b[1], x + b[2], y + b[3]) for (x, y, t, a), b in zip(sprites, bb) if b]
                label = expected_sprite(kind, slot, sprites[0][2], sprites[0][3] & 3, r)[0] if kind != "MARIO" else "Mario"
                label += f" {lrx - ulx}x{lry - uly}"
                if not pts: box[(label, "nothing drawn")] += 1; continue
                x0, y0, x1, y1 = min(p[0] for p in pts), min(p[1] for p in pts), max(p[2] for p in pts), max(p[3] for p in pts)
                box[(label, f"{x0 - ulx:+d},{y0 - uly:+d},{x1 - lrx:+d},{y1 - lry:+d}")] += 1
                if kind == "MARIO" and (x0, y0, x1, y1) == (ulx, uly, lrx, lry) and r[0x33] in (1, 2):
                    canvas = np.zeros((y1 - y0, x1 - x0), bool)
                    for x, y, t, a in sprites:
                        ys, xs = rom.pts[(t, a >> 6 & 1, a >> 7 & 1)]; yy, xx = ys + y - y0, xs + x - x0
                        keep = (yy >= 0) & (yy < canvas.shape[0]) & (xx >= 0) & (xx < canvas.shape[1]); canvas[yy[keep], xx[keep]] = True
                    hy, hx = np.where(~canvas)
                    side = "none" if not len(hx) else ("right" if hx.mean() > canvas.shape[1] / 2 else "left")
                    eye[("faces right" if r[0x33] == 1 else "faces left", f"hole {side}", len(hx))] += 1
        # ---- background cells (once the level runs: while it loads, the screen is drawn column by column)
        if r[0x772] == 3:
            nt = np.frombuffer(st.get(b"NTAR", 2048), np.uint8); left = int(r[0x71A]) * 256 + int(r[0x71C])
            ax = left + 16 * np.arange(17 if left & 15 else 16); page, col = (ax >> 8) & 1, (ax >> 4) & 15
            held = r[0x500 + page[None, :] * 0xD0 + np.arange(13)[:, None] * 16 + col[None, :]]      # [13 rows, visible columns]
            tiles = np.transpose(nt[rom.nt[:, page, :, col]], (1, 2, 0))                             # [4 tiles, 13, columns]
            attr = (nt[rom.at[page, :, col]].T >> rom.shift[page, :, col].T) & 3
            used = rom.bits[tiles[0]] | rom.bits[tiles[1]] | rom.bits[tiles[2]] | rom.bits[tiles[3]] # palette indices drawn in the cell
            bgpal = np.frombuffer(pram[:16], np.uint8); want = rom.want[held]; good = np.where(want == 0xFF, used == 0, used != 0)
            for i in (1, 2, 3): good &= ((used >> i) & 1 == 0) | (bgpal[4 * attr + i] == want)
            cells["ok"] += int(good.sum())
            for v in np.unique(held): blocks[level][f"${int(v):02X}"] += 1
            now = {}
            for row, c in zip(*np.where(~good)):
                h, tl, a = int(held[row, c]), [int(t) for t in tiles[:, row, c]], int(attr[row, c])
                got = "+".join(sorted({NAME.get(pram[4 * a + i], f"${pram[4 * a + i]:02X}") for i in (1, 2, 3) if used[row, c] >> i & 1})) or "-"
                drawn = [t for t in tl if rom.bits[t]]                                               # text written over an empty cell (or over transparent decoration)
                if h == 0 and drawn and all(t in GLYPHS for t in drawn): cells["text"] += 1; text[(got, a)] += 1; continue
                key = (f"${h:02X}", " ".join(f"{t:02X}" for t in tl), a, got, str(EXPECT_BLOCK.get(h, "?")), level)
                where = (int(ax[c]) >> 4, int(row), key); since, counted = streak.get(where, (f, False))
                if not counted and f - since >= PERSIST: cells_bad[key] += 1; counted = True         # the name table lags the block buffer by a few frames when a block
                elif not counted: cells["transient"] += 1                                            # changes: a mismatch counts once it has lasted PERSIST frames
                now[where] = (since, counted)
            streak = now
    env.close()
    j = lambda c: [[list(k) if isinstance(k, tuple) else k, n] for k, n in c.most_common()]
    return dict(replay=os.path.basename(bk2), frames=f, audited=audited, sprites=j(spr), sprites_bad=j(spr_bad), boxes=j(box), eye=j(eye),
                cells=dict(cells), cells_bad=j(cells_bad), colours_bad=j(colours_bad), text=j(text),
                blocks={k: dict(v) for k, v in blocks.items()}, objects={k: dict(v) for k, v in objects.items()})

_RGB = {}
def palette_rgb(env, state):
    """RGB the emulator shows for each of the 64 NES colours (measured: a frame drawn with a one-colour palette)."""
    if not _RGB:
        key = b"PRAM" + (32).to_bytes(4, "little"); i = state.find(key) + 8
        for c in range(64):
            env.initial_state = state[:i] + bytes([c] * 32) + state[i + 32:]; env.reset()
            obs, *_ = env.step([0] * env.num_buttons)
            flat = obs.reshape(-1, 3).astype(np.uint32); v, n = np.unique(flat[:, 0] << 16 | flat[:, 1] << 8 | flat[:, 2], return_counts=True)
            _RGB[c] = int(v[n.argmax()])
    return _RGB

# ------------------------------------------------------------------ report --
def merge(results):
    tot = dict(frames=0, audited=0, sprites=Counter(), sprites_bad=Counter(), boxes=Counter(), eye=Counter(), cells=Counter(),
               cells_bad=Counter(), colours_bad=Counter(), text=Counter(), blocks=defaultdict(Counter), objects=defaultdict(Counter), errors=[])
    for r in results:
        if "error" in r: tot["errors"].append((r["replay"], r["error"])); continue
        tot["frames"] += r["frames"]; tot["audited"] += r["audited"]; tot["cells"].update(r["cells"])
        for name in ("sprites", "sprites_bad", "boxes", "eye", "cells_bad", "colours_bad", "text"):
            for k, n in r[name]: tot[name][tuple(k) if isinstance(k, list) else k] += n
        for name in ("blocks", "objects"):
            for lvl, c in r[name].items(): tot[name][lvl].update(c)
    return tot

def report(tot, rom, out=sys.stdout):
    p = lambda *a: print(*a, file=out)
    p(f"frames replayed {tot['frames']}, audited {tot['audited']}")
    bad = static_blocks(rom)
    p(f"\n== background, static: {len(rom.metatile)} metatiles of the ROM against the expected category: {len(bad)} mismatch(es)")
    for mt, got, want in bad: p(f"   metatile {mt}: drawn {got or 'empty'}, expected {want}")
    c = tot["cells"]; nbad = sum(tot["cells_bad"].values())
    p(f"\n== background, in play: {c.get('ok', 0)} cells as expected, {c.get('text', 0)} text cells, {c.get('transient', 0)} transient (a block changing), {nbad} place(s) unexpected")
    agg = Counter()
    for (held, tiles, attr, got, want, level), n in tot["cells_bad"].items(): agg[(held, tiles, attr, got, want)] += n
    for (held, tiles, attr, got, want), n in agg.most_common(40): p(f"   x{n:<8d} block {held} drawn with tiles {tiles} (BG palette {attr}) as {got}, expected {want}")
    if tot["text"]: p("   text cells are drawn " + ", ".join(f"{got} (BG palette {a}) x{n}" for (got, a), n in tot["text"].most_common()))
    nb = sum(tot["sprites_bad"].values())
    p(f"\n== sprites: {sum(tot['sprites'].values())} sprites drawn, {nb} with an unexpected colour")
    agg = Counter()
    for (label, tile, pal, got, allowed, level), n in tot["sprites_bad"].items(): agg[(label, tile, pal, got, allowed)] += n
    for (label, tile, pal, got, allowed), n in agg.most_common(60): p(f"   x{n:<8d} {label}: tile ${tile} with sprite palette {pal} drawn {got}, expected {allowed}")
    p("\n   objects and the colour they were drawn with (sprites with no opaque pixel omitted):")
    seen = defaultdict(Counter)
    for (label, tile, pal, got), n in tot["sprites"].items():
        if got != "-": seen[label][got] += n
    for label in sorted(seen): p(f"   {label:42s} " + ", ".join(f"{g} x{n}" for g, n in seen[label].most_common()))
    p("\n== collision boxes: drawn rectangle minus live box (left, top, right, bottom), per object and box size")
    per = defaultdict(Counter)
    for (label, d), n in tot["boxes"].items(): per[label][d] += n
    for label in sorted(per):
        n = sum(per[label].values()); exact = per[label].get("+0,+0,+0,+0", 0)
        rest = ", ".join(f"{d} {100 * k / n:.1f}%" for d, k in per[label].most_common(5) if d != "+0,+0,+0,+0")
        p(f"   {label:42s} n={n:<8d} exact {100 * exact / n:5.1f}%" + (f"   other: {rest}" if rest else ""))
    p("\n== Mario's facing hole (frames where his rectangle is exactly his box)")
    for (facing, side, npx), n in sorted(tot["eye"].items()): p(f"   {facing}, {side} ({npx} px): x{n}")
    nc = sum(tot["colours_bad"].values())
    p(f"\n== rendered frames: {nc} occurrence(s) of a colour outside the legend")
    agg = Counter()
    for (rgb, level), n in tot["colours_bad"].items(): agg[rgb] += n
    for rgb, n in agg.most_common(20): p(f"   {rgb} in {n} frame(s)")
    p("\n== coverage: blocks held by the game in the visible screens, per level")
    for lvl in sorted(tot["blocks"]): p(f"   {lvl:16s} " + " ".join(sorted(k for k in tot["blocks"][lvl] if k != "$00")))
    p("\n== coverage: objects, per level")
    for lvl in sorted(tot["objects"]): p(f"   {lvl:16s} " + "; ".join(sorted(tot["objects"][lvl])))
    for name, err in tot["errors"]: p(f"ERROR {name}: {err}")
    return len(bad) + nbad + nb + nc + len(tot["errors"])

def _job(args):
    parent, game, bk2, every = args
    retro.data.Integrations.add_custom_path(parent)
    try: return audit(game, bk2, Rom(os.path.join(parent, game, "rom.nes")), every)
    except Exception as e:
        import traceback; return dict(replay=os.path.basename(bk2), error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--jobs", type=int, default=1); p.add_argument("--every", type=int, default=2); p.add_argument("--json")
    p.add_argument("mod"); p.add_argument("replays", nargs="+")
    a = p.parse_args()
    parent, game = os.path.dirname(os.path.abspath(a.mod)), os.path.basename(a.mod.rstrip("/"))
    jobs = [(parent, game, bk2, a.every) for bk2 in a.replays]
    if a.jobs > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(a.jobs) as pool: results = list(pool.imap_unordered(_job, jobs))
    else: results = [_job(j) for j in jobs]
    tot = merge(results)
    if a.json: json.dump(results, open(a.json, "w"))
    sys.exit(1 if report(tot, Rom(os.path.join(parent, game, "rom.nes"))) else 0)

if __name__ == "__main__":
    main()
