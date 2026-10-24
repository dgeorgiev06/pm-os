## Building the system itself

- "Add a mode for X to pm" → `forge/new-mode`. "Create a pack for Y" → `forge/new-pack`.
- Both stage everything under `outputs/<id>/staged/`, check it, and come back for approval like any
  other change; the Operator then copies the files into `packs/` (`pmos action run`).
- Then tell the PM the exact install command from the result's summary
  (`python scripts/pmos.py pack add packs/<name> [--upgrade] [--approve-grants]`). Don't run it.
