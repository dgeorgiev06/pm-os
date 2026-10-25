# Release 2.4, ships 2026-10-30

Routing rules are live, and reports no longer lag after a sync.

## New features
- Routing rules can be set per account (STK-412)

## Fixes
- Reports no longer lag after a sync (STK-407)

## Internal
- Refactor of the sync worker (STK-409)

Support: restart the sync worker if reports lag (runbook RB-12).
