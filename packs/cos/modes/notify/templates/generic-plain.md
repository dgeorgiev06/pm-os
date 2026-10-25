---
audience: any
format: plain
max_words: 250
fields:
  subject: {type: string, required: false, max_words: 15}
  body: {type: string, required: true}
---
{{#subject}}Subject: {{subject}}

{{/subject}}{{body}}
