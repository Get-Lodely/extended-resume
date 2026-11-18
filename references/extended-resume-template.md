# Extended resume template

Write `extended-resume.md` in the output folder with this structure. Work from `.work/evidence_index.md`; pull full cards with `evidence_tool.py show E-xxxxxx` when you need the detail. Cite cards as `[E-xxxxxx]` after each fact. Mark anything not stated outright as *(inferred)*. Where a number is missing, write `[ADD METRIC: what]` rather than estimating.

The point of this document is depth: the reasoning, alternatives, tradeoffs, setbacks and feedback that a normal resume drops. Keep the decision log rich.

```markdown
# Extended Resume: {Owner name}
_Built {date} from {N} approved documents and notes ({earliest year}–{latest year}). Target role: {role, or "not specified"}._
_Every fact cites its evidence card, e.g. [E-3f9a2c]. Look one up with `evidence_tool.py show E-3f9a2c`. Items marked (inferred) weren't stated outright._

## Snapshot
3–5 sentences: who they are professionally, the through-line across roles, 2–3 signature strengths with evidence, what they're aiming for next.

## Career timeline
| Period | Organization | Title / level | Team & scope | Evidence |
|---|---|---|---|---|
(reverse chronological; include roles that only older resume versions mention)

## Roles in depth

### {Title}, {Organization} ({start}–{end})
**Mandate & scope:** what they owned, team size, who they reported to (by role), the metrics they were accountable for.

#### {Project} ({dates})
- **Context:** the problem and the stakes
- **My role:** what they personally did (explicit / inferred)
- **Key decisions:** see the decision log rows [D3, D4]
- **What was hard:**
- **Outcome:** metrics exactly as written, or [ADD METRIC: …]
- **Worked with:** roles, not names
- **Evidence:** [E-…] [E-…]

**People & leadership:** mentoring, hiring, managing, influence without authority.
**Feedback received:** short quotes with source and date.
**Setbacks & lessons:**

## Decision log
| # | When | Decision | Options considered | Chosen & why | Tradeoffs | Result | Evidence |
|---|---|---|---|---|---|---|---|
(the most valuable section; include smaller calls that show judgment)

## Achievements & metrics
- {metric with baseline and context} [E-…]

## Conflicts, setbacks and mistakes
For each: what happened, the owner's part in it, what they did, what changed afterwards. Honest; these feed the hardest questions.

## Feedback themes
- **Recurring strengths** (ideally 2+ sources each):
- **Recurring growth areas:**
- **What they've done about them:**

## Skills with evidence
| Skill | Where it shows | Evidence |
|---|---|---|

## Motivations & direction
What energizes them, what they want next, why they made past moves (journals, career notes, user-notes). If nothing was found, say so.

## Open questions & gaps
- Discrepancies between sources (dates, titles, numbers) and which one you used
- Major projects without outcomes or metrics
- Question types with no story yet (e.g. no conflict, no failure found)

## Sources
| Source | Date | Cards |
|---|---|---|
(titles and dates of the documents used, from the extraction summary)
```

Judgment calls:
- **Conflicting facts:** prefer the most recent authoritative source (the latest resume over an older one; a dated document over an undated note), and list the discrepancy under Open questions.
- **Confidential items** (`sensitivity: confidential`): keep the truth here, since this document is for the owner, but note "(confidential - generalize when speaking)".
- **Names:** colleagues by role only, even here.
