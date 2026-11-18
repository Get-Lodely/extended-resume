---
name: extended-resume
description: Builds an evidence-backed "extended resume" from the person's own notes and documents (Documents, Desktop, Downloads, Obsidian, Logseq, and opt-in Apple Notes, Notion, OneNote, Bear, Joplin, cloud drives), capturing projects, decisions and alternatives weighed, tradeoffs, metrics, conflicts, mistakes and feedback, then writes interview-ready answers to the top behavioral questions (tell me about yourself, conflict, failure, prioritization, deadlines, disagreeing with a manager, strengths and weaknesses and more), each grounded in and cited to that history. The person approves exactly which files are read before anything is opened. Also answers questions the person adds. Use whenever someone wants to prepare for behavioral or leadership interviews, build a STAR story bank, mine their notes or work history for interview stories, turn years of docs into a deeper resume or brag document, or answer behavioral questions from their own experience, even if they don't mention notes or files.
license: MIT
---

# Extended Resume → Behavioral Answer Bank

Turn the notes and documents already on someone's computer into:
1. **`extended-resume.md`**: a deep, sourced record of what they did, decided, weighed, learned and were told; and
2. **`answers.md`**: answers to the top behavioral interview questions, every claim traceable to a source.

A normal resume keeps outcomes and drops the reasoning. Interviewers probe the reasoning ("what else did you consider?", "what would you do differently?"), and that reasoning usually still sits in old design docs, retros, 1:1 notes and self-reviews. This skill finds it, so answers are specific and true instead of generic.

`SKILL_DIR` below means the folder that contains this file. All scripts are Python 3.8+ with the standard library only; run them as `python3 SKILL_DIR/scripts/<name>.py`. Everything runs locally; no script uses the network.

## Ground rules

1. **You (the AI) never open the person's original files.** Not before approval, not after. Only the skill's scripts read originals, and `extract.py` reads only the items the person approved. You read metadata digests while scoping, and the extracted, redacted text in `OUT/.work/text/` (via the batch lists) afterwards. Never cat/grep/head/open/preview anything inside a source folder or a note app's database, even to settle a doubt; mark it ASK instead. This is the promise the person is relying on.
2. **The person approves the scope before anything is read.** Show them what's in, what's out and what needs their call; apply their changes; freeze only when they say it's approved.
3. **Never invent experience.** Every fact in the resume and answers comes from an evidence card or from the person directly. Missing numbers become visible placeholders like `[ADD METRIC: latency before/after]`. A made-up metric repeated in an interview is far worse than a gap, because interviewers dig into numbers.
4. **Only the owner's experience counts.** Other people's resumes, saved articles and teammates' docs aren't their stories.
5. **Protect other people.** Colleagues appear by role, never by name. Generalize confidential details (unreleased products, customer names) in answers.
6. **Don't read the person-only files**: `hidden-by-safety.md` and `quarantine.md` list sensitive file names for the person; you only need the counts the scripts print.

## Output folder

Default `OUT = ~/extended-resume/` (ask if they want another place; never inside a git repository or inside a source folder). If your sandbox can't write there, ask the person to approve the write or pick a folder you can write to. Pass `--out OUT` to every script if it isn't the default.

| Path | What it is |
|---|---|
| `extended-resume.md` | the deep resume |
| `answers.md` | the answer bank |
| `scope.md` | the reviewable list of what will be read (the person can tick/untick) |
| `custom-questions.md` | questions the person added; persists across runs |
| `user-notes.md` | facts the person told you directly (counts as a source) |
| `sources.selected.json` | which places are switched on |
| `hidden-by-safety.md`, `quarantine.md` | for the person only |
| `.work/` | catalog, decisions, extracted text, evidence. Holds extracted text of their documents; offer to delete it at the end |

## Pick the mode

Look in `OUT` first.
- No `extended-resume.md` → **Full build** (steps 1–9).
- It exists and they want a refresh → **Update**: `scope.py catalog --refresh`, `scope.py digest --only-undecided`, decide only the new folders, review, freeze, `extract.py --only-new`, mine only the new batches, merge, then revise the resume and the affected answers.
- They only want more questions answered → **Add questions** (steps 7–8 for the new questions only; no scanning).
- No local files (e.g. a chat app with an uploaded zip): unzip it into a folder, add that folder with `sources.py select --add-folder PATH`, and run the full build on it. There are no guard hooks in that setting; ground rule 1 still applies.

## Step 1: Sources and consent (one message)

```
python3 SKILL_DIR/scripts/sources.py detect
```
This prints a numbered menu of the places the skill knows about, with counts, reading nothing but names and counts:
- **On by default:** Documents, Desktop, Downloads (all *strict*: a file is read only with positive evidence it's career material), Obsidian vaults (from Obsidian's own vault list), Logseq graphs, `~/Notes`.
- **Off until switched on:** Apple Notes (macOS asks permission; can be limited to named folders), Notion desktop cache, OneNote (Windows desktop app), Bear, Joplin, iCloud Drive, each cloud drive, and connectors.
- If you have Notion / Google Drive / Microsoft 365 connector tools available, mention them as an optional source too.
- A source marked **NO PERMISSION** is one macOS is blocking (it is not empty). On macOS the access belongs to the app that runs the scripts: when that is Claude Code, the person turns the folder on in System Settings > Privacy & Security > Files and Folders under the lowercase **claude** entry (the command-line tool), not under Claude.app. Then run `detect` again.

