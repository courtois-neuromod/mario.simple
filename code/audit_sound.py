#!/usr/bin/env python3
"""Check what a simplified ROM plays against the sound legend of simplify_rom.py.

The fceumm savestate holds the registers of the sound chip (chunk "PSG": the
16 bytes written to $4000-$400F; "ENCH": the channel enables of $4015;
"LEN0".."LEN3": the length counters; "TRIC": the triangle's linear counter),
so what each of the four channels is doing on a frame can be read exactly,
without analysing audio.  This tool replays recordings on the simplified ROM
and checks, on every frame where the game is idle (see verify_replays.py):

  cues     when a sound effect starts (the engine's buffer of that channel,
           $F1-$F3, takes a new value), the channel must be set to the pitch,
           duty and volume that CUES gives for the lowest queued bit, stay
           audible with those values on every frame of the effect, and the
           effect must last the number of frames CUES gives, unless another
           effect of the same channel replaces it, the death tune stops it
           (as in the original) or an area change wipes the engine's memory;
  silence  a channel may only be audible while something is playing on it:
           square 1 and noise during an effect, square 2 during an effect or
           a tune, the triangle never;
  tunes    while a tune plays (death, game over, level clear, time warning,
           star-power hum), square 2 may only sound the notes TUNES gives
           for it, and the area tunes must be silent.  Every event tune that
           starts must sound its notes for their number of frames, unless an
           effect was playing on square 2 meanwhile (an effect interrupts a
           tune note, as in the original): those are counted.

It also counts how often each cue and tune occurred, i.e. the coverage of the
set of recordings, and two things that can happen to a cue because it writes
its channel once, where the original effects rewrite it on every frame.  The
music routine can write the same channel, which cuts off a cue that is
sounding, or silences one that starts on that frame: it did so on both
squares when a tune ended and on the noise channel on every (silent) drum
beat of the star-power tune, until simplify_rom.py changed those two places
(SOUND_SITES, TUNE_END), and the count is kept as a regression check.  And a
tone can be left over for one frame at the start of a recording or across an
area change.

Usage:
    audit_sound.py [--jobs N] [--json OUT] MOD_INTEGRATION_DIR REPLAY.bk2 [...]

Exit status 1 if anything unexpected was played.
"""
import os, sys, json, zipfile, argparse, importlib.util
from collections import Counter
try:
    import stable_retro as retro
except ImportError:
    import retro

HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sr, fs = _load("simplify_rom"), _load("fix_state")

IDLE = (0x8057, 0xFF)
CHANNELS = {1: ("square 1", 0x00), 2: ("square 2", 0x04), 3: ("noise", 0x0C)}       # sfx channel -> name, first register (offset from $4000)
EVENT_TUNES = {0x01: "death", 0x02: "game over", 0x04: "victory", 0x08: "castle clear", 0x20: "level clear", 0x40: "time warning"}
AREA_TUNES = {0x01: "ground", 0x02: "water", 0x04: "underground", 0x08: "castle", 0x10: "cloud", 0x20: "pipe intro", 0x40: "star power", 0x80: "silence"}
NOTE_OF = {v: k for k, v in sr.NOTE.items()}

class State:
    def __init__(self, raw): self.raw = raw; self.at = {}
    def get(self, name, size):
        if name not in self.at:
            i = self.raw.find(name + size.to_bytes(4, "little")); assert i >= 0, name; self.at[name] = i + 8
        return self.raw[self.at[name]:self.at[name] + size]

def periods(rom_path):
    """pitch value (index of the game's FreqRegLookupTbl, $FF00) -> timer period."""
    rom = open(rom_path, "rb").read(); t = sr._cpu(0xFF00)
    return {p: (rom[t + p] & 7) << 8 | rom[t + p + 1] for p in range(0, 0x66, 2)}

MUSIC_SILENCE = {1: 0x90, 2: 0x90, 3: 0x10}       # what the unchanged music routine writes to a channel's control register when it silences it
# Event tunes: frames of sound each one must give (its notes, rests excluded), and the frames those notes span from its start
TUNE_SOUND = {name: sum(n for note, n in notes if note != "REST") for _, (name, _, notes) in sr.TUNES.items()}
TUNE_SPAN = {name: sum(n for _, n in notes[:max(i for i, (note, _) in enumerate(notes) if note != "REST") + 1]) for _, (name, _, notes) in sr.TUNES.items()}

