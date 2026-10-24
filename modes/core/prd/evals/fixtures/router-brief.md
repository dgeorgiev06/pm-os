# Brief: multi-operator staking router (fixture)

Institutional clients (custodians and banks) want to stake SOL across several node operators
through one API, without integrating each operator separately.

- They need a single API for stake, unstake, rewards and reporting.
- If an operator degrades, new stake should route to healthy operators.
- Compliance teams need per-operator exposure reports.
- Start with Solana; Ethereum later.
