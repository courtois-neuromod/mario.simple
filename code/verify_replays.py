#!/usr/bin/env python3
"""Check that a modified ROM replays participant recordings identically to the original ROM.

For each .bk2 given, the recording is replayed with stable-retro on both ROMs
from the recording's own initial state, and the 2 KB of console RAM are
compared after every frame.  A savestate taken mid-replay on the original ROM
is then loaded into the modified ROM and the remaining inputs are replayed, to
check that it tracks the original run.

What "after every frame" means.  The emulator returns once per video frame.
On almost every frame the CPU is then parked in the game's idle loop ($8057,
`jmp` to itself, stack pointer $FF): the interrupt handler has uploaded the
graphics, run the sound engine and run all the game logic of that frame.  RAM
is compared on those frames only.  On the few frames where the CPU is still
inside the interrupt handler (the game wipes its RAM over more than one frame
when an area loads), the two ROMs are a few CPU cycles apart, because the
sound code differs, and a snapshot is not comparable; those frames are counted
and skipped, and any real divergence would still show on the next frame.

Which bytes may differ.  Everything the game logic computes must be equal.
The bytes that only describe what is drawn or played are tolerated:

  $0200-$02FF  the sprite buffer: the tile and the attribute byte of each
               sprite.  The two position bytes (Y, X) must be equal, since
               the simplified ROM is meant to draw every sprite where the
               original does, except for: a sprite that is off screen
               (Y >= $EF) or shows the blank tile ($FC) on both ROMs, whose
               bytes are left over from an earlier object; the sprites of a
               hammer (tiles $80-$83 on the original), which the simplified
               ROM draws as one square on its collision box, 4 px to the
               left or 4 px up; and those of a Bullet Bill (tiles $E7-$EA)
               while one fired by a cannon exists, drawn 1 px lower (see
               $0002).  One position byte is read by game logic and must be
               equal whatever the sprite shows: $0207, the horizontal
               position of Mario's first sprite (the fire bars of the castle
               levels test a hit against it, at $CE46);
  $0301-$033F, $0341-$0362  the two PPU write buffers (tile numbers, palette
               and attribute bytes queued for the graphics chip).  Each starts
               with its length, at $0300 and $0340, which must be equal;
  $0363-$03FF  only where the second buffer reaches: it grows over these
               addresses while an area loads (four columns of the first
               screen per frame), whereas during play they hold game
               variables.  A byte there may differ if it is inside the length
               queued on that frame, or has not been written since it was;
  $0004        zero-page scratch through which the drawing routines pass a
               sprite's palette (see SPRITE_PATCHES in simplify_rom.py);
  $0002        zero-page scratch through which the enemy drawing routine
               passes the row it draws.  The original ROM raises a Bullet
               Bill fired by a cannon by one pixel there ("dec $02"), the
               simplified ROM does not (SPRITE_PATCHES), so the byte is left
               one higher.  Only that is tolerated: modified = original + 1,
               on a frame where such a Bullet Bill exists or existed on the
               frame before, and for as long as neither run writes the byte
               again (a paused game);
  $00F0-$00FF, $07B0-$07CA  the sound engine's own state (queues, buffers,
               music pointers, counters).  Game logic only writes the queues
               and reads one byte back, EventMusicBuffer ($07B1), to wait for
               the death and level-clear tunes; the rewritten tunes keep their
               frame counts, so a difference there would desynchronise the
               logic and show everywhere else;
  $0160-$01FF  the CPU stack (the game itself excludes this range when it
               wipes RAM).  In the idle loop the stack is empty and these
               bytes are leftovers: return addresses of routines that have
               returned, among them those of the replaced sound code.

Usage:
    verify_replays.py [--jobs N] [--track-every N] [--fix-state] [--wav DIR] [--json OUT] ORIG_INTEGRATION_DIR MOD_INTEGRATION_DIR REPLAY.bk2 [...]

--track-every N does the savestate check (a third replay) for one recording
in N only; the frame-by-frame comparison is always done.

--fix-state starts the run on the modified ROM from the recording's initial
state as rewritten by fix_state.py (palette, sound state, drawn screen), which
is how a recording made on the original ROM is rendered on the simplified
one; the comparison is then between that run and the untouched one on the
original ROM.  --wav DIR also writes DIR/<replay>.wav, the audio of the replay
on the modified ROM, to listen to the simplified sound.  --json writes the
per-replay details.  Each integration dir is a gym-retro game folder (rom.nes,
data.json, scenario.json, *.state).  Both must live under the same parent
directory.
"""
import os, sys, json, zipfile, wave, argparse
from collections import Counter
import numpy as np
try:
    import stable_retro as retro