def audit(game, bk2, period):
    env = retro.make(game, state=retro.State.NONE, inttype=retro.data.Integrations.CUSTOM_ONLY, use_restricted_actions=retro.Actions.ALL, render_mode="rgb_array")
    env.initial_state = fs.fix(zipfile.ZipFile(bk2).read("Core.bin"))[0]; env.reset()
    m = retro.Movie(bk2); m.step()
    note_of_period = {period[v]: k for k, v in sr.NOTE.items() if k != "REST"}
    expected_notes = {name: {n for n, _ in notes if n != "REST"} for _, (name, _, notes) in sr.TUNES.items()}
    expected_notes["star power"] = {n for n, _ in sr.HUM}
    cues, bad, known, tunes, heard, examples, starts = Counter(), Counter(), Counter(), Counter(), Counter(), [], Counter()
    played, inst = Counter(), None                               # event tunes: how each one that started was heard; the one in progress
    def finish(i, ended=False):
        want = TUNE_SOUND[i["tune"]]
        if i["heard"] == want: how = "in full"
        elif f - i["start"] < TUNE_SPAN[i["tune"]]: how = "cut by the end of the recording" if ended else "replaced by another tune"
        elif i["effect"]: how = ("not played" if not i["heard"] else "shortened") + ": an effect was playing on square 2"
        elif i["skipped"]: how = "frames not audited (pause, or an area loading)"
        else: how = f"{i['heard']} frames of sound, expected {want}"; flag(f"tune '{i['tune']}': {how}")
        played[(i["tune"], how)] += 1
    def flag(what):
        bad[(what,)] += 1
        if len(examples) < 20: examples.append((f, what))
    during = lambda area: " (star-power tune)" if area == 0x40 else ""
    playing = {c: None for c in CHANNELS}                       # channel -> dict(name, want, start, cnt, buf, lag, ctrl, pitch, cut)
    f = frames = 0; disturbed = tune_start = -99; last_event = 0; skipped = 0
    def close(c, how):
        cur = playing[c]; got = f - cur["start"]; playing[c] = None
        if cur.get("how"): cues[(cur["name"], cur["how"])] += 1
        elif how != "ended" or cur["want"] <= got <= cur["want"] + cur["lag"]: cues[(cur["name"], "full length" if how == "ended" else how)] += 1
        elif f - tune_start <= 1: cues[(cur["name"], "cut by a tune")] += 1          # the death tune stops the effects, as in the original
        elif f - disturbed <= 2: cues[(cur["name"], "cut by an area change")] += 1   # the game wipes its memory, the engine's included
        else: cues[(cur["name"], "ended")] += 1; flag(f"{cur['name']}: lasted {got} frames, expected {cur['want']}")
    while m.step():
        env.step([m.get_key(i, 0) for i in range(env.num_buttons)]); f += 1
        st = State(env.em.get_state())
        if (int.from_bytes(st.get(b"PC\0\0", 2), "little"), st.get(b"S\0\0\0", 1)[0]) != IDLE:      # the frame's logic is not finished:
            disturbed = f                                                                         # an area is loading, and the engine may miss a frame
            for cur in playing.values():
                if cur: cur["lag"] += 1
            if inst: inst["skipped"] = True
            continue
        r = env.get_ram(); frames += 1
        if r[0x772] != 3: disturbed = f
        if r[0x776] & 1:                                         # game paused: the pause jingle is the original one
            if inst: inst["skipped"] = True
            continue
        psg, enabled = st.get(b"PSG\0", 16), st.get(b"ENCH", 1)[0]
        length = [int.from_bytes(st.get(b"LEN%d" % k, 4), "little") for k in range(4)]
        square = lambda k: bool(enabled >> k & 1 and length[k] and (psg[4 * k] & 0x0F or not psg[4 * k] & 0x10))
        audible = {"square 1": square(0), "square 2": square(1), "noise": bool(enabled & 8 and length[3] and (psg[0x0C] & 0x0F or not psg[0x0C] & 0x10)),
                   "triangle": bool(enabled & 4 and length[2] and st.get(b"TRIC", 1)[0])}
        area, event = int(r[0xF4]), int(r[0x7B1])
        if event and not last_event: tune_start = f
        last_event = event
        # ---- cues
        for c, (cname, reg) in CHANNELS.items():
            p = sr.CHANNEL[c]; buf, cnt = int(r[p["BUF"]]), int(r[p["CNT"]]); cur = playing[c]
            started = buf and (cur is None or cnt >= cur["cnt"] or buf != cur["buf"])   # the length counter went back up: the cue was queued again
            if cur is not None and (started or not buf): close(c, "replaced by another cue" if started else "ended")
            if started:
                bit = (buf & -buf).bit_length() - 1; name = sr.SFX_BITS[c][bit]; frames_, pitch, ctrl = sr.CUES[name] if name else sr.SILENT
                label = name or f"(silent: bit {bit} of {cname})"
                playing[c] = dict(name=label, want=frames_, start=f, cnt=cnt, buf=buf, lag=0, ctrl=ctrl if name else None, pitch=pitch, cut=False)
                if name: starts[(label, during(area).strip(" ()"))] += 1
                if name and psg[reg] == MUSIC_SILENCE[c]:
                    playing[c]["cut"] = True; known[(f"{label}: made no sound, the music routine wrote the same channel on the frame it started" + during(area),)] += 1
                elif name:
                    if psg[reg] != ctrl: flag(f"{label}: control byte ${psg[reg]:02X}, expected ${ctrl:02X}")
                    if c == 3 and psg[0x0E] & 0x0F != pitch: flag(f"{label}: noise period {psg[0x0E] & 0x0F}, expected {pitch}")
                    if c != 3 and ((psg[reg + 3] & 7) << 8 | psg[reg + 2]) != period[pitch]:
                        flag(f"{label}: timer period {(psg[reg + 3] & 7) << 8 | psg[reg + 2]}, expected {period[pitch]} ({NOTE_OF.get(pitch)})")
                if cnt != frames_: flag(f"{label}: length counter {cnt}, expected {frames_}")
            cur = playing[c]
            if cur is not None:
                cur["cnt"] = cnt
                if cur["ctrl"] is None:
                    if audible[cname]: flag(f"{cname} audible during {cur['name']}")
                elif not cur["cut"] and f > cur["start"]:                                       # the cue must still sound, with its own registers
                    own = psg[reg] == cur["ctrl"] and ((psg[0x0E] & 0x0F) == cur["pitch"] if c == 3 else ((psg[reg + 3] & 7) << 8 | psg[reg + 2]) == period[cur["pitch"]])
                    if not (own and audible[cname]):
                        cur["cut"] = True
                        if own and f - tune_start <= 1: cur["how"] = "cut by a tune"             # the death tune stops the effects, as in the original (which leaves the buffer of square 2 set)
                        elif psg[reg] == MUSIC_SILENCE[c]: known[(f"{cur['name']}: cut short, the music routine wrote the same channel while it sounded" + during(area),)] += 1
                        else: flag(f"{cur['name']}: stopped sounding on frame {f - cur['start'] + 1} of {cur['want']} (control byte ${psg[reg]:02X})")
            if audible[cname] and not buf and not (c == 2 and (area or event)):
                if f <= 2 or f - disturbed <= 2: known[(f"{cname}: a tone left over for a frame (from the initial state, or across an area change)",)] += 1
                else: flag(f"{cname} audible with no effect" + (" or tune" if c == 2 else ""))
        if audible["triangle"]: flag("triangle audible")
        # ---- tunes
        tune = EVENT_TUNES.get(event) if event else (AREA_TUNES.get(area) if area else None)
        if event and tune is None: tune = f"event ${event:02X}"
        if inst and inst["event"] != event: finish(inst); inst = None                        # ---- event tunes: did the notes of this one sound?
        if event and inst is None and tune in TUNE_SOUND: inst = dict(event=event, tune=tune, start=f, heard=0, effect=False, skipped=False)
        if inst and f - inst["start"] < TUNE_SPAN[tune]:
            if r[0xF2]: inst["effect"] = True
            elif audible["square 2"]: inst["heard"] += 1
        if tune:
            tunes[tune] += 1
            if audible["square 2"] and not r[0xF2]:
                per = (psg[7] & 7) << 8 | psg[6]; note = note_of_period.get(per, f"period {per}"); heard[(tune, note)] += 1
                if note not in expected_notes.get(tune, set()): flag(f"tune '{tune}': square 2 sounds {note}, expected {sorted(expected_notes.get(tune, set())) or 'silence'}")
    for c in CHANNELS:
        if playing[c] is not None: cues[(playing[c]["name"], "cut by the end of the recording")] += 1
    if inst: finish(inst, ended=True)
    env.close()
    j = lambda c: [[list(k), n] for k, n in c.most_common()]
    return dict(replay=os.path.basename(bk2), frames=f, audited=frames, cues=j(cues), bad=j(bad), known=j(known), starts=j(starts),
                tunes=j(Counter({(k,): n for k, n in tunes.items()})), heard=j(heard), played=j(played), examples=examples)

