#!/usr/bin/env python3
"""Rewrite what a savestate carries that simplify_rom.py cannot reach: the PPU
palette and the state of the sound engine.

Savestates (.state files, or Core.bin inside a .bk2) carry the PPU palette of
the moment they were captured, and the game only rewrites palettes when a new
area loads.  A state saved on the "WORLD x-y" screen therefore shows that
screen with the stored backdrop and Mario colours, and a state saved
mid-level shows the whole level with the stored palette until the next area
change.  This replaces the stored palette with the one simplify_rom.py
installs, backdrop included, so that a run starts with the same colours it
continues with.

A state saved mid-level also carries the music that was playing (which tune,
where in its data).  On the simplified ROM the engine would go on reading the
original tune from that point until the current section ends.  The sound fix
clears the sound-effect and music buffers and queues "Silence", which the
engine turns into a silent, idle state on the first frame (it also writes
silence to the square and triangle channels).  Game logic never reads these
bytes (see simplify_rom.py, "sound"), so the run itself is unchanged.

The fceumm savestate stores the 32 palette bytes in a chunk keyed "PRAM"
(4-byte key, 4-byte little-endian size 32, data) and the 2 KB of CPU RAM in
a chunk keyed "RAM\\0" (size 2048), so both blocks are found structurally,
whatever they currently hold.  Usage:

    fix_state.py IN.state OUT.state [--palette-only | --sound-only]
"""
import gzip, sys, importlib.util, os
spec = importlib.util.spec_from_file_location("sr", os.path.join(os.path.dirname(os.path.abspath(__file__)), "simplify_rom.py"))
sr = importlib.util.module_from_spec(spec); spec.loader.exec_module(sr)

NEW = bytearray(sum(sr.BG_PAL, []) + sum(sr.SPR_PAL, []))
NEW[16:20] = bytes(sr.PLAYER_PAL[0])          # sprite palette 0 as the game writes it for Mario
NEW = bytes(NEW)
PRAM = b"PRAM" + (32).to_bytes(4, "little")
RAM = b"RAM\0" + (2048).to_bytes(4, "little")
SOUND_IDLE = {0xF1: 0, 0xF2: 0, 0xF3: 0,       # square 1, square 2, noise sfx buffers
              0xF4: 0, 0x07B1: 0, 0x07C5: 0,   # area music buffer, event music buffer, saved area music
              0xFB: 0x80}                      # area music queue: Silence, which the engine loads on the next frame

def fix_palette(data: bytes):
    """Return (data with every PRAM palette chunk rewritten, number of chunks)."""
    n = 0; i = data.find(PRAM)
    while i >= 0:
        j = i + len(PRAM)
        assert all(b < 0x40 for b in data[j:j+32]), "PRAM chunk does not look like a palette"
        data = data[:j] + NEW + data[j+32:]; n += 1
        i = data.find(PRAM, j)
    return data, n

def fix_sound(data: bytes):
    """Return (data with the sound engine idle in every RAM chunk, number of chunks)."""
    n = 0; i = data.find(RAM)
    while i >= 0:
        j = i + len(RAM); ram = bytearray(data[j:j+2048])
        for a, v in SOUND_IDLE.items(): ram[a] = v
        data = data[:j] + bytes(ram) + data[j+2048:]; n += 1
        i = data.find(RAM, j)
    return data, n

def fix(data: bytes, palette=True, sound=True):
    """Return (fixed data, palette chunks rewritten, RAM chunks rewritten)."""
    np_ = ns = 0
    if palette: data, np_ = fix_palette(data)
    if sound:   data, ns = fix_sound(data)
    return data, np_, ns

if __name__ == "__main__":
    src, dst = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = open(src, "rb").read()
    gz = raw[:2] == b"\x1f\x8b"
    data, np_, ns = fix(gzip.decompress(raw) if gz else raw,
                        palette="--sound-only" not in sys.argv, sound="--palette-only" not in sys.argv)
    open(dst, "wb").write(gzip.compress(data) if gz else data)
    print(f"{src}: {np_} palette chunk(s), {ns} RAM chunk(s) rewritten -> {dst}")
