#!/usr/bin/env python3
"""Rewrite the PPU palette stored inside a savestate so it matches simplify_rom.py.

Savestates (.state files, or Core.bin inside a .bk2) carry the PPU palette of
the moment they were captured, and the game only rewrites palettes when a new
area loads.  A state saved on the "WORLD x-y" screen therefore shows that
screen with the stored backdrop and Mario colours, and a state saved
mid-level shows the whole level with the stored palette until the next area
change.  This replaces the stored palette with the one simplify_rom.py
installs, backdrop included, so that a run starts with the same colours it
continues with.

The fceumm savestate stores the 32 palette bytes in a chunk keyed "PRAM"
(4-byte key, 4-byte little-endian size 32, data), so the block is found
structurally, whatever palette it currently holds.  Usage:

    fix_state_palette.py IN.state OUT.state
"""
import gzip, sys, importlib.util, os

spec = importlib.util.spec_from_file_location("sr", os.path.join(os.path.dirname(os.path.abspath(__file__)), "simplify_rom.py"))
sr = importlib.util.module_from_spec(spec); spec.loader.exec_module(sr)

NEW = bytearray(sum(sr.BG_PAL, []) + sum(sr.SPR_PAL, []))
NEW[16:20] = bytes(sr.PLAYER_PAL[0])          # sprite palette 0 as the game writes it for Mario
NEW = bytes(NEW)
CHUNK = b"PRAM" + (32).to_bytes(4, "little")

def fix(data: bytes):
    """Return (data with every PRAM palette chunk rewritten, number of chunks)."""
    n = 0; i = data.find(CHUNK)
    while i >= 0:
        j = i + len(CHUNK)
        assert all(b < 0x40 for b in data[j:j+32]), "PRAM chunk does not look like a palette"
        data = data[:j] + NEW + data[j+32:]; n += 1
        i = data.find(CHUNK, j)
    return data, n

if __name__ == "__main__":
    src, dst = sys.argv[1:3]
    raw = open(src, "rb").read()
    gz = raw[:2] == b"\x1f\x8b"
    data, n = fix(gzip.decompress(raw) if gz else raw)
    if n != 1: print(f"warning: {n} palette chunks found in {src}", file=sys.stderr)
    open(dst, "wb").write(gzip.compress(data) if gz else data)
    print(f"{src}: {n} palette chunk(s) rewritten -> {dst}")