except ImportError:
    import retro

IDLE = (0x8057, 0xFF)                   # EndlessLoop: jmp EndlessLoop, with an empty stack
INIT_MEMORY = range(0x90CC, 0x90E6)     # InitializeMemory, the only routine known to span a frame boundary
SPRITES = [a for a in range(0x200, 0x300) if a != 0x207]    # $0207 is read by game logic: see above
OFF_SCREEN, BLANK, HAMMER, BULLET = 0xEF, 0xFC, range(0x80, 0x84), range(0xE7, 0xEB)   # sprite Y from which nothing is drawn; sprite tiles
SOUND = list(range(0xF0, 0x100)) + list(range(0x7B0, 0x7CB))
SCRATCH = [0x04]
ROW, CANNON_BULLET, ENEMY_ID = 0x02, 0x33, range(0x16, 0x19)      # scratch $02; a Bullet Bill fired by a cannon lives in enemy slots 0-2
STACK = range(0x160, 0x200)
BUFFERS = list(range(0x301, 0x340)) + list(range(0x341, 0x363))   # PPU write buffers 1 and 2, the part nothing else uses
BUFFER2, SHARED = 0x341, 0x363                                    # buffer 2 (length at $0340) can extend over $0363-$03FF
REG_PC, REG_S = b"PC\0\0" + (2).to_bytes(4, "little"), b"S\0\0\0" + (1).to_bytes(4, "little")

def make(game):
    return retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY,
                      use_restricted_actions=retro.Actions.ALL, render_mode="rgb_array")

def inputs(bk2, nbuttons):
    m = retro.Movie(bk2); m.step(); keys = []
    while m.step():
        keys.append([m.get_key(i, 0) for i in range(nbuttons)])
    return keys

def cpu_regs(state):
    """(program counter, stack pointer) stored in an fceumm savestate."""
    i, j = state.find(REG_PC), state.find(REG_S)
    assert i >= 0 and j >= 0, "CPU registers not found in the savestate"
    return int.from_bytes(state[i + 8:i + 10], "little"), state[j + 8]

def run(game, core, keys, save_at=None, wav=None, resume=None):
    """Replay keys; return (RAM per frame, (PC, S) per frame, state saved after frame save_at).
    Row 0 is the starting point.  resume=(state, frame) starts from that state instead of core."""
    init, start = resume if resume else (core, 0)
    env = make(game); env.initial_state = init; env.reset()
    if resume: env.em.set_state(init)
    ram = lambda: env.get_ram()[:0x800].copy()                    # console RAM; the core also exposes 8 KB of cartridge RAM, which this game does not have
    rams = [ram()]; regs = [cpu_regs(env.em.get_state())]; saved = None; audio = []
    for f in range(start + 1, len(keys) + 1):
        env.step(keys[f - 1]); rams.append(ram()); state = env.em.get_state(); regs.append(cpu_regs(state))
        if f == save_at: saved = state
        if wav: audio.append(env.em.get_audio().copy())
    if wav:
        a = np.concatenate(audio).astype(np.int16)
        with wave.open(wav, "wb") as w:
            w.setnchannels(a.shape[1]); w.setsampwidth(2); w.setframerate(int(env.em.get_audio_rate())); w.writeframes(a.tobytes())
    env.close(); return np.array(rams), np.array(regs), saved

def placed_elsewhere(o, m, shot):
    """Which of the 64 sprites may have other position bytes (Y, X) on the modified ROM (see the module docstring).
    o, m: RAM of the frame on the two ROMs; shot: a Bullet Bill fired by a cannon exists, or did on the frame before."""
    o, m = o[0x200:0x300].reshape(64, 4).astype(np.int16), m[0x200:0x300].reshape(64, 4).astype(np.int16)
    dy, dx = (m[:, 0] - o[:, 0]) & 0xFF, (m[:, 3] - o[:, 3]) & 0xFF
    unseen = ((o[:, 0] >= OFF_SCREEN) & (m[:, 0] >= OFF_SCREEN)) | ((o[:, 1] == BLANK) & (m[:, 1] == BLANK))
    hammer = np.isin(o[:, 1], HAMMER) & (((dy == 0) & (dx == 0xFC)) | ((dy == 0xFC) & (dx == 0)))
    bill = np.isin(o[:, 1], BULLET) & (dy == 1) & (dx == 0) & shot
    return unseen | hammer | bill

