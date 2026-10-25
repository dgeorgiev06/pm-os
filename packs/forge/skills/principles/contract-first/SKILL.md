---
name: forge-principles-contract-first
description: "Principle: Write the contract and the golden task before the steps. Read when a role or mode cites forge:contract-first, and before reviewing work against it."
kind: principle
check: "The mode has concrete accepts and returns, an approval rule, and at least one golden task whose expectations a reviewer can verify"
---
# Write the contract and the golden task before the steps.

The contract is what makes a mode composable: the CoS and other modes only ever see accepts, returns and approval. Writing the golden task first forces a clear definition of done, and the steps then exist to satisfy it.

- If you can't write the golden task's expectations, the mode's job isn't clear yet. Ask.
- Mark optional inputs with a trailing ?; never make a field optional just to avoid deciding.
