#!/usr/bin/env python3
"""Regenerate the figures of docs/ and paper/figures/ from participant recordings and the level states.

Every panel is a frame of a recording of the mario dataset (or of a level
state played with scripted input), rendered once on the original ROM and once
on the simplified ROM: the game logic is identical, so the two frames show the
same instant.  The recordings and frame numbers are listed below.

Usage:
    make_figures.py ORIG_INTEGRATION_DIR MOD_INTEGRATION_DIR MARIO_DATASET_DIR ORIG_STATES_DIR [FIGURE ...]

ORIG_INTEGRATION_DIR / MOD_INTEGRATION_DIR: gym-retro game folders holding the
original and the simplified rom.nes (same parent directory);
MARIO_DATASET_DIR: root of the mario dataset (sub-*/ses-*/gamelogs/*.bk2);
ORIG_STATES_DIR: the SuperMarioBros-Nes folder of mario.stimuli (level states
with the original palette).  FIGURE: compare, levels, hitbox, cues,
tilesheet (default: all).  Writes docs/original_vs_simplified.png and
paper/figures/*.png.
"""
import os, sys, glob, gzip, zipfile, importlib.util
import numpy as np
from PIL import Image, ImageDraw
try:
    import stable_retro as retro
except ImportError:
    import retro

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
fs = _load("fix_state")

R = "sub-{s}/ses-{e}/gamelogs/sub-{s}_ses-{e}_task-mario_level-{l}_rep-{r}.bk2"
def rec(s, e, l, r): return R.format(s=s, e=e, l=l, r=r)
# figure "compare": (recording, frame)
COMPARE = [(rec("06", "010", "w1l1", "001"), 580),      # question blocks, bricks, a stomped Goomba, a score
           (rec("06", "001", "w1l1", "000"), 1154),     # a question block just hit: the used block bounces, a coin pops out
           (rec("06", "001", "w1l2", "002"), 1880),     # underground: coins, bricks, Koopas
           (rec("06", "007", "w3l1", "000"), 4670),     # night: a springboard, fire Mario
           (rec("06", "012", "w7l1", "000"), 1610)]     # cannons and their Bullet Bills, question blocks
# figure "hitbox": (label, recording, frame, first line of the 136-line crop)
HITBOX = [("Goomba", rec("06", "001", "w1l1", "001"), 263, 88),
          ("Koopa and shell", rec("06", "001", "w1l2", "000"), 4785, 88),
          ("Hammer Bro and hammer", rec("06", "013", "w3l1", "001"), 13571, 40),
          ("Bullet Bills", rec("06", "012", "w7l1", "000"), 1610, 88),
          ("lift", rec("06", "001", "w1l3", "002"), 2077, 88)]
# figure "cues": (caption, recording, frame, centre x, centre y)
CUES = [("question blocks (interactive) among bricks (breakable)", rec("06", "010", "w1l1", "001"), 580, 215, 130),
        ("a block just hit bounces as the used block it has become; a coin pops out", rec("06", "001", "w1l1", "000"), 1154, 40, 130),
        ("coins (collectible) set in bricks", rec("06", "002", "w3l1", "000"), 3050, 110, 110),
        ("cannon: the barrel is the launcher, pedestal and column are terrain", rec("06", "012", "w7l1", "000"), 1610, 150, 190),
        ("springboard: interactive, striped, on a terrain base", rec("06", "013", "w3l1", "001"), 14116, 166, 176),
        ("Hammer Bro (8x24) and hammers (8x8)", rec("06", "013", "w3l1", "001"), 13571, 199, 120),
        ("Piranha Plant: toothed edge (cannot be stomped)", rec("05", "015", "w4l2", "000"), 10213, 195, 139),
        ("Paratroopa: wing bar above the box", rec("06", "001", "w1l3", "002"), 5576, 192, 121),
        ("Koopa shell: hollow; walking Koopa: solid", rec("06", "001", "w1l2", "000"), 4785, 94, 184),
        ("dying Mario: hollow", rec("06", "001", "w1l1", "003"), 6214, 77, 151),
        ("Goomba: a 10x6 box; Mario: the hole is on the side he faces", rec("06", "001", "w1l1", "001"), 272, 125, 165),
        ("Lakitu and a Spiny egg", rec("05", "003", "w4l1", "002"), 203, 151, 60),
        ("super mushroom: green", rec("06", "001", "w1l1", "001"), 512, 58, 120),
        ("1-up: dark green", rec("06", "001", "w2l1", "003"), 1705, 63, 56),
        ("fire flower: fire-Mario deep blue", rec("06", "007", "w3l1", "000"), 2322, 80, 72),
        ("star: pale pink", rec("06", "001", "w1l1", "001"), 4508, 60, 120),
        ("lift: terrain", rec("06", "001", "w1l3", "002"), 2077, 152, 194),
        ("flagpole, flag and its score: goal", rec("06", "001", "w1l1", "001"), 8183, 123, 141)]

