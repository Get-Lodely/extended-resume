# extended-resume

**Turn the notes and documents already on your computer into a deep, sourced career record and interview-ready behavioral answers, without the AI ever opening a file you didn't approve.**

An [Agent Skill](https://agentskills.io) for **Claude** (Claude Code, Claude apps) and **OpenAI Codex**.

A normal résumé keeps outcomes and drops the reasoning. Interviewers probe exactly that reasoning:
- *What else did you consider?*
- *What would you do differently?*
- *How did you get the other team on board?*

That material usually still exists in your old design docs, retros, 1:1 notes, performance reviews, journals and brag docs. This skill finds it (with your approval, file by file) and turns it into two documents:

1. **`extended-resume.md`**: a deep record of what you did, decided, weighed, learned and were told. It covers projects, the decisions behind them, tradeoffs, metrics, conflicts, mistakes and feedback. Every fact cites the note or document it came from.
2. **`answers.md`**: drafts for the 23 most common behavioral interview questions, each built on a real story from that record, with likely follow-ups, a backup story and a "check before using" list.

It **never invents experience**. A missing number becomes a visible `[ADD METRIC: …]` placeholder, and anything inferred is marked `[VERIFY: …]`. A made-up metric repeated in an interview is far worse than a gap.

---

## Quick start

Paste one line into your agent.

**Claude Code**
```text
Install the extended-resume skill by cloning https://github.com/Get-Lodely/extended-resume into ~/.claude/skills/extended-resume, then read its SKILL.md and use it to build my extended resume and behavioral answer bank.
```

**Codex**
```text
Install the extended-resume skill by cloning https://github.com/Get-Lodely/extended-resume into ~/.agents/skills/extended-resume, then read its SKILL.md and use it to build my extended resume and behavioral answer bank.
```

Prefer to install it yourself? Use one of these commands:

```bash
git clone https://github.com/Get-Lodely/extended-resume ~/.claude/skills/extended-resume
```

```bash
git clone https://github.com/Get-Lodely/extended-resume ~/.agents/skills/extended-resume
```

The first is for Claude Code, the second for Codex. To use one copy for both, clone it once and symlink: `ln -s ~/.claude/skills/extended-resume ~/.agents/skills/extended-resume`.

For the Claude apps (claude.ai, desktop), download `extended-resume.skill` from the [latest release](https://github.com/Get-Lodely/extended-resume/releases/latest) and upload it under **Settings → Capabilities → Skills**. There, you upload a zip of your notes instead of pointing at local folders.

Then ask your agent things like:
- "Build my extended resume from my notes and answer the standard behavioral questions."
- "I have a staff engineer loop next week. Mine my docs for STAR stories."
- "Answer these behavioral questions from my own experience: …"
- "Add 'Tell me about a time you mentored someone' to my answer bank."

You can also invoke it directly with `/extended-resume` in Claude Code or `$extended-resume` in Codex.

**Requirements:**
- Python 3.8+ (standard library only, nothing to install).
- Optional: `pdftotext` (poppler) or `pip install pypdf`, for PDFs.
- macOS's built-in `textutil` handles `.doc` and `.rtf`.

---

## How it works

The whole run is designed around one promise: **the AI reads only what you approved, and only after a local script has cleaned it.**

| Step | What happens | Who reads what |
|---|---|---|
| **1. Pick sources** | The skill shows a numbered menu of places it knows about, with counts, and asks for your name (as it appears in documents). Optional extras: your employers with rough dates, a target role, anything to leave out. | Folder names and counts only |
| **2. Install the read guard** | A pre-tool-use hook is added to your Claude Code or Codex settings, with a backup. It blocks the AI's own file and shell tools from touching your source folders and note-app databases. It's removed at the end. | — |
| **3. Propose a scope** | Scripts list file names, folders, dates, document properties (author, title, company) and download origins, **never contents**. The AI judges each folder or file against a rubric: authored by you? Names an employer? Dated during a job? Came from a work tool, or from a bank? In Documents, Desktop and Downloads, a file is in scope only with **positive evidence** that it's career material. Anything uncertain goes to you. | Metadata only |
| **4. You review `scope.md`** | It lists what's in, what needs your call and what's left out, each with a reason. Tick or untick items, or say things like "leave out Documents/Personal" or "nothing before 2018". Repeat until you say it's approved. | You |
| **5. Freeze and read locally** | A local script reads only the frozen list and refuses files that changed after approval. It quarantines anything that reads like a bank, tax, pay, ID, medical, legal or password document. It redacts keys, tokens, ID and card numbers, emails and phone numbers. Then it writes cleaned text. | The script reads originals; the AI sees only cleaned text |
| **6. Mine evidence** | The AI turns the cleaned text into small structured *evidence cards*: roles, projects, decisions (options and why one won), achievements with exact numbers, conflicts, mistakes, feedback and motivations. Large corpora are split across parallel workers. | Cleaned text |
| **7. Write the extended résumé** | A timeline, each role in depth, a decision log, metrics, setbacks, feedback themes, skills with evidence, and the conflicting facts it found between sources. | Evidence cards |
| **8. Gap check** | Up to ~7 short questions about missing outcomes, unclear dates, missing story types and your real reason for moving. You can skip it, and the placeholders stay. | You |
| **9. Answers, audit, cleanup** | It builds a story map (8–14 stories spread across questions), writes `answers.md` and self-checks every number against its source. An audit of the session transcript reports any AI tool call that referred to your files. The guard is removed. You're offered deletion of the working folder. | — |

Later runs can **update** (re-scan only new or changed files) or **add questions** (no re-scanning at all).

---

## Inputs

| Input | Required? | How you give it |
|---|---|---|
| Your name, plus any other spellings in documents | Yes | Prefilled from your system and git name hints; confirm in chat |
| Which sources to scan | Yes (defaults are sensible) | Toggle numbers in the menu |
| Employers with rough dates (`Acme Corp\|2021-04\|2023-11`) | Optional, but sharpens scoping a lot | Chat |
| Target role or job description | Optional | Chat |
| Things to leave out (folders, date ranges, topics) | Optional | Chat or `scope.md` |
| Extra folders (e.g. an exported Notion workspace or Google Takeout) | Optional | Chat; added with `sources.py select --add-folder` |
| Apple Notes folders to limit to | Optional | Chat |
| Your scope approval | **Yes, nothing is read without it** | Chat, after reviewing `scope.md` |
| Answers to the gap check | Optional | Chat; saved to `user-notes.md` and treated as a source |
| Your own questions | Optional | Chat, `questions.py add`, or `custom-questions.md` |

---

## Data sources

| Source | Default | How it's read | Status |
|---|---|---|---|
| Documents, Desktop, Downloads | **On** (strict) | Local files: docx, pptx, xlsx, odt, pdf, rtf, html, md, txt, Evernote `.enex` | Tested, including real macOS installs |
| Obsidian vaults | **On** | Markdown, found from Obsidian's own vault list | Tested |
| Logseq graphs | **On** | Markdown pages and journals | Experimental |
| `~/Notes` | **On** | Markdown and text | Tested |
| Apple Notes (macOS) | Off | `osascript` (macOS asks for permission once); can be limited to named folders | Tested on a real macOS install |
| Notion (desktop app cache) | Off | Read-only SQLite; only pages the app has cached | Tested on a real cache; newer CRDT-encoded blocks decoded best-effort |
| OneNote (Windows desktop) | Off | COM automation while OneNote is open | Experimental |
| Bear, Joplin | Off | Read-only SQLite | Experimental |
| iCloud Drive, other cloud drives | Off | Local synced folders (strict) | Tested as folders |
| Connectors (Notion, Google Drive, Microsoft 365 tools your agent already has) | Off | Titles listed for review; approved pages fetched after the freeze | Depends on your agent |
| Any folder you add (exports, unzipped archives) | Off until added | Same as Documents (strict) | Tested |

**Never listed at all:** password managers, keychains, browser data, Mail, Messages and photo libraries.
**Always dropped:** credential and key files, encrypted files and images (there's no OCR).

**macOS tip:** if Documents or Downloads shows **NO PERMISSION**, open System Settings → Privacy & Security → Files and Folders. Enable those folders for the agent's command-line process, which for Claude Code is the lowercase `claude` entry, not Claude.app. Then run detection again.

Sources no script can reach directly:
- **Notion, full workspace:** Settings → Export → Markdown & CSV, then add the unzipped folder.
- **Google Docs:** use Google Takeout (Docs as .docx).
- **OneNote on Mac:** export to PDF.
- **Pages and Keynote:** export to .docx or .pdf.

---

## Outputs

Everything is written to `~/extended-resume/` (you can choose another folder, never inside a git repository or a source folder).

| File | What it is |
|---|---|
| `extended-resume.md` | Snapshot, career timeline, roles and projects in depth, decision log, achievements and metrics, conflicts, setbacks and mistakes, feedback themes, skills with evidence, motivations, open questions (conflicting dates, missing metrics, story types with no evidence), and a sources table |
| `answers.md` | "Fill these first" checklist, story map, and for each question: the answer, likely follow-ups, a backup story, sources and "check before using" |
| `scope.md` | The reviewable list of what will be read; you can tick and untick |
| `custom-questions.md` | Questions you added; kept across runs |
| `user-notes.md` | Facts you told the skill directly (counts as a source) |
| `quarantine.md`, `hidden-by-safety.md` | **For your eyes only:** what was held back, and why. The AI gets only the counts. |
| `.work/` | Catalog, decisions, cleaned text and evidence cards. **It contains extracted text of your documents**, so delete it when you're done (the skill offers to). |

Every fact in the extended résumé cites an evidence card (e.g. `[E-3f9a2c]`). Look one up with `python3 scripts/evidence_tool.py show E-3f9a2c`.

---

## The behavioral questions

The built-in bank has **23 canonical questions**, deduplicated from 30 commonly reported interview prompts. Company-specific prompts ("Why do you want to work at Google?") are left out, because your history alone can't answer them. Add them as custom questions with context about the company, and the skill answers from your real history without inventing facts about the company.

Each question has an answer *shape*:

- **story:** STAR + Learning, roughly 220–350 words.
- **pitch:** present → past → future, about 90 seconds.
- **approach + example:** your actual method, then a short story.
- **self-assessment:** evidence-backed strengths, plus a real weakness with progress.
- **motivation:** forward-looking, with nothing negative about an employer.

| # | Question | What the interviewer is assessing | Shape |
|---|---|---|---|
| 1 | Tell me about yourself. | A concise, relevant career narrative; whether your path leads naturally to this role | pitch |
| 2 | Tell me about a time you solved a complex or difficult problem. | Framing, decomposition, hypotheses, persistence, judgment | story |
| 3 | Tell me about a technical challenge you overcame. | Technical depth, tradeoff reasoning, ownership of a hard outcome | story |
| 4 | Tell me about a time you solved a problem in an innovative way. | Challenging assumptions, simplifying, a non-obvious approach | story |
| 5 | What is the most challenging situation you've faced in your career? | Resilience, composure and judgment under pressure | story |
| 6 | What is the project you are most proud of? | What you value, depth of ownership, impact | story |
| 7 | Tell me about the most complex project you have led. | Planning, coordination across teams, risk management, execution | story |
| 8 | Tell me about a time you made a short-term sacrifice for long-term gain. | Long-term thinking and judgment about tradeoffs | story |
| 9 | Tell me about a time you made a decision with limited data or took a calculated risk. | Reasoning under uncertainty; limiting downside (reversibility, rollback, staged rollout) | story |
| 10 | How do you prioritize your work (e.g. five projects at once)? | A real method, impact vs. effort, communicating tradeoffs, saying no | approach + example |
| 11 | Tell me about conflicting stakeholder priorities and how you got alignment. | Influence without authority, negotiation, driving to a decision | story |
| 12 | Tell me about a project with a tight deadline. | Scoping under pressure, quality tradeoffs, keeping people informed | story |
| 13 | Tell me about a time you missed a deadline. | Ownership, raising risk early, recovery, what changed afterward | story |
| 14 | Tell me about a time you made a mistake or failed. | Self-awareness, ownership without excuses, systemic fixes | story |
| 15 | Tell me about a time you received negative feedback. | Coachability and concrete behavior change | story |
| 16 | Tell me about a conflict or disagreement with someone. | Empathy, listening, using data, keeping the relationship | story |
| 17 | Tell me about a time you disagreed with your manager. | Respectful pushback with evidence; disagree-and-commit | story |
| 18 | Tell me about a time you dealt with a difficult person at work. | Professionalism, empathy, boundary-setting, focus on the outcome | story |
| 19 | Describe an experience working on a cross-functional team. | Collaboration across disciplines; translating between functions | story |
| 20 | How do you earn the trust of your team members? | Reliability, transparency, care for others, follow-through | approach + example |
| 21 | What are your strengths and weaknesses? | Evidence-backed self-awareness; a real weakness and what you're doing about it | self-assessment |
| 22 | Why should we not hire you? | Honesty about genuine gaps and how you mitigate them | self-assessment |
| 23 | Why do you want to switch jobs now? | Positive, forward-looking motivation that fits your career arc | motivation |

How the answers are built (from [`references/answer-guide.md`](references/answer-guide.md)):
- **Story map first.** 8–14 stories, each the primary story for at most 3 questions. Questions in the same family (conflict / manager / difficult person, or mistake / missed deadline) get different stories, because interviewers in one loop compare notes.
- **Grounded.** Every claim traces to an evidence card, and numbers are copied exactly.
- **Private.** Colleagues appear by role, never by name, and confidential details are generalized in the spoken text.
- **Honest when there's no story.** If no real story exists for a question, the skill says so and gives prompts to jog your memory, rather than writing a fake one.

---

## Privacy and safety: how leaks are prevented, and what's left to you

This skill handles some of the most personal data on your computer. It is built to keep the AI away from anything you didn't approve, and to keep sensitive material out of the text the AI sees.

**Built-in safeguards**
- **Approval before reading.** Nothing is read until you approve the exact list in `scope.md`. Undecided items are never read.
- **Metadata-only scoping.** While deciding scope, the AI sees names, folders, dates and document properties, never contents.
- **The AI never opens originals.** Only the skill's local scripts read your files, and only from the frozen list.
- **Enforced, not just instructed.** A pre-tool-use hook (the read guard) blocks the AI's own file and shell tools from touching your source folders and note-app databases. After the run, `audit.py` checks the session transcript for any tool call that referred to them.
- **Screening before the AI sees text.** Documents that look like bank, tax, pay, ID, medical, legal or password material are quarantined, so their text is never written. Keys, tokens, ID and card numbers, emails and phone numbers are redacted from everything else.
- **Never touched:** password managers, keychains, browser data, Mail, Messages and photos are never listed. Credential, key and encrypted files are dropped.
- **Local only.** No script uses the network. An access log (`.work/access_log.jsonl`) records every file the scripts read and what happened to it.
- **People protected.** Colleagues appear by role, never by name. Confidential details (unreleased products, customer names, financials) are flagged and generalized in answers.

**Limits, stated plainly**
- **The guard isn't airtight.** It catches direct access by path. A deliberately disguised command could slip past it, which is why the audit exists.
- **Names are visible.** File names and document properties are visible to the AI during scoping. Contents of unapproved files never are.
- **Your AI provider sees the cleaned text.** It processes whatever cleaned text the AI reads, under that provider's normal terms.
- **Connectors are fetched first.** Pages from Notion, Google Drive or Microsoft 365 via your agent are fetched by the AI after approval, so their text reaches the AI before the local screen runs.
- **Chat apps have no hooks.** In chat apps without local files, you upload a zip. The approve-then-read flow still applies, but there's no hook to enforce it.
- **Redaction is pattern-based.** It catches common formats, not every possible secret.

**Use at your own discretion.** You decide what goes in scope, and you're responsible for what you share with your AI provider and in interviews:
- **Mind confidentiality.** Respect your employers' confidentiality obligations and any NDAs. Generalize what isn't yours to share.
- **Review everything.** Read both outputs and fill every `[ADD METRIC]`, `[VERIFY]` and `[CONFIRM]` before relying on them.
- **Drafts, not facts.** The answers are drafts drawn from your own history, not guaranteed-accurate statements and not career, legal or employment advice.
- **Clean up.** Delete `~/extended-resume/.work/` when you're done; it holds extracted text of your documents.

This software is provided "as is", without warranty of any kind (see [LICENSE](LICENSE)).

---

## Repository layout

```
SKILL.md                       the workflow the agent follows
agents/openai.yaml             Codex display metadata
assets/question_bank.json      the 23 questions: variants, what they assess, what evidence to look for
assets/sources.json            the source registry
scripts/                       sources, scope, extract, guard, audit, questions, evidence_tool (+ adapters, common)
references/                    scoping guide, mining guide, résumé template, answer guide
evals/                         a synthetic home folder fixture, end-to-end tests and agent eval cases
```

## Testing

```bash
python3 evals/run_tests.py
```

This builds a synthetic home folder in a temporary directory and checks the whole pipeline end to end. It touches nothing else on your machine. Covered: source detection, metadata-only cataloging, scoping and the review loop, freeze enforcement, extraction with quarantine and redaction, the guard and its install and uninstall, audit, questions, evidence merging, and the Notion adapter.

## Contributing

Issues and pull requests are welcome, especially real-machine reports for the experimental adapters (OneNote, Bear, Joplin, Logseq). Please **never attach real personal documents**. Reproduce issues with the synthetic fixture in `evals/fixture/` instead.

## License

[MIT](LICENSE)