def _job(args):
    parent, game, bk2 = args
    retro.data.Integrations.add_custom_path(parent)
    try: return audit(game, bk2, periods(os.path.join(parent, game, "rom.nes")))
    except Exception as e:
        import traceback; return dict(replay=os.path.basename(bk2), error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

def report(results, out=sys.stdout):
    p = lambda *a: print(*a, file=out)
    tot = {k: Counter() for k in ("cues", "bad", "known", "tunes", "heard", "starts", "played")}; frames = audited = 0; errors = []
    for r in results:
        if "error" in r: errors.append(r); continue
        frames += r["frames"]; audited += r["audited"]
        for k in tot:
            for key, n in r[k]: tot[k][tuple(key)] += n
    p(f"frames replayed {frames}, audited {audited}")
    p("\n== cues: times each one started, and how it ended")
    per = {}
    for (name, how), n in tot["cues"].items(): per.setdefault(name, Counter())[how] += n
    for name in sorted(per, key=lambda n: -sum(per[n].values())):
        legend = sr.CUES.get(name); desc = ""
        if legend: desc = f"{legend[0]:3d} frames, " + (f"{NOTE_OF.get(legend[1], legend[1])}" if name not in ("brick", "flame") else f"noise {legend[1]}")
        p(f"   {name:34s} x{sum(per[name].values()):<8d} {desc:22s} " + ", ".join(f"{how} {n}" for how, n in per[name].most_common()))
    p("\n== tunes: frames during which each one was active, and the notes heard on square 2")
    for (tune,), n in tot["tunes"].most_common():
        notes = ", ".join(f"{note} ({k} frames)" for (t, note), k in sorted(tot["heard"].items()) if t == tune) or "silent"
        p(f"   {tune:14s} {n:9d} frames   {notes}")
    p("\n== event tunes: how the notes of each one that started were heard")
    per = {}
    for (tune, how), n in tot["played"].items(): per.setdefault(tune, Counter())[how] += n
    for tune in sorted(per, key=lambda t: -sum(per[t].values())):
        p(f"   {tune:14s} x{sum(per[tune].values()):<6d} {TUNE_SOUND[tune]:3d} frames of sound   " + ", ".join(f"{how} {n}" for how, n in per[tune].most_common()))
    p(f"\n== known side effects of writing a channel once per cue: {sum(tot['known'].values())}")
    for (what,), n in tot["known"].most_common(): p(f"   x{n:<8d} {what}")
    star = Counter({name: n for (name, when), n in tot["starts"].items() if when})
    if star: p("   cues that started during the star-power tune: " + ", ".join(f"{name} x{n}" for name, n in star.most_common()))
    nbad = sum(tot["bad"].values())
    p(f"\n== unexpected: {nbad}")
    for (what,), n in tot["bad"].most_common(40): p(f"   x{n:<8d} {what}")
    for r in errors: p(f"ERROR {r['replay']}: {r['error']}")
    return nbad + len(errors)

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--jobs", type=int, default=1); p.add_argument("--json"); p.add_argument("mod"); p.add_argument("replays", nargs="+")
    a = p.parse_args()
    parent, game = os.path.dirname(os.path.abspath(a.mod)), os.path.basename(a.mod.rstrip("/"))
    jobs = [(parent, game, bk2) for bk2 in a.replays]
    if a.jobs > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(a.jobs) as pool: results = list(pool.imap_unordered(_job, jobs))
    else: results = [_job(j) for j in jobs]
    if a.json: json.dump(results, open(a.json, "w"))
    sys.exit(1 if report(results) else 0)

if __name__ == "__main__":
    main()