In one message, show the menu and ask the person to:
- confirm or change which sources are on;
- confirm their **name** as it appears in documents (prefill from the hints) and any other spellings;
- optionally list **employers with rough dates** (`Acme Corp|2021-04|2023-11`): this sharpens the scoping a lot;
- optionally give a **target role or job description**, and anything to leave out.

Tell them plainly what happens next: "I'll first list names, folders, dates and document properties (author, title, company), never contents. You'll review exactly which files are in scope and can change anything. Only after you approve does a local script read those files, screen out anything that looks like a bank, ID, medical or password document, and strip stray secrets. I only see that cleaned text."

Also tell them that before anything is read (step 4), you will install the **read guard**: a pre-tool-use hook that blocks the AI's own tools from touching their source folders, so the promise above is enforced rather than just followed. It edits the agent's user settings (a backup is kept) and is removed in step 9. This is not optional; if they don't want their settings changed, the build stops after the scope review.

Save their choices:
```
python3 SKILL_DIR/scripts/sources.py select --owner "Sam Okafor" --alias "Sam O" \
  --employer "Acme Corp|2021-04|present" "Tidewater Health|2019-01|2021-03" \
  --enable 7 --disable 3 [--add-folder ~/Work/notes] [--apple-notes-folders "Work,1:1s"]
```
If they say "just run it": keep the defaults, state them, and still do steps 2–3 (the review can't be skipped).

## Step 2: Scope proposal (metadata only)

```
python3 SKILL_DIR/scripts/scope.py catalog
python3 SKILL_DIR/scripts/scope.py digest
```
`catalog` lists items with names, dates, document properties and download origins, never contents; it also drops credential/key files and encrypted files outright. `digest` writes folder summaries to `.work/scope/digest/part-NNN.md`.

Read **`references/scoping-guide.md`**, then judge every folder card: `IN-ALL`, `OUT-ALL` (with a category), `ASK-ALL` or `MIXED`. For MIXED folders run `scope.py files F-xxxxxxxx ...` and decide each item `IN` / `OUT` / `ASK`. Write decisions as JSON lines to `.work/scope/decisions/part-NNN.jsonl` (one file per digest part). If there are many parts and you can run parallel workers or sub-agents, give each worker one part plus the scoping guide and have it write that part's decisions file.

In strict sources, IN needs positive evidence; anything uncertain is ASK. Then:
```
python3 SKILL_DIR/scripts/scope.py status     # nothing left unreviewed?
python3 SKILL_DIR/scripts/scope.py render     # writes OUT/scope.md and prints a short summary
```

## Step 3: Review loop (repeat until approved)

Show the printed summary (counts per source, biggest in-scope folders, the "needs your call" list grouped by folder, left-out counts by reason) and point them to `OUT/scope.md`, where they can tick and untick.

Apply what they say:
```
python3 SKILL_DIR/scripts/scope.py set --exclude "~/Documents/Personal"
python3 SKILL_DIR/scripts/scope.py set --include F-1a2b3c4d f-0123456789ab
python3 SKILL_DIR/scripts/scope.py set --include-ask "folder:Work"     # all "needs your call" items there
python3 SKILL_DIR/scripts/scope.py set --before 2018-01-01            # leave out anything older
python3 SKILL_DIR/scripts/scope.py apply-md                           # pick up their checkbox edits
python3 SKILL_DIR/scripts/sources.py select --add-folder ~/Work/notes && python3 SKILL_DIR/scripts/scope.py catalog
```
Then `scope.py render` again and show the new summary. Keep going until they explicitly approve. Undecided items are not read; say so.

Only then:
```
python3 SKILL_DIR/scripts/scope.py freeze --approved
```

## Step 4: Read and mine

**Install the read guard first, every time.** Never run `extract.py` or read any extracted text without it:
```
python3 SKILL_DIR/scripts/guard.py install --claude      # Claude Code
python3 SKILL_DIR/scripts/guard.py install --codex       # Codex (then: type /hooks in Codex and trust it)
python3 SKILL_DIR/scripts/guard.py install --claude --dry-run   # show the change instead of making it
```
Tell the person it's installed. If the install fails, or the agent you're running in has no hook support (no `--claude`/`--codex` fit), stop and tell the person; don't extract until they've fixed it or explicitly said to go on without the guard. The only exception is the no-local-files setting above, where there are no originals to guard.

```
python3 SKILL_DIR/scripts/extract.py
```
It reads only the frozen list, refuses files changed since approval, quarantines anything that reads like a bank/tax/pay, ID, medical, legal or password document (the person sees which in `quarantine.md`; you see counts), redacts keys, tokens, ID and card numbers, emails and phone numbers, and writes `.work/text/*.txt`, `.work/batches/*.txt` and `.work/extract_summary.md`. If the person says a quarantined item is a false alarm, re-run with `--allow ITEM_ID`.

Then mine evidence with **`references/mining-guide.md`**:
1. **Skeleton first:** read the newest resume's text (marked in `extract_summary.md`) and write role cards to `.work/evidence/batch-000.jsonl`.
2. **Batches:** for each batch file, read the listed text files and write `.work/evidence/<batch name>.jsonl`. With parallel workers, give each one a batch, the mining guide, the owner's name and the skeleton roles; ask them to reply only with a count. Without, go batch by batch and write each batch's cards before reading the next, so raw text doesn't pile up. On a very large corpus, stop when later (lower-ranked) batches stop producing new stories, and say where you stopped.
3. `python3 SKILL_DIR/scripts/evidence_tool.py merge` → `.work/evidence.jsonl` and `.work/evidence_index.md` (with a coverage table and gaps). Fix any reported bad lines and merge again.

## Step 5: Write the extended resume

Follow **`references/extended-resume-template.md`**. Work from `evidence_index.md`; pull full cards with `evidence_tool.py show E-xxxxxx` or `--type decision`. Keep the decision log rich; note conflicting facts under Open questions; mark inferred items.

## Step 6: Gap check (recommended, skippable)

From the index's Gaps section and the coverage table, ask the person at most ~7 short questions in one message: missing outcomes on major projects, an unclear personal role, a missing story type (no conflict or failure found), and their real reason for wanting to move. Append answers to `OUT/user-notes.md` with the date, and add cards with `"item": "user-notes"` to `.work/evidence/user-notes.jsonl`, then merge again. If they skip, keep placeholders.

## Step 7: Questions

```
python3 SKILL_DIR/scripts/questions.py list
```
The built-in bank has 23 questions, deduplicated from 30 commonly asked prompts, with company-specific ones (like "Why do you want to work at Google?") removed. See `assets/question_bank.json` for what each question assesses and what evidence to look for.

To add questions (a single one, several, or a messy pasted list):
```
python3 SKILL_DIR/scripts/questions.py add "Tell me about a time you mentored someone."
python3 SKILL_DIR/scripts/questions.py add --from-file pasted.txt
python3 SKILL_DIR/scripts/questions.py add "How do you handle disagreement with a peer?" --variant-of conflict
python3 SKILL_DIR/scripts/questions.py skip why-not-hire
```
The script flags duplicates, possible duplicates and company-specific wording. It can't catch every same-meaning duplicate ("disagreed with a coworker" vs "conflict with a peer"), so check new questions against the list yourself; if one would get the same answer as a built-in, re-add it with `--variant-of`. Company-specific questions are fine when the person wants them: ask what draws them to that company and answer by connecting their real history to it, never inventing facts about the company.

## Step 8: Story map, then answers

Follow **`references/answer-guide.md`**: build the story map (8–14 stories, each primary for at most 3 questions), then write `OUT/answers.md` in the format given there, with follow-ups, a backup story, sources and a "check before using" list for every question. In Add-questions mode, append the new answers and update the story map without rewriting anything else.

Before finishing, run the self-check in the answer guide: every number traces to evidence or `user-notes.md`, no names, every placeholder listed under "Fill these first".

## Step 9: Wrap up

```
python3 SKILL_DIR/scripts/audit.py          # did any AI tool call touch the originals?
python3 SKILL_DIR/scripts/guard.py uninstall --claude   # or --codex: always remove the guard installed in step 4
```
Tell the person: where the files are; how many sources, cards and stories; the audit result; the "Fill these first" list; that they can add questions any time by asking or by editing `custom-questions.md`; and offer to delete `OUT/.work/` (it holds extracted text of their documents).

## Notes for sources no script can reach

- **Notion, full workspace:** Settings → Export → Markdown & CSV, unzip, then add the folder.
- **OneNote on Mac:** export sections to PDF, or use a Microsoft 365 connector.
- **Google Docs:** Drive for desktop keeps only links (`.gdoc`); use Google Takeout (Docs as .docx), unzip, add the folder.
- **Evernote:** export notebooks as `.enex` into a folder that's in scope.
- **Pages / Keynote:** export to .docx / .pdf.

Connector sources (Notion, Google Drive, Microsoft 365 tools the agent already has): search with career terms (resume, review, retro, postmortem, 1:1, design doc, RFC, roadmap, OKR, launch, brag), write the results' **titles, locations and dates only** to a JSONL file and register them with `scope.py add-items --source connectors FILE`. They go through the same review. After the freeze, fetch only the approved pages, save each as `.work/sources/connectors/<item id>.md`, then run `extract.py`. Say plainly that fetching a page shows its text to you before the local screen runs.
