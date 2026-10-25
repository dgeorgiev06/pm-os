---
audience: external
channel: channels:channel/email
max_words: 200
fields:
  body: {type: string, required: true}
  support_notes: {type: string, required: false}
---
Subject: Release 2.4 is out
{{body}}
{{#support_notes}}{{support_notes}}{{/support_notes}}
