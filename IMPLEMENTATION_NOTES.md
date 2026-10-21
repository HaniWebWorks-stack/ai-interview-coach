# Implementation notes: upgrade of 2026-10-14

## Checklist

| Requirement | Status | Where |
|---|---|---|
| Keep interview practice, voice, 3D avatar, barge-in, 15-min mock interview, reports, worksheets, history | Kept (no changes to the voice pipeline except targeted practice) | Practice page |
| Interview types (job, technical, HR, behavioural, internship, management, other) | Kept: the coach asks; reports use per-category rubrics | agent/evaluation.py RUBRICS |
| Smart preparation engine (weakness types, evidence, new questions, notes, frameworks, recommendations, reassessment, targeted practice) | Done | Studio > What to work on next; agent/studio.py make_insights |
| Track improvement / reassess with new questions | Done: AI marks earlier weak spots improved / still weak / not reassessed; Progress page computes criterion changes from data | Studio, Progress |
| Targeted practice session from a weakness, recommendation, roadmap node, resume | Done: coach skips stage 1 and uses the prepared questions | agent/coach_logic.py focus_rules |
| Interactive diagrams: mind map, concept, flowchart, skill gap, STAR, roadmap | Done (React Flow + dagre) | Studio; frontend/src/components/DiagramViewer.tsx |
| Zoom, pan, fit, reset, fullscreen, expand/collapse, node details, notes, practice, assistant, edit labels | Done | Diagram viewer |
| Export PNG/SVG (not blank), PDF via print | Done (tested: 100 kB PNG, 400 kB SVG) | Diagram toolbar |
| Invalid diagram data handled | Done: server validates/repairs, rejects unusable diagrams with a retry | agent/studio.py clean_diagram |
| Skill-gap: unassessed never shown as weakness | Done: no evidence => "Not assessed yet" | clean_diagram |
| Roadmap progress (to do / in progress / done) saved | Done | progress_items table |
| Performance charts (score trend, criteria, activity), missing data, filters | Done (SVG, validated colours, table view, tooltips) | Progress page |
| Study packs: notes, definitions, question bank, quiz, flashcards, frameworks, checklist | Done | Studio |
| Downloads: PDF (print), CSV question bank, CSV progress tracker, CSV report questions, CSV skill table, PNG/SVG diagrams | Done | various |
| XLSX downloads | Not done: CSV opens in Excel; no extra library added | - |
| Resume + JD matching with evidence check, questions, talking points, roadmap, skill diagram | Done | Resume match page; agent/resume.py |
| Advanced evaluation: fairness rules, skipped questions, difficulty, confidence, "AI estimate" wording | Done | agent/evaluation.py |
| Interactive report: summary first, priorities, practice links, studio links, assistant, exports | Done | report screen, History |
| Longitudinal progress (trends, repeated weak spots, strengths, improved, reassess, activity, timeline, filters) | Done, deterministic | agent/progress.py |
| Learning assistant scoped to one item, with real actions | Done | Assistant drawer |
| Security: local-only API, input validation, upload limits, no secrets in browser, resume not stored/logged | Done | viewer_server.local_only, studio_api |
| Database: new tables only, no destructive migration | Done (tested on an old database) | agent/storage.py |
| Duplicate submissions | Blocked per job (409) and buttons disabled while working | studio_api._Once |

## How the diagrams work

1. The Studio (or the assistant, a report, the Progress page) asks the local
   server for a diagram of a topic and type.
2. The server builds a prompt with the topic and, when chosen, a short digest
   of your real saved sessions, and asks Gemini for JSON in a fixed schema
   (nodes with id, label, detail, role, evidence, questions; edges).
3. `studio.clean_diagram` validates and repairs the answer: unique ids, valid
   edges only, known roles, a root/start where needed, skill-gap boxes without
   evidence become "not assessed yet", unusable results are rejected (one
   automatic retry, then an honest error).
4. The diagram is saved in `coach.db` (materials table) and drawn in the
   browser with React Flow; dagre computes the layout. Nothing is drawn by AI.
5. Notes, edited labels and roadmap progress are saved back to the database.
6. Resume skill-match diagrams are built directly from the verified skill
   table (no AI layout or invention).

## Tested (in the development workspace)

- 47 Python tests (`run-tests.bat`): diagram validation, insights/study-pack
  cleaning, resume extraction and evidence checks, progress analytics,
  database migration on an old database, API endpoints, local-only security,
  missing API key, uploads, targeted practice, existing tests.
- TypeScript type check and production build: pass.
- Browser end-to-end (Chromium, desktop 1366px and phone 390px), real server
  and database, with Gemini replaced by a stand-in (the workspace cannot reach
  Google): 47 of 48 checks pass; the remaining "error" is the expected 400
  from the deliberate too-short-file test.

## Not verified yet (needs a real run on the laptop)

- Real Gemini output quality for insights, diagrams, study packs, resume
  match and the assistant (free-tier limits may slow or refuse requests;
  the app shows the reason).
- Targeted practice with the real voice coach.
- PDF resume reading with your own PDF files (scanned PDFs have no text; paste
  the text instead).

## Paid services

None added or activated. Everything uses the existing free Gemini key; the
optional LiveAvatar video avatar is unchanged.

## Update: the coach explains with diagrams during live practice
- New voice tool `show_diagram(topic, diagram_type)` (agent/agent.py). During preparation the coach calls it when she
  starts explaining a topic, concept, process or answer method, or when the user asks for a visual. It never runs
  during the formal mock interview.
- The diagram is drawn in the background with the fast Gemini text models (same free key) and sent to the page on
  the `coach.diagram` stream; it appears under the video in "Visual explanation" (zoom, fit, full screen, click a box,
  download PNG/SVG). If "Save my interview report" is ticked it is also saved in Studio.
- Failures (e.g. free-limit reached) are shown honestly on screen; the same topic can be tried again later.
- Tests: agent/tests/test_live_diagrams.py (5 tests; only the Gemini call is replaced). Total now 52 tests, all passing.
