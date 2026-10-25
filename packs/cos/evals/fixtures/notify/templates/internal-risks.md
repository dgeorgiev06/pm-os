---
audience: internal
channel: channels:channel/slack
max_words: 120
fields:
  message: {type: string, required: true}
  risks: {type: list, required: false}
---
{{message}}
{{#risks}}Known risks:
{{risks}}
{{/risks}}
