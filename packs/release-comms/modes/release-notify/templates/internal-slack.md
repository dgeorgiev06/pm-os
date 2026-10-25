---
audience: internal
channel: channels:channel/slack
max_words: 150
fields:
  version: {type: string, required: true}
  ship_date: {type: date, required: true}
  changes: {type: list, required: true, min: 1}
  risks: {type: list, required: false}
  support_notes: {type: string, required: false}
---
**{{version}} ships {{ship_date}}**
{{changes}}
{{#risks}}Known risks:
{{risks}}
{{/risks}}
{{#support_notes}}Support: {{support_notes}}{{/support_notes}}
