---
name: pm-product-staking-prd
description: Product-specific guidance for PRDs on institutional staking products (custodians, banks, financial institutions; Ethereum and Solana). Use with domain-prd-structure for any staking PRD.
---
# Staking PRD guidance

Replace this placeholder with your existing staking PRD skill. Keep the frontmatter.

Starter checklist until then:

- **Personas**: custodian operations, bank product owner, compliance / risk reviewer, client engineer integrating the API.
- **Chain specifics**: state which chains (Ethereum, Solana) and any per-chain differences in stake,
  unstake, rewards timing and slashing exposure.
- **Operator model**: single vs multi-operator; what happens when an operator degrades or is removed.
- **Reporting**: rewards, exposure per operator, audit trail — what compliance needs and how often.
- **Controls**: approvals, limits, segregation of duties for institutional workflows.