def compare(ro, co, rm, cm, first=0):
    """Compare two runs frame by frame (see the module docstring).  Returns a dict:
    bad: [(frame, address, original, modified)...] differences that are not tolerated (first 50),
    bad_frames, bad_addresses, compared: frames compared, skipped: {(PC orig, PC mod): frames not in the idle loop},
    tolerated: {region: [lowest address, highest address, frames]}."""
    regions = (("sprite buffer", SPRITES), ("sound engine", SOUND), ("scratch $04", SCRATCH), ("dead stack", STACK), ("PPU write buffers", BUFFERS))
    always = np.zeros(2048, bool); region_of = np.full(2048, "", dtype=object)
    for name, region in regions: always[list(region)] = True; region_of[list(region)] = name
    idle = (co[:, 0] == IDLE[0]) & (co[:, 1] == IDLE[1]) & (cm[:, 0] == IDLE[0]) & (cm[:, 1] == IDLE[1])
    skipped = Counter((int(a), int(b)) for a, b in zip(co[~idle, 0], cm[~idle, 0]))
    explained = np.zeros(0x400 - SHARED, bool)                     # $0363-$03FF: byte currently explained as content of buffer 2
    bullet = (ro[:, list(ENEMY_ID)] == CANNON_BULLET).any(axis=1); row = False   # $0002: currently explained as the row of a cannon-fired Bullet Bill
    bad, bad_frames, bad_addr, tol = [], 0, Counter(), {}
    def note(name, addrs):
        if len(addrs):
            t = tol.setdefault(name, [int(addrs.min()), int(addrs.max()), 0])
            t[0] = min(t[0], int(addrs.min())); t[1] = max(t[1], int(addrs.max())); t[2] += 1
    for f in range(len(ro)):
        queued = np.zeros(0x400 - SHARED, bool)
        queued[:max(0, BUFFER2 + max(int(ro[f, 0x340]), int(rm[f, 0x340])) + 1 - SHARED)] = True
        if f == 0: explained = queued
        else:
            untouched = (ro[f, SHARED:0x400] == ro[f - 1, SHARED:0x400]) & (rm[f, SHARED:0x400] == rm[f - 1, SHARED:0x400])
            explained = queued | (explained & untouched)
        row = bool(bullet[f] or (f and bullet[f - 1]) or (row and f and ro[f, ROW] == ro[f - 1, ROW] and rm[f, ROW] == rm[f - 1, ROW]))
        if not idle[f]: continue                                   # mid-logic: not comparable (the bookkeeping above still runs)
        d = ro[f] != rm[f]
        if not d.any(): continue
        ok = always.copy(); ok[SHARED:0x400] = explained
        ok[ROW] = row and (int(rm[f, ROW]) - int(ro[f, ROW])) & 0xFF == 1
        if d[0x200:0x300:4].any() or d[0x203:0x300:4].any():      # a sprite is drawn elsewhere: only where that is meant ($0207 stays strict)
            free = placed_elsewhere(ro[f], rm[f], bool(bullet[f] or (f and bullet[f - 1])))
            ok[0x200:0x300:4] &= free; ok[0x203:0x300:4] &= free
        v = np.where(d & ~ok)[0]
        if len(v):
            bad_frames += 1; bad_addr.update(int(a) for a in v)
            if len(bad) < 50: bad += [(int(f) + first, int(a), int(ro[f, a]), int(rm[f, a])) for a in v[:10]]
        a = np.where(d & ok)[0]
        for name, _ in regions: note(name, a[region_of[a] == name])
        note("scratch $02, cannon-fired Bullet Bill", a[a == ROW])
        note("sprite positions", a[(a >= 0x200) & (a < 0x300) & ((a & 3) % 3 == 0)])
        b = a[a >= SHARED] if len(a) else a; b = b[b < 0x400]
        note("buffer 2 over $0363-$03FF, queued", b[queued[b - SHARED]]); note("buffer 2 over $0363-$03FF, leftover", b[~queued[b - SHARED]])
    return dict(bad=bad, bad_frames=bad_frames, bad_addresses={f"${a:04X}": n for a, n in sorted(bad_addr.items())},
                compared=int(idle.sum()), skipped={f"${a:04X}/${b:04X}": n for (a, b), n in sorted(skipped.items())},
                skipped_elsewhere=sum(n for (a, b), n in skipped.items() if a not in INIT_MEMORY or b not in INIT_MEMORY),
                tolerated={k: [f"${lo:04X}", f"${hi:04X}", n] for k, (lo, hi, n) in tol.items()})

