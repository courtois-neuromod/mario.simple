#!/usr/bin/env python3
"""Measure which sprite tiles belong to which game object, from participant replays.

Super Mario Bros builds its sprite list (OAM) in RAM at $0200-$02FF, and keeps
for each object the offset of its entries: the player at $06E4, the six enemy
slots (slot 5 is the power-up object) at $06E5-$06EA, bumped blocks at
$06EC-$06ED, bubbles at $06EE-$06F0, fireballs at $06F1-$06F2 and misc
objects (coins, hammers) at $06F3-$06FB.  Enemy ids are at $0016-$001B with
active flags at $000F-$0014; the power-up type is at $0039.

Replaying recordings on the original ROM and reading these every few frames
gives, for every tile id, the object that drew it and the sprite palette it
was drawn with.  This is how the sprite classification in simplify_rom.py was
obtained (66 replays, 3 per level, all 22 levels of the mario dataset).

Usage: survey_sprite_tiles.py ORIG_INTEGRATION_DIR REPLAY.bk2 [...]  > survey.txt
"""
import os, sys, zipfile
from collections import defaultdict, Counter
import retro

def main():
    orig_dir, *replays = sys.argv[1:]
    retro.data.Integrations.add_custom_path(os.path.dirname(os.path.abspath(orig_dir)))
    game = os.path.basename(orig_dir.rstrip('/'))
    owner_of = defaultdict(Counter); palette_of = defaultdict(Counter)
    for bk2 in replays:
        core = zipfile.ZipFile(bk2).read('Core.bin'); m = retro.Movie(bk2); m.step()
        env = retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY,
                         use_restricted_actions=retro.Actions.ALL)
        env.initial_state = core; env.reset(); f = 0
        while m.step():
            env.step([m.get_key(i, 0) for i in range(env.num_buttons)]); f += 1
            if f % 3: continue
            r = env.get_ram(); oam = r[0x200:0x300]; owners = {}
            def tag(off, n, name):
                for k in range(n): owners.setdefault(int(off) + 4 * k, name)
            tag(r[0x6E4], 8, 'MARIO')
            for s in range(6):
                if r[0x0F + s]:
                    eid = int(r[0x16 + s])
                    tag(r[0x6E5 + s], 6, f'POWERUP_{int(r[0x39])}' if eid == 0x2E else f'ENEMY_{eid:02X}')
            tag(r[0x6EC], 4, 'BLOCK'); tag(r[0x6ED], 4, 'BLOCK')
            for s in range(3): tag(r[0x6EE + s], 1, 'BUBBLE')
            for s in range(2): tag(r[0x6F1 + s], 1, 'FIREBALL')
            for s in range(9): tag(r[0x6F3 + s], 1, 'MISC')
            for i in range(0, 256, 4):
                y, t, a, x = oam[i:i + 4]
                if y >= 0xF0: continue
                owner_of[int(t)][owners.get(i, 'UNKNOWN')] += 1; palette_of[int(t)][int(a) & 3] += 1
        env.close(); print('done', os.path.basename(bk2), file=sys.stderr)
    by_owner = defaultdict(list)
    for t in sorted(owner_of):
        o, n = owner_of[t].most_common(1)[0]; share = n / sum(owner_of[t].values())
        by_owner[o].append(f"{t:02X}(pal{palette_of[t].most_common(1)[0][0]}{'' if share > 0.9 else '*'})")
    for o in sorted(by_owner):
        print(o, ' '.join(by_owner[o]))

if __name__ == '__main__':
    main()
