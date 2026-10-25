---
name: pm-principles-testable-requirements
description: "Principle: Every requirement can be checked by someone other than its author. Read when a role or mode cites pm:testable-requirements, and before reviewing work against it."
kind: principle
check: "Every requirement or acceptance criterion is a testable statement with a number, state or behavior, not an adjective"
---
# Every requirement can be checked by someone other than its author.

Vague requirements turn review into argument and QA into guesswork. 'Fast' becomes 'p95 under 300 ms'; 'handles failover' becomes 'routes new stake away from an operator within one epoch of it failing health checks'.

- Say who or what observes the requirement being met: a test, a dashboard, a report.
