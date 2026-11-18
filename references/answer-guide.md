# Answer guide

How to turn the extended resume into interview answers that are specific, honest and sound like the person.

## 1. Build a story map first

Pick **8–14 stories** from the extended resume. Good stories are:
- recent (last ~5 years) unless an older one is clearly stronger,
- personally driven (the owner's actions are explicit, not inferred),
- complete (a clear outcome, ideally with a number),
- tense (a real choice, constraint, disagreement or setback).

Then map every question to a **primary** and a **backup** story:
- A story is primary for at most **3** questions, and each reuse tells it from a different angle (the decision for "limited data", the people side for "conflict").
- Spread stories across roles and organizations so the candidate doesn't sound one-note.
- Questions in the same family (complex problem / technical challenge / innovative solution; conflict / manager / difficult person; mistake / missed deadline) get *different* primary stories, because interviewers in one loop compare notes.

## 2. Formats by question shape

The `shape` field in the question bank says which one to use.

- **story** (most questions): STAR + L.
  - *Situation* (2–3 sentences, with stakes) → *Task* (1 sentence: the owner's responsibility) → *Action* (~60% of the answer: what **I** did, the options I weighed and why I chose, how I brought people along) → *Result* (metrics exactly as recorded, and what it unlocked) → *Learning* (one specific sentence, not a platitude).
  - 220–350 words ≈ 1.5–2.5 minutes spoken.
- **pitch** (tell me about yourself): present → past → future, 150–220 words (~90 seconds). Current role and scope; 2 highlights with numbers that fit the target role; the through-line; why this next step. No childhood, no full chronology.
- **approach + example** (prioritization, earning trust): 2–4 sentences of the owner's *actual* method (drawn from evidence, e.g. the triage doc they wrote), then a short story showing it (120–200 words).
- **self-assessment** (strengths and weaknesses, why not hire):
  - Strengths: 2–3, each with a proof point from evidence (ideally praise that recurs across reviews).
  - Weakness: real, relevant but not disqualifying, backed by actual feedback, with concrete steps and progress since. No humblebrags ("I work too hard").
  - Why not hire: an honest gap against the target role or a working style that wouldn't suit some teams, plus how it's mitigated.
- **motivation** (why switch now; company-specific questions): forward-looking pull toward the target role, not push away from the current job; consistent with the career arc; nothing negative about an employer. If the notes don't show a motivation, draft from what is known and mark `[CONFIRM: your real reason]`. For a company-specific question, use only what the person told you about the company; never invent facts about it.

## 3. Traps to avoid

- **Mistake / failure / missed deadline:** a real miss the owner contributed to, raised early, fixed, and followed with a systemic change (postmortem action items are gold). Not a disguised success.
- **Conflict / manager / difficult person:** steelman the other side, show listening and evidence, end with the relationship intact. Never villainize anyone; never name anyone.
- **Negative feedback:** paraphrase the actual feedback, the honest first reaction, what changed, and evidence it worked (later feedback).
- **Calculated risk / limited data:** what was known, what wasn't, why waiting cost more, how the downside was limited (reversible, staged rollout, rollback plan), what was monitored.
- **Short-term sacrifice:** name what was given up (speed, scope, credit) and the measured long-term payoff.

## 4. Grounding rules (these matter more than polish)

- Every factual claim traces to evidence cards; list them on the Sources line.
- Numbers exactly as in the evidence. No rounding up, no invented percentages. Missing → `[ADD METRIC: what to measure]`.
- Inferred facts → `[VERIFY: …]`.
- Confidential items generalized in the spoken text ("a top-5 US retailer", "an internal payments platform") and listed under "Check before using".
- People by role, never by name.
- "I" for the owner's actions, "we" only for team outcomes.
- No matching story at all: don't write a fake one. Write "No matching story found in your notes", give 2–3 prompts to jog memory, and point to the closest adjacent story.

## 5. answers.md format

```markdown
# Behavioral answer bank: {Owner}
_Built {date} from extended-resume.md · target role: {role or "not specified"}_

> These are drafts in your own history, not scripts. Read them aloud, cut them to your voice, and fill every [ADD METRIC] / [VERIFY] / [CONFIRM] before an interview.

## Fill these first
- [ ] [ADD METRIC] … (question #)
- [ ] [VERIFY] …

## Story map
| # | Story | When / where | Primary for | Backup for |
|---|---|---|---|---|

---

## 1. {Question}
_Also asked as: {variants}_ · _Story: S3 {name}_ · _They're listening for: {assesses}_

{answer}

**Likely follow-ups**
- *What would you do differently?* {short grounded answer}
- *{probe}* {short grounded answer}

**Backup story:** S7 {name} - {one line on the angle}
**Sources:** [E-3f9a2c] rfc-route-cache.docx (2023-03) · [E-91bb02] 2023-H2 self-review
**Check before using:** {VERIFY items, generalized confidential details}
```

## 6. Self-check before you finish

- Every number in `answers.md` appears in a cited card or in `user-notes.md`.
- No colleague names; confidential details generalized.
- No story is primary for more than 3 questions.
- Every placeholder appears in "Fill these first".
- In add-questions mode, the new answers were appended and the story map updated; nothing else was rewritten.
