#!/usr/bin/env python3
"""Exit 0 if text A first appears before text B on stdin.  before.py A B"""
import sys

text = sys.stdin.read()
a, b = sys.argv[1], sys.argv[2]
ia, ib = text.find(a), text.find(b)
if ib == -1:
    sys.exit(f"'{b}' not found")
if ia == -1:
    sys.exit(f"'{a}' not found")
if ia > ib:
    sys.exit(f"'{a}' (offset {ia}) comes after '{b}' (offset {ib})")
print(f"ok: '{a}' at {ia} before '{b}' at {ib}")
