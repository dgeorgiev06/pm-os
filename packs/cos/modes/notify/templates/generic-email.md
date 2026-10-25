---
audience: any
channel: email
max_words: 250
fields:
  subject: {type: string, required: true, max_words: 15}
  body: {type: string, required: true}
---
Subject: {{subject}}

{{body}}
