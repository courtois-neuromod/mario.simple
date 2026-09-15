#!/usr/bin/env python3
"""Check that a modified ROM replays participant recordings identically to the original ROM.

For each .bk2 given, the recording is replayed with stable-retro on both ROMs
from the recording's own initial state, and the emulator RAM is compared on
every frame.  Differences are only tolerated inside the PPU write buffer
($0300-$03FF), which holds tile ids and palette bytes queued for the graphics
chip and never feeds back into game logic.  A savestate taken mid-replay on
the original ROM is then loaded into the modified ROM and the remaining
inputs are replayed to check that it tracks the original run.

Usage:
    verify_replays.py ORIG_INTEGRATION_DIR MOD_INTEGRATION_DIR REPLAY.bk2 [...]

Each integration dir is a gym-retro game folder (rom.nes, data.json,
scenario.json, *.state).  Both must live under the same parent directory.
"""
import os, sys, zipfile
import numpy as np
import retro

VRAM_BUFFER = range(0x300, 0x400)

def make(game):
    return retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY,
                      use_restricted_actions=retro.Actions.ALL)

def inputs(bk2, nbuttons):
    m = retro.Movie(bk2); m.step(); keys = []
    while m.step():
        keys.append([m.get_key(i, 0) for i in range(nbuttons)])
    return keys

def run(game, core, keys, save_at):
    env = make(game); env.initial_state = core; env.reset()
    rams = [env.get_ram().copy()]; state = None
    for f, k in enumerate(keys, 1):
        env.step(k); rams.append(env.get_ram().copy())
        if f == save_at: state = env.em.get_state()
    env.close(); return np.array(rams), state

def track(game, state, keys, start, ref, mask):
    env = make(game); env.initial_state = state; env.reset(); env.em.set_state(state)
    for f in range(start + 1, len(keys) + 1):
        env.step(keys[f - 1])
        if not (env.get_ram()[mask] == ref[f][mask]).all():
            env.close(); return f
    env.close(); return None

def main():
    orig_dir, mod_dir, *replays = sys.argv[1:]
    retro.data.Integrations.add_custom_path(os.path.dirname(os.path.abspath(orig_dir)))
    orig, mod = os.path.basename(orig_dir.rstrip('/')), os.path.basename(mod_dir.rstrip('/'))
    env = make(orig); nb = env.num_buttons; env.close()   # NES = 9 buttons; reading fewer drops A
    ok = True
    for bk2 in replays:
        core = zipfile.ZipFile(bk2).read('Core.bin'); keys = inputs(bk2, nb); mid = len(keys) // 2
        ro, so = run(orig, core, keys, mid); rm, _ = run(mod, core, keys, mid)
        mask = np.ones(ro.shape[1], bool); mask[list(VRAM_BUFFER)] = False
        diff = ro != rm
        outside = int(diff[:, mask].any(1).sum())
        addrs = np.where(diff)[1]
        rng = f"${addrs.min():03X}-${addrs.max():03X}" if len(addrs) else "-"
        first_bad = track(mod, so, keys, mid, ro, mask)
        good = outside == 0 and first_bad is None; ok &= good
        print(f"{os.path.basename(bk2)}: frames={len(keys)} differing_addresses={rng} "
              f"frames_differing_outside_vram_buffer={outside} state_tracks={first_bad is None} -> {'OK' if good else 'FAIL'}")
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
