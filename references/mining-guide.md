# Mining guide: from extracted text to evidence cards

You read approved, already-redacted text from `.work/text/` (listed in a batch file) and write **evidence cards**: small structured facts about what the owner did, decided, learned and was told. Write them as JSON Lines to the output file you were given (e.g. `.work/evidence/batch-20261117-003.jsonl`). If you were spawned as a worker, reply only with "N cards from M items".

Read only the files listed in your batch. Never open the person's original files; the text files are all you need.

## Each text file

Starts with a header, then `---`, then the text:

```
ITEM: f-0123456789ab
SOURCE: documents
TITLE: rfc-route-cache.docx
PATH: ~/Documents/Work/Acme/rfc-route-cache.docx
DATE: 2023-03-14
AUTHORED_BY_OWNER: yes | no | unknown
DURING_ROLE_AT: Acme Corp        (when the date falls in a known job)
```

Put the `ITEM` id in every card you take from that file. Use dates written inside the document over `DATE` (the file's modified date) when they exist.

## Whose experience is it?

Mine only what the **owner** did, decided, felt or was told.

- Strong signs it's the owner's: `AUTHORED_BY_OWNER: yes`, first person in a personal doc (journal, brag doc, self-review, own notes), the owner named as author / DRI / owner, "feedback for <owner>", the owner's resume.
- Not the owner's experience: articles, books, course notes, templates, interview-prep material with sample answers, other people's resumes. Skip them (they should have been scoped out; if one slipped through, write nothing).
- Docs written by others where the owner's part isn't visible: at most a `project` card with `"my_role_confidence": "unknown"`, and only if the project shows up elsewhere.
- Feedback the owner wrote *about* others (as a manager or peer) is evidence of the owner's management practice: write a `leadership` card about what the owner did ("coached a report on prioritization"), never the other person's name or private details.

## What to extract

Card `type` is one of: `role`, `project`, `decision`, `achievement`, `challenge`, `conflict`, `mistake`, `feedback`, `leadership`, `collaboration`, `learning`, `motivation`, `skill`, `other`.

Don't miss these - they're what make an extended resume deeper than a resume:

- **Decisions** with the options considered and why one won. Look for "options", "alternatives", "trade-off", "pros/cons", "we went with", "decided", RFC/ADR structure.
- **Outcomes with numbers.** Copy numbers exactly as written, with units and baselines ("p99 1.2s → 300ms"). Never compute, round, combine or estimate a number.
- **Friction:** disagreements, pushback, escalations, a difficult working relationship, reprioritizations, scope cuts.
- **Things that went wrong:** incidents, slips, missed deadlines, wrong bets, mistakes, postmortem action items.
- **Feedback received:** from reviews, 1:1s, peers. Quote briefly.
- **Motivation and reflection:** what they want next, why they joined or left, what energizes or drains them.
- **Roles:** from resumes and similar: employer, title, dates, team, scope. Older resume versions may list roles or projects the newest one dropped - capture those.

One card per distinct thing. A design doc might give one `project`, two `decision` and one `challenge` card.

## Card format

One JSON object per line. Omit fields you don't have; never fill a field with a guess.

```json
{"item": "f-0123456789ab", "type": "decision", "summary": "Pushed for a 6-week dual-write migration over a weekend cutover so finance never had a reconciliation gap.", "date": "2023-03", "org": "Acme Corp", "role": "Senior Software Engineer", "project": "Ledger migration", "situation": "Moving 40M ledger rows to a new store; finance closes books monthly.", "actions": ["wrote the RFC comparing both options", "got finance to sign off on the plan"], "decision": {"question": "How to cut over", "options": ["weekend big-bang cutover", "6-week dual-write"], "chosen": "6-week dual-write", "why": "finance couldn't tolerate a reconciliation gap", "tradeoffs": "roughly doubled engineering effort"}, "outcome": "Cutover with zero downtime.", "metrics": ["reconciliation errors ~40/day → 0"], "people": ["finance lead", "my manager"], "quote": "I pushed for (b) even though it doubled the work", "my_role_confidence": "explicit", "sensitivity": "internal", "tags": ["long-term-thinking", "risk", "stakeholder-management"]}
```

| Field | Notes |
|---|---|
| `item` | **required** - the ITEM id from the header (use `user-notes` for facts the person told you directly) |
| `type` | **required** |
| `summary` | **required** - one or two plain, specific sentences |
| `date` | when it happened: `2023`, `2023-03` or `2023-03-14` |
| `org`, `role`, `project` | as written; attach to a role from the skeleton when you can |
| `situation`, `actions`, `outcome` | the STAR raw material; `actions` = what the owner personally did |
| `decision` | for decision cards: `question`, `options`, `chosen`, `why`, `tradeoffs` |
| `metrics` | exact numbers as written |
| `people` | **roles, never names**: "staff engineer on payments", "my manager", "a PM" |
| `feedback_from` | for feedback cards: `manager`, `peer`, `report`, `customer`, `self` |
| `quote` | ≤ 30 words verbatim; replace any names with `[name]` |
| `my_role_confidence` | `explicit`, `inferred` or `unknown` |
| `sensitivity` | `none`, `internal` (internal project/team names) or `confidential` (unreleased products, customer names, financials, security issues, legal matters, anything marked confidential) |
| `tags` | from: problem-solving, technical-depth, innovation, ownership, leadership, influence, conflict, collaboration, cross-functional, communication, prioritization, execution, deadline, ambiguity, risk, data-driven, customer-focus, mentoring, hiring, growth, resilience, failure, feedback, long-term-thinking, stakeholder-management, motivation |

## Privacy

- Leave `[REDACTED ...]`, `[email]` and `[phone]` markers as they are; never try to reconstruct them.
- Don't copy anyone's personal details (health, family, finances) into cards, including the owner's, unless it's directly about their career (e.g. "took leave and came back to a reorg" is fine; the medical reason is not).
- Colleagues appear only as roles.

## Long or messy files

- Over ~40k characters: skim headings first, then read the sections that involve the owner.
- Daily notes and journals: each dated entry can be its own card; fold a repeated theme into one card ("recurring friction with the design lead over scope, Mar-May 2022").
- Slides: speaker notes often hold the reasoning.
