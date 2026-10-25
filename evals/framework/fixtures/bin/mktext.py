#!/usr/bin/env python3
"""Write a component file (SKILL.md, agent) with a known number of body words, for the lint cases.

  mktext.py FILE WORDS [--front KEY=VALUE ...] [--code N] [--sentence N] [--append]

The body is a heading plus WORDS words of distinct filler in sentences of --sentence words (default
6); --code adds a fenced block of N words (the lint doesn't count it). Frontmatter gets a
description unless --append (then only the words are appended to FILE).
"""
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("file")
p.add_argument("words", type=int)
p.add_argument("--front", action="append", default=[], help="KEY=VALUE frontmatter line")
p.add_argument("--code", type=int, default=0)
p.add_argument("--sentence", type=int, default=6)
p.add_argument("--append", action="store_true")
p.add_argument("--seed", default="w", help="prefix of the generated words (distinct texts per seed)")
a = p.parse_args()

words = [f"{a.seed}{i}x" for i in range(a.words - (0 if a.append else 2))]
sentences = [" ".join(words[i:i + a.sentence]).capitalize() + "." for i in range(0, len(words), a.sentence)]
body = " ".join(sentences)
code = ("\n\n```\n" + " ".join(f"c{i}" for i in range(a.code)) + "\n```\n") if a.code else ""
f = Path(a.file)
f.parent.mkdir(parents=True, exist_ok=True)
if a.append:
    f.write_text(f.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + body + "\n" + code, encoding="utf-8")
else:
    front = ['description: "Fixture text for the lint cases."', *[x.replace("=", ": ", 1) for x in a.front]]
    f.write_text("---\n" + "\n".join(front) + "\n---\n# Fixture text\n\n" + body + "\n" + code, encoding="utf-8")
print(f"wrote {f}")
