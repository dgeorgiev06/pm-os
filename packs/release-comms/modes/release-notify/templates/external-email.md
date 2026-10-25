---
audience: external
channel: channels:channel/email
max_words: 250
fields:
  version: {type: string, required: true}
  ship_date: {type: date, required: true}
  headline: {type: string, required: true, max_words: 12}
  changes: {type: list, required: true, min: 1}
  action: {type: string, required: false}   # one full sentence: what the reader must do, or that nothing is needed
  contact: {type: string, required: true}
---
Subject: {{version}} is out: {{headline}}

{{headline}}. Released {{ship_date}}.

What changed:
{{changes}}
{{#action}}{{action}}
{{/action}}Questions? {{contact}}