SCALE = 2
GAP = 8
OVERSCAN = 8      # the emulator returns 240x224 pixels: the NES picture (256x240) without 8 pixels on each side

def make(game):
    return retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY, use_restricted_actions=retro.Actions.ALL, render_mode="rgb_array")

def grab(game, bk2, frames, fix):
    """{frame: (image, RAM)} of a recording replayed on a ROM."""
    core = zipfile.ZipFile(bk2).read("Core.bin")
    if fix: core = fs.fix(core)[0]
    env = make(game); env.initial_state = core; env.reset(); m = retro.Movie(bk2); m.step(); out = {}; f = 0
    while f < max(frames) and m.step():
        obs, *_ = env.step([m.get_key(i, 0) for i in range(env.num_buttons)]); f += 1
        if f in frames: out[f] = (Image.fromarray(obs), env.get_ram().copy())
    env.close(); return out

def scripted(game, state, n=420):
    """Image after n frames of scripted input from a state: run right, jump periodically."""
    env = make(game); env.initial_state = state; env.reset()
    for f in range(n):
        k = [0] * env.num_buttons; k[7] = 1; k[8] = int(f % 60 < 20)
        obs, *_ = env.step(k)
    env.close(); return Image.fromarray(obs)

def big(im, scale=SCALE): return im.resize((im.width * scale, im.height * scale), Image.NEAREST)

def sheet(rows, labels=None, bg=(255, 255, 255), pad=14):
    """rows: list of lists of images (all the same size) -> one image; labels: one caption per row, drawn above it."""
    w, h = rows[0][0].size; top = pad if labels else 0
    out = Image.new("RGB", (len(rows[0]) * (w + GAP) - GAP, len(rows) * (h + GAP + top) - GAP), bg); d = ImageDraw.Draw(out)
    for r, row in enumerate(rows):
        y = r * (h + GAP + top)
        if labels: d.text((2, y + 1), labels[r], fill=(0, 0, 0))
        for c, im in enumerate(row): out.paste(im, (c * (w + GAP), y + top))
    return out

def boxes(im, r):
    """Draw the collision boxes the game is using ($04AC-$04DB) on a frame."""
    ac = _load("audit_colours"); d = ImageDraw.Draw(im); own = set(ac.owners(r).values())
    for kind, slot in own:
        k = ac.live_box(kind, slot, r)
        if k is None: continue
        x0, y0, x1, y1 = (int(v) - OVERSCAN for v in r[0x4AC + 4 * k:0x4B0 + 4 * k])
        if x0 < x1 and y0 < y1: d.rectangle((x0, y0 + 1, x1 - 1, y1), outline=(255, 0, 255))     # the PPU shows sprites one line below their Y
    return im

def fig_compare(orig, mod, data):
    top, bottom = [], []
    for bk2, f in COMPARE:
        p = os.path.join(data, bk2); top.append(grab(orig, p, {f}, False)[f][0]); bottom.append(grab(mod, p, {f}, True)[f][0])
    im = sheet([top, bottom])
    im.save(os.path.join(ROOT, "docs", "original_vs_simplified.png")); im.save(os.path.join(ROOT, "paper", "figures", "original_vs_simplified.png"))

