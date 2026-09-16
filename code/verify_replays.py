#!/usr/bin/env python3
"""Check that a modified ROM replays participant recordings identically to the original ROM.

For each .bk2 given, the recording is replayed with stable-retro on both ROMs
from the recording's own initial state, and the emulator RAM is compared on
every frame.  Differences are only tolerated inside the sprite buffer
($0200-$02FF), the PPU write buffer ($0300-$03FF) and one zero-page scratch
byte ($0004) used by the block-drawing routine: these hold the sprite list,
tile ids and palette bytes queued for the graphics chip and never feed back
into game logic.  Since the sound was simplified, the sound engine's own
state ($F0-$FF, $07B0-$07CA: music pointers, sfx counters, sound queues) is
tolerated too: game logic only writes the queues and only reads one byte
back, EventMusicBuffer ($07B1), to wait for the death and level-clear tunes
to end, and the rewritten tunes keep their frame counts, so every other RAM
byte, i.e. everything the game logic computes, must still match.  A
savestate taken mid-replay on
the original ROM is then loaded into the modified ROM and the remaining
inputs are replayed to check that it tracks the original run.

Usage:
    verify_replays.py [--wav DIR] ORIG_INTEGRATION_DIR MOD_INTEGRATION_DIR REPLAY.bk2 [...]

--wav DIR also writes DIR/<replay>.wav, the audio of the replay on the
modified ROM, to listen to the simplified sound.

Each integration dir is a gym-retro game folder (rom.nes, data.json,
scenario.json, *.state).  Both must live under the same parent directory.
"""
import os, sys, zipfile, wave
import numpy as np
import retro

# RAM the graphics path writes and game logic never reads: the sprite buffer $0200-$02FF, the PPU
# write buffer $0300-$03FF, and zero-page scratch $0004, which the block-drawing routine uses to
# hand its sprite palette to a shared helper (see SPRITE_PATCHES in simplify_rom.py).
PRESENTATION = list(range(0x200, 0x400)) + [0x0004]
# RAM only the sound engine reads and writes (sound queues, music/sfx state): see simplify_rom.py, "sound".
SOUND = list(range(0xF0, 0x100)) + list(range(0x7B0, 0x7CB))

def make(game):
    return retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY,
                      use_restricted_actions=retro.Actions.ALL)

def inputs(bk2, nbuttons):
    m = retro.Movie(bk2); m.step(); keys = []
    while m.step():
        keys.append([m.get_key(i, 0) for i in range(nbuttons)])
    return keys

def run(game, core, keys, save_at, wav=None):
    env = make(game); env.initial_state = core; env.reset()
    rams = [env.get_ram().copy()]; state = None; audio = []
    for f, k in enumerate(keys, 1):
        env.step(k); rams.append(env.get_ram().copy())
        if f == save_at: state = env.em.get_state()
        if wav: audio.append(env.em.get_audio().copy())
    if wav:
        a = np.concatenate(audio).astype(np.int16)
        with wave.open(wav, "wb") as w:
            w.setnchannels(a.shape[1]); w.setsampwidth(2); w.setframerate(int(env.em.get_audio_rate())); w.writeframes(a.tobytes())
    env.close(); return np.array(rams), state

def track(game, state, keys, start, ref, mask):
    env = make(game); env.initial_state = state; env.reset(); env.em.set_state(state)
    for f in range(start + 1, len(keys) + 1):
        env.step(keys[f - 1])
        if not (env.get_ram()[mask] == ref[f][mask]).all():
            env.close(); return f
    env.close(); return None

def main():
    args = sys.argv[1:]; wav_dir = None
    if args[0] == "--wav": wav_dir, args = args[1], args[2:]
    orig_dir, mod_dir, *replays = args
    retro.data.Integrations.add_custom_path(os.path.dirname(os.path.abspath(orig_dir)))
    orig, mod = os.path.basename(orig_dir.rstrip('/')), os.path.basename(mod_dir.rstrip('/'))
    env = make(orig); nb = env.num_buttons; env.close()   # NES = 9 buttons; reading fewer drops A
    ok = True
    for bk2 in replays:
        core = zipfile.ZipFile(bk2).read('Core.bin'); keys = inputs(bk2, nb); mid = len(keys) // 2
        wav = os.path.join(wav_dir, os.path.basename(bk2)[:-4] + ".wav") if wav_dir else None
        ro, so = run(orig, core, keys, mid); rm, _ = run(mod, core, keys, mid, wav)
        mask = np.ones(ro.shape[1], bool); mask[PRESENTATION] = False; mask[SOUND] = False
        diff = ro != rm
        outside = int(diff[:, mask].any(1).sum())
        addrs = np.where(diff)[1]
        rng = f"${addrs.min():03X}-${addrs.max():03X}" if len(addrs) else "-"
        first_bad = track(mod, so, keys, mid, ro, mask)
        good = outside == 0 and first_bad is None; ok &= good
        print(f"{os.path.basename(bk2)}: frames={len(keys)} differing_addresses={rng} "
              f"frames_differing_outside_ppu_and_sound={outside} state_tracks={first_bad is None} -> {'OK' if good else 'FAIL'}")
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