def verify(orig, mod, bk2, wav=None, fix_state=False, track=True):
    """Replay one recording on both ROMs; return the result dict (ok: bool)."""
    env = make(orig); nb = env.num_buttons; env.close()          # NES = 9 buttons; reading fewer drops A
    core = zipfile.ZipFile(bk2).read("Core.bin"); keys = inputs(bk2, nb); mid = len(keys) // 2
    ro, co, state = run(orig, core, keys, save_at=mid)
    if fix_state:
        import importlib.util
        spec = importlib.util.spec_from_file_location("fix_state", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fix_state.py"))
        fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)
    rm, cm, _ = run(mod, fs.fix(core)[0] if fix_state else core, keys, wav=wav)
    res = compare(ro, co, rm, cm)
    if track and state is not None:
        rt, ct, _ = run(mod, core, keys, resume=(state, mid)); tr = compare(ro[mid:], co[mid:], rt, ct, first=mid)
    else: tr = dict(bad=[], bad_frames=0)
    res.update(replay=os.path.basename(bk2), frames=len(keys), tracked=bool(track and state is not None), track_bad=tr["bad"],
               track_bad_frames=tr["bad_frames"], ok=res["bad_frames"] == 0 and tr["bad_frames"] == 0)
    return res

def _job(args):
    orig, mod, bk2, wav_dir, parent, fix_state, track = args
    retro.data.Integrations.add_custom_path(parent)
    wav = os.path.join(wav_dir, os.path.basename(bk2)[:-4] + ".wav") if wav_dir else None
    try: return verify(orig, mod, bk2, wav, fix_state, track)
    except Exception as e: return dict(replay=os.path.basename(bk2), ok=False, error=f"{type(e).__name__}: {e}")

def line(r):
    if "error" in r: return f"{r['replay']}: ERROR {r['error']}"
    tol = ", ".join(f"{k} {lo}-{hi}" for k, (lo, hi, n) in r["tolerated"].items()) or "none"
    s = (f"{r['replay']}: frames={r['frames']} compared={r['compared']} skipped_mid_logic={sum(r['skipped'].values())}"
         f" (outside InitializeMemory: {r['skipped_elsewhere']}) differing_frames={r['bad_frames']}"
         f" state_tracks={r['track_bad_frames'] == 0 if r['tracked'] else 'not checked'} -> {'OK' if r['ok'] else 'FAIL'}\n    tolerated: {tol}")
    for f, a, o, m in (r["bad"] + r["track_bad"])[:8]: s += f"\n    frame {f}: ${a:04X} original ${o:02X} modified ${m:02X}"
    return s

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--jobs", type=int, default=1); p.add_argument("--wav"); p.add_argument("--json"); p.add_argument("--fix-state", action="store_true"); p.add_argument("--track-every", type=int, default=1)
    p.add_argument("orig"); p.add_argument("mod"); p.add_argument("replays", nargs="+")
    a = p.parse_args()
    parent = os.path.dirname(os.path.abspath(a.orig))
    orig, mod = os.path.basename(a.orig.rstrip("/")), os.path.basename(a.mod.rstrip("/"))
    jobs = [(orig, mod, bk2, a.wav, parent, a.fix_state, i % a.track_every == 0) for i, bk2 in enumerate(a.replays)]
    if a.jobs > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(a.jobs) as pool:
            results = []
            for r in pool.imap_unordered(_job, jobs): print(line(r), flush=True); results.append(r)
    else:
        results = []
        for j in jobs: r = _job(j); print(line(r), flush=True); results.append(r)
    bad = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(bad)}/{len(results)} recordings OK")
    if a.json: json.dump(sorted(results, key=lambda r: r["replay"]), open(a.json, "w"), indent=1)
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