def fig_levels(orig, mod, states):
    names = [f"Level{w}-{l}" for w in range(1, 9) for l in (1, 2, 3)]; pairs = []
    for n in names:
        a = scripted(orig, gzip.decompress(open(os.path.join(states, n + ".state"), "rb").read()))
        b = scripted(mod, gzip.decompress(open(os.path.join(ROOT, "SuperMarioBros-Nes", n + ".state"), "rb").read()))
        pair = Image.new("RGB", (2 * a.width + 4, a.height + 12), (255, 255, 255)); ImageDraw.Draw(pair).text((2, 0), "World " + n[5:], fill=(0, 0, 0))
        pair.paste(a, (0, 12)); pair.paste(b, (a.width + 4, 12)); pairs.append(pair)
    sheet([pairs[i:i + 4] for i in range(0, 24, 4)]).save(os.path.join(ROOT, "paper", "figures", "levels_original_vs_simplified.png"))

def fig_hitbox(orig, mod, data):
    rows, labels = [], []
    for label, bk2, f, top in HITBOX:
        p = os.path.join(data, bk2); a, r = grab(orig, p, {f}, False)[f]; b, _ = grab(mod, p, {f}, True)[f]
        crop = (0, top, a.width, top + 136)
        rows.append([big(boxes(a, r).crop(crop)), big(b.crop(crop))]); labels.append(f"{label} (level {bk2.split('level-w')[1][0]}-{bk2.split('level-w')[1][2]}, frame {f})")
    sheet(rows, labels).save(os.path.join(ROOT, "paper", "figures", "hitbox_original_vs_simplified.png"))

def fig_cues(orig, mod, data):
    cells = []
    for caption, bk2, f, cx, cy in CUES:
        p = os.path.join(data, bk2); a = grab(orig, p, {f}, False)[f][0]; b = grab(mod, p, {f}, True)[f][0]
        cx, cy = cx - OVERSCAN, cy - OVERSCAN                                                       # CUES gives NES coordinates
        x0 = min(max(cx - 56, 0), a.width - 112); y0 = min(max(cy - 44, 0), a.height - 80); crop = (x0, y0, x0 + 112, y0 + 80)
        pair = Image.new("RGB", (2 * 336 + 6, 240 + 14), (255, 255, 255)); ImageDraw.Draw(pair).text((2, 1), caption, fill=(0, 0, 0))
        pair.paste(big(a.crop(crop), 3), (0, 14)); pair.paste(big(b.crop(crop), 3), (342, 14)); cells.append(pair)
    if len(cells) % 2: cells.append(Image.new("RGB", cells[0].size, (255, 255, 255)))
    sheet([cells[i:i + 2] for i in range(0, len(cells), 2)]).save(os.path.join(ROOT, "paper", "figures", "cues_original_vs_simplified.png"))

def fig_tilesheet(orig_dir, mod_dir):
    grey = np.array([(88, 152, 248), (48, 48, 48), (136, 136, 136), (216, 216, 216)], np.uint8)       # index 0 in blue, 1-3 in greys
    def tiles(path):
        chr_ = open(path, "rb").read()[16 + 0x8000:]; bits = np.unpackbits(np.frombuffer(chr_, np.uint8).reshape(512, 2, 8, 1), axis=3)
        idx = bits[:, 0] | (bits[:, 1] << 1); img = np.zeros((32 * 8, 16 * 8), np.uint8)
        for t in range(512): img[(t // 16) * 8:(t // 16) * 8 + 8, (t % 16) * 8:(t % 16) * 8 + 8] = idx[t]
        return big(Image.fromarray(grey[img]))
    sheet([[tiles(os.path.join(orig_dir, "rom.nes")), tiles(os.path.join(mod_dir, "rom.nes"))]], ["original (left) and simplified (right): sprite tiles above, background tiles below"]).save(
        os.path.join(ROOT, "paper", "figures", "tilesheet_original_vs_simplified.png"))

def main():
    orig_dir, mod_dir, data, states, *which = sys.argv[1:]
    retro.data.Integrations.add_custom_path(os.path.dirname(os.path.abspath(orig_dir)))
    orig, mod = os.path.basename(orig_dir.rstrip("/")), os.path.basename(mod_dir.rstrip("/"))
    which = which or ["compare", "levels", "hitbox", "cues", "tilesheet"]
    if "compare" in which: fig_compare(orig, mod, data)
    if "levels" in which: fig_levels(orig, mod, states)
    if "hitbox" in which: fig_hitbox(orig, mod, data)
    if "cues" in which: fig_cues(orig, mod, data)
    if "tilesheet" in which: fig_tilesheet(orig_dir, mod_dir)

if __name__ == "__main__":
    main()
