#!/usr/bin/env python3
"""Measure, for every sprite tile, where it sits relative to its object's collision box.

Super Mario Bros computes each object's collision box from the object's
relative screen position plus one of 12 four-byte offset entries
(BoundBoxCtrlData: left, top, right, bottom), selected by a per-object box
control byte ($0499-$04A2).  The boxes are stored in RAM at $04AC-$04DB (player,
six enemy slots, two fireballs, misc objects; four bytes each: UL x, UL y, LR x,
LR y).  The sprites of the same object are drawn at fixed offsets from the same
position, so the pixels of a given tile that fall inside the box are fixed.

Replaying recordings on the original ROM and reading, every second frame, the
sprite buffer ($0200-$02FF), the object -> sprite-offset tables ($06E4-$06FB)
and the live boxes gives, for every tile: the owner object (id and state), the
tile's offset from the box corner and the box size, with horizontal/vertical
flips folded back into CHR space.  The dominant geometry per tile is the
HITBOX table of simplify_rom.py.  Objects whose state disables collisions
(defeated enemies, d5 set; squished Goombas) and objects without a box are
skipped.

Usage: hitbox_survey.py ORIG_INTEGRATION_DIR REPLAY.bk2 [...]  > hitbox.txt
Prints one line per tile: tile, owner, dx, dy, w, h, share of observations.
"""
import os, sys, zipfile
from collections import defaultdict, Counter
import retro

def s8(v): return ((v + 128) & 0xFF) - 128

def live(name):
    """True if the owner's collision box is actually used by the game."""
    if name.startswith('ENEMY_'):
        eid, st = int(name[6:8], 16), int(name.split('_s')[1], 16)
        return not (st & 0x20 or eid >= 0x2F or (eid == 0x06 and (st & 7) >= 2))
    if name.startswith('MISC_'): return int(name[6:], 16) >= 0x80       # hammers
    return name.startswith(('MARIO', 'POWERUP', 'FIREBALL'))

def main():
    orig_dir, *replays = sys.argv[1:]
    retro.data.Integrations.add_custom_path(os.path.dirname(os.path.abspath(orig_dir)))
    game = os.path.basename(orig_dir.rstrip('/'))
    obs = defaultdict(Counter)            # tile -> Counter[(owner, dx, dy, w, h)]
    for bk2 in replays:
        core = zipfile.ZipFile(bk2).read('Core.bin'); m = retro.Movie(bk2); m.step()
        env = retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY,
                         use_restricted_actions=retro.Actions.ALL)
        env.initial_state = core; env.reset(); f = 0
        while m.step():
            env.step([m.get_key(i, 0) for i in range(env.num_buttons)]); f += 1
            if f % 2: continue
            r = env.get_ram(); oam = r[0x200:0x300]; owners = {}
            def tag(off, n, name, k):
                for j in range(n): owners.setdefault(int(off) + 4*j, (name, k))
            tag(r[0x6E4], 8, f'MARIO_c{int(r[0x499])}', 0)
            for s in range(6):
                if r[0x0F + s]:
                    eid, st = int(r[0x16 + s]), int(r[0x1E + s])
                    tag(r[0x6E5 + s], 6, f'POWERUP_{int(r[0x39])}' if eid == 0x2E else f'ENEMY_{eid:02X}_s{st:02X}', 1 + s)
            for s in range(2): tag(r[0x6F1 + s], 1, f'FIREBALL_s{int(r[0x24 + s]):02X}', 7 + s)
            for s in range(9): tag(r[0x6F3 + s], 1, f'MISC_s{int(r[0x2A + s]):02X}', 9 + s)
            for i in range(0, 256, 4):
                y, t, a, x = (int(v) for v in oam[i:i + 4])
                if y >= 0xF0 or i not in owners or not live(owners[i][0]): continue
                name, k = owners[i]
                ulx, uly, lrx, lry = (int(v) for v in r[0x4AC + 4*k: 0x4B0 + 4*k])
                w, h = (lrx - ulx) & 0xFF, (lry - uly) & 0xFF
                if (ulx, uly, lrx, lry) == (0xFF,)*4 or not (0 < w < 128 and 0 < h < 128): continue
                dx, dy = s8(x - ulx), s8(y - uly)
                if a & 0x40: dx = w - 8 - dx           # horizontal flip: fold into CHR space
                if a & 0x80: dy = h - 8 - dy           # vertical flip
                obs[t][(name.split('_s')[0], dx, dy, w, h)] += 1
        env.close(); print('done', os.path.basename(bk2), file=sys.stderr)
    for t in sorted(obs):
        (name, dx, dy, w, h), n = obs[t].most_common(1)[0]
        print(f"{t:02X} {name:10s} dx={dx:3d} dy={dy:3d} w={w:2d} h={h:2d} share={n / sum(obs[t].values()):.2f}")

if __name__ == '__main__':
    main()
