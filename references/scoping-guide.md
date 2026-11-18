# Scoping guide: deciding what gets read

You are deciding, **from metadata only**, which items are worth reading to reconstruct the owner's career. You see folder digests (file counts, types, date ranges, sample names, authors, companies, download origins) and, for mixed folders, per-item lines. You never open a file to decide. If you can't tell, the answer is ASK.

The person reviews everything you decide before anything is read, so a clear reason matters as much as the call itself.

## The bar

**IN means: there is positive evidence this is the owner's own career material.** Not "might be useful", not "probably harmless".

Documents, Desktop, Downloads, iCloud/cloud drives and folders the person added are **strict**: IN needs at least one strong signal, or two supporting signals that point the same way. Anything weaker is ASK. Note apps (Obsidian, Logseq, Apple Notes, Notion, Bear, Joplin, OneNote) are the owner's own notes, so a work-looking title or folder is enough for IN; personal-life notes are still OUT.

## Signals

Weigh them together; no single keyword decides.

| Signal | Weight |
|---|---|
| Author or last editor is the owner (`author you`, `by you`) | strong |
| Company property, folder name or title names one of the owner's employers or teams | strong |
| A resume/CV whose author is the owner, or that has no author but sits in a career folder | strong |
| Notion/notes page created or last edited by the owner, with a work-like title | strong (notes) |
| Dated during a known employment period (`during Acme`) | supporting |
| Downloaded from a work tool: Confluence, Jira, Google Docs/Slides, Notion, Workday, Lattice, Culture Amp, 15Five, BambooHR, LinkedIn (own profile export), Greenhouse/Lever *offer or scorecard about the owner* | supporting |
| Name reads as a work artifact: spec, design doc, RFC, ADR, PRD, roadmap, retro, postmortem, incident, 1:1, review, self-review, brag doc, OKRs, launch, deck, proposal, status update | supporting |
| Folder full of the owner's work artifacts (most items authored by the owner) | supporting for the whole folder |

**OUT** (give a category):

| Looks like | Category |
|---|---|
| Someone else's document: author is another person and nothing ties it to the owner's work; candidate resumes and interview packets the owner reviewed as an interviewer; other people's papers, decks, CVs | `others-docs` |
| Bank, tax, payroll, invoices, receipts, insurance, mortgage, leases, utilities, travel bookings, tickets, school or kids' forms, government forms | `finance` / `personal-admin` |
| Medical records, lab results, prescriptions, therapy | `medical` |
| Contracts, legal correspondence, settlements, immigration paperwork | `legal` |
| Manuals, ebooks, research papers, courses, templates, datasets, saved articles and newsletters, product brochures | `reference-media` |
| An older copy or version when a newer one of the same document is in scope (`resume v3` when `resume final 2024` exists) | `duplicate` |
| Source code, generated files, exports of tooling | `code` |

Download origin is a strong OUT signal when it's a bank, payroll, insurer, clinic, government or ticketing site.

**ASK** when:
- the name is generic (`notes.docx`, `Document (3).pdf`, `Untitled.md`) and there's no author, company or origin to go on;
- it could be career or personal (`plan.docx`, `ideas.md`, `goals 2022`);
- it's career-related but about someone else in a way the owner may still want (a reference letter written *for* the owner, feedback the owner wrote for a report);
- an offer letter or compensation document (career, but sensitive; the person decides).

## Working through a digest

1. Read the folder card. Decide the whole folder when the evidence is consistent:
   - `IN-ALL` - e.g. "14 docs authored by you, company Acme, 2021-2023".
   - `OUT-ALL` - e.g. "tax and bank statements from chase.com / irs.gov" (`finance`).
   - `ASK-ALL` - a folder you can't judge but that could matter (rare; prefer MIXED).
   - `MIXED` - the folder holds both; then run `scope.py files <F-id>` and decide each item.
   - Add `"recursive": true` only when the folder's whole subtree is clearly the same (e.g. `Documents/Personal`, `Documents/Taxes`, `Work/Acme`). Subfolders with their own decisions still win. This works for note-app folders too (`Apple Notes: iCloud/Personal` covers `Apple Notes: iCloud/Personal/Trips`).
2. Item decisions inside MIXED folders: `IN`, `OUT` (with category) or `ASK`, each with a short reason a person can check at a glance.
3. Write decisions as JSON lines to `.work/scope/decisions/<digest part name>.jsonl`:
   ```json
   {"target": "F-1a2b3c4d", "decision": "IN-ALL", "reason": "your Acme design docs and retros, 2021-23"}
   {"target": "F-9f8e7d6c", "decision": "OUT-ALL", "category": "finance", "reason": "bank statements from chase.com", "recursive": true}
   {"target": "F-5a5a5a5a", "decision": "MIXED", "reason": "work docs mixed with downloads"}
   {"target": "f-0123456789ab", "decision": "IN", "reason": "your self-review, H2 2023"}
   {"target": "f-ba9876543210", "decision": "OUT", "category": "others-docs", "reason": "candidate resume you reviewed"}
   {"target": "f-aaaaaaaaaaaa", "decision": "ASK", "reason": "generic name, no author"}
   ```
4. Run `scope.py status` and make sure no folder is left unreviewed. Unreviewed items stay ASK and are never read.

## Reasons people can check

Good: "authored by you, Acme, Mar 2023", "from chase.com, bank statement", "candidate's resume (author Priya N.)", "older copy of brag-doc-2024".
Bad: "relevant", "not relevant", "career".

## Things to keep in mind

- Names and paths you see may themselves be personal. Don't repeat them in chat beyond what the person needs to review the scope.
- Never peek inside a file to settle a call. ASK is the right answer to uncertainty; the person can resolve twenty ASK items in seconds.
- When parallel workers split the digest, each writes its own decisions file named after its part; nothing else needs coordinating.
