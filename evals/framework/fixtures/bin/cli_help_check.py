#!/usr/bin/env python3
"""Fail if any pmos CLI option lacks help text. Walks the argparse tree from scripts/pmos.py."""
import argparse
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("pmos_cli", Path("scripts/pmos.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["pmos_cli"] = mod
spec.loader.exec_module(mod)
parser = mod.build_parser() if hasattr(mod, "build_parser") else None
if parser is None:
    for name in dir(mod):
        obj = getattr(mod, name)
        if callable(obj) and name.endswith("parser"):
            parser = obj()
            break
if not isinstance(parser, argparse.ArgumentParser):
    sys.exit("could not find the pmos argument parser")

missing = []


def walk(p: argparse.ArgumentParser, path: str) -> None:
    for act in p._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sub in act.choices.items():
                walk(sub, f"{path} {name}")
        elif isinstance(act, argparse._HelpAction):
            continue
        elif act.option_strings and not (act.help and act.help.strip() and act.help != argparse.SUPPRESS):
            missing.append(f"{path} {'/'.join(act.option_strings)}")


walk(parser, "pmos")
if missing:
    print(f"{len(missing)} option(s) without help text:")
    print("\n".join(f"- {m}" for m in missing))
    sys.exit(1)
print("every option has help text")
