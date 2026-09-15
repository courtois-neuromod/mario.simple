#!/usr/bin/env python3
"""Rewrite the PPU palette stored inside a savestate so it matches simplify_rom.py.

Savestates (.state files, or Core.bin inside a .bk2) captured mid-level on the
original ROM carry the original PPU palette; the game only rewrites palettes
when a new area loads.  The 26 level states in this repo start on the black
"WORLD x-y" screen and are fine, but mid-level states (Level5-x, Level6-x,
scene-level states) would show original colours until the next area load.

This finds the 32-byte palette block in the (gzip) state and replaces it with
the palette simplify_rom.py installs.  Usage:

    fix_state_palette.py IN.state OUT.state
"""
import gzip, sys, re, importlib.util, os

spec = importlib.util.spec_from_file_location("sr", os.path.join(os.path.dirname(os.path.abspath(__file__)), "simplify_rom.py"))
sr = importlib.util.module_from_spec(spec); spec.loader.exec_module(sr)

ORIG_SETS = [  # BG rows 0-3 then sprite rows 0-3 of the four area palette sets (index 0 of each row is a wildcard)
    "0F 15 12 25 0F 3A 1A 0F 0F 30 12 0F 0F 27 12 0F 22 16 27 18 0F 10 30 27 0F 16 30 27 0F 0F 30 10",
    "0F 29 1A 0F 0F 36 17 0F 0F 30 21 0F 0F 27 17 0F 0F 16 27 18 0F 1A 30 27 0F 16 30 27 0F 0F 36 17",
    "0F 29 1A 09 0F 3C 1C 0F 0F 30 21 1C 0F 27 17 1C 0F 16 27 18 0F 1C 36 17 0F 16 30 27 0F 0C 3C 1C",
    "0F 30 10 00 0F 30 10 00 0F 30 16 00 0F 27 17 00 0F 16 27 18 0F 1C 36 17 0F 16 30 27 0F 00 30 10",
]
def pattern(s):
    b = bytes.fromhex(s.replace(" ", "")); out = b""
    for i, x in enumerate(b):
        wild = i % 4 == 0 or i < 4 or 12 <= i < 20 or (i % 4 == 3 and i < 16)
        out += b"." if wild else re.escape(bytes([x]))
    return out
# Wildcards: every index-0 byte, BG row 0 (snow/mushroom variants rewrite it), BG index 3 and all of
# BG row 3 (the palette-3 rotation), sprite row 0 (varies with Mario's state).  BG rows 1-2 and sprite
# rows 1-3 identify the area palette set.
PATS = [re.compile(pattern(s), re.S) for s in ORIG_SETS]
NEW = bytes(sum(sr.BG_PAL, []) + sum(sr.SPR_PAL, []))

def fix(data: bytes):
    n = 0
    for pat in PATS:
        for m in pat.finditer(data):
            i = m.start(); block = bytearray(data[i:i+32])
            for k in range(32):
                if k % 4 == 0: continue            # keep stored index-0 bytes
                block[k] = NEW[k]
            block[17:20] = bytes(sr.PLAYER_PAL[0][1:])  # Mario row
            data = data[:i] + bytes(block) + data[i+32:]; n += 1
    return data, n

if __name__ == "__main__":
    src, dst = sys.argv[1:3]
    raw = open(src, "rb").read()
    gz = raw[:2] == b"\x1f\x8b"
    data = gzip.decompress(raw) if gz else raw
    data, n = fix(data)
    open(dst, "wb").write(gzip.compress(data) if gz else data)
    print(f"{src}: {n} palette block(s) rewritten -> {dst}")
