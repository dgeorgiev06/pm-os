## Building the system itself

- "Add a mode for X to pm" → `forge/new-mode`; "create a pack for Y" → `forge/new-pack`. Both stage
  their files under `outputs/<id>/staged/` and come back for approval.
- Once applied, give the PM the install command in the result's summary
  (`python scripts/pmos.py pack add packs/<name> [--upgrade] [--approve-grants]`). Don't run it.
