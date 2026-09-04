# Literature record template

Copy this file per external source, named `research/literature/<short-slug>.md`.

```markdown
# <Title>

- **URL / DOI**: <link>
- **Retrieved**: <YYYY-MM-DD>
- **Claim it supports**: <one sentence — what hypothesis/experiment this backs>
- **Verification method**: <WebFetch | WebSearch | training-data recall (UNVERIFIED)>
- **Verification note**: <if training-data recall, say so explicitly and flag
  as unverified; if WebFetch/WebSearch, note what was actually fetched/found>
```

Never fabricate a citation. If a claim is only recalled from training data
and has not been checked live this session, mark it `UNVERIFIED` and do not
present it with the same confidence as a fetched source.

Empty at Phase C seed time — see `research/memory/open_questions.md` for why
(no live LLM key to drive literature-grounded hypothesis generation yet).
