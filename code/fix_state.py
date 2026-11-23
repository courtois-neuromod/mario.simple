#!/usr/bin/env python3
"""Rewrite what a savestate carries that simplify_rom.py cannot reach: the PPU
palette, the state of the sound engine, and the part of the screen that is
already drawn.

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

A state saved mid-level also carries the two name tables: the tiles of the
screen that the ROM it was saved on had already drawn.  The simplified ROM
draws a few blocks with other tiles than the original (see METATILE_PATCH,
CASTLE_METATILES and ROPE_OPERANDS in simplify_rom.py): what the original
drew stays on screen until it scrolls away, e.g. the castle next to which a
level starts shows as a wall in the brick colour.  The name-table fix redraws
those cells the way the simplified ROM would.  It needs to know what each
16x16 cell is, and reads it from the game's block buffer in the same state
($0500-$069F): a block the game holds there is redrawn if its tiles changed
(pipe shafts, springboard base); where the game holds nothing, the cell is
decoration, and the tiles that only the castle and the lift ropes use are
blanked.  Only the PPU's memory is touched, never the game's.

The fceumm savestate stores the 32 palette bytes in a chunk keyed "PRAM"
(4-byte key, 4-byte little-endian size 32, data), the 2 KB of CPU RAM in a
chunk keyed "RAM\\0" (size 2048) and the two name tables in a chunk keyed
"NTAR" (size 2048), so the blocks are found structurally, whatever they
currently hold.  Usage:

    fix_state.py IN.state OUT.state [--palette-only | --sound-only | --nametable-only]
"""
import gzip, sys, importlib.util, os
spec = importlib.util.spec_from_file_location("sr", os.path.join(os.path.dirname(os.path.abspath(__file__)), "simplify_rom.py"))
sr = importlib.util.module_from_spec(spec); spec.loader.exec_module(sr)

NEW = bytearray(sum(sr.BG_PAL, []) + sum(sr.SPR_PAL, []))
NEW[16:20] = bytes(sr.PLAYER_PAL[0])          # sprite palette 0 as the game writes it for Mario
NEW = bytes(NEW)
PRAM = b"PRAM" + (32).to_bytes(4, "little")
RAM = b"RAM\0" + (2048).to_bytes(4, "little")
NTAR = b"NTAR" + (2048).to_bytes(4, "little")
SOUND_IDLE = {0xF1: 0, 0xF2: 0, 0xF3: 0,       # square 1, square 2, noise sfx buffers
              0xF4: 0, 0x07B1: 0, 0x07C5: 0,   # area music buffer, event music buffer, saved area music
              0xFB: 0x80}                      # area music queue: Silence, which the engine loads on the next frame
BLANK = 0x24
# metatile id -> (tiles the original ROM draws, tiles the simplified ROM draws), for the metatiles the game keeps in its block buffer
REDRAWN = {(off - sr.MT0) // 4 if off < sr.MT1 else 0x40 + (off - sr.MT1) // 4: (old, new) for off, (old, new) in sr.METATILE_PATCH.items()}
REDRAWN = {mt: v for mt, v in REDRAWN.items() if mt >= (0x10, 0x51)[mt >> 6]}    # the others (ropes) are decoration: not in the block buffer
# tiles that, in a cell where the game holds no block, can only be the end-of-level castle or a lift rope
DECORATION = {0x47, 0x9B, 0x9C, 0x9D, 0x9E, 0xA9, 0xAA, 0xA2, 0xA3}

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

def fix_nametable(data: bytes):
    """Return (data with the name tables redrawn as the simplified ROM draws them, number of 16x16 cells changed)."""
    n = 0; k = data.find(NTAR)
    while k >= 0:
        i = data.rfind(RAM, 0, k); assert i >= 0, "no RAM chunk before the name tables"
        ram = data[i + len(RAM):i + len(RAM) + 2048]; nt = bytearray(data[k + len(NTAR):k + len(NTAR) + 2048])
        for page in range(2):                    # the two block buffers ($0500, $05D0: 13 rows of 16) describe the two name tables
            for row in range(13):
                for col in range(16):
                    held = ram[0x500 + page * 0xD0 + row * 16 + col]
                    at = [page * 0x400 + (4 + 2 * row + dy) * 32 + 2 * col + dx for dx, dy in ((0, 0), (0, 1), (1, 0), (1, 1))]
                    tiles = bytes(nt[a] for a in at)
                    if held in REDRAWN and tiles == REDRAWN[held][0]: new = REDRAWN[held][1]
                    elif held == 0: new = bytes(BLANK if t in DECORATION else t for t in tiles)
                    else: continue
                    if new != tiles:
                        n += 1
                        for a, t in zip(at, new): nt[a] = t
        data = data[:k + len(NTAR)] + bytes(nt) + data[k + len(NTAR) + 2048:]
        k = data.find(NTAR, k + len(NTAR))
    return data, n

def fix(data: bytes, palette=True, sound=True, nametable=True):
    """Return (fixed data, palette chunks rewritten, RAM chunks rewritten, name-table cells redrawn)."""
    np_ = ns = nn = 0
    if nametable: data, nn = fix_nametable(data)          # first: it reads the state as saved
    if palette: data, np_ = fix_palette(data)
    if sound:   data, ns = fix_sound(data)
    return data, np_, ns, nn

if __name__ == "__main__":
    src, dst = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = open(src, "rb").read()
    gz = raw[:2] == b"\x1f\x8b"
    only = [a for a in sys.argv[1:] if a.endswith("-only")]
    data, np_, ns, nn = fix(gzip.decompress(raw) if gz else raw, palette=only in ([], ["--palette-only"]),
                            sound=only in ([], ["--sound-only"]), nametable=only in ([], ["--nametable-only"]))
    open(dst, "wb").write(gzip.compress(data, mtime=0) if gz else data)
    print(f"{src}: {np_} palette chunk(s), {ns} RAM chunk(s) rewritten, {nn} name-table cell(s) redrawn -> {dst}")
