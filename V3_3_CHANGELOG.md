# ST310 Street Finest Portal — V3.3

## Added
- Student Services gateway after choosing Student: **Register for ST310** and **Choose Your Seminar**.
- Before saving a new registration: **Review Your Details** with Edit/Confirm buttons.
- After successful registration: **Choose Your Seminar**.
- Existing students can find their own record using **Reg No + all names**. No second registration is created.
- Exactly one seminar assignment stored on each student record: MON 16:00–16:55 ALRC, THU 10:00–10:55 ALRB, FRI 18:00–18:55 ALRD.
- Re-selection rejected; a student with a selected seminar sees **Request Seminar Shift**, can choose a different seminar and explain why.
- At most one pending shift request per student. The current group does not change while pending.
- Master Admin reviews and approves/rejects shift requests. When approved, the existing seminar field is updated atomically; the student never belongs to both groups.
- Master Admin seminar overview, counts, and Excel exports: **All 3 seminar groups in one workbook (3 sheets)** or **one group per workbook**, three data columns: Student Names, Registration Number, Course. Sorted by programme and student name.
- CR summary counts and a seminar column on its complete searchable, scrollable student list; CR continues to approve only the whole programme.
- Master Admin student record correction (names, registration number, programme, seminar), with duplicate checks and audit event. Name/reg/programme edits reset only affected CR approvals; seminar-only edits do not.
- Master Admin screens adapt to PC width while preserving the same original UDSM/Street Finest navy-gold artwork and footer.

## Preserved
- The original Welcome/Role reference artwork and all existing branding assets.
- All previous student registrations, CR accounts, duplicate-check rules, original detailed and submission exports, PDF exports, approval flow and Render persistent-disk configuration.
- No demo records, production credentials or database file included in the release.

## QA done
- Python compile and JavaScript syntax checks.
- Backend integration tests: first-choice lock, identical and approximate-name duplicate blocking, shift request/approval, double-submit refusal, admin edits, protected Excel exports and three worksheet structure.
- Migration from an existing V3.2 database preserving students, CR approvals and audit history; repeated migration unchanged.
- 30 concurrent unique seminar assignments: 30/30 succeeded, exactly one seminar per student.
- Frontend code rendering smoke test: 20 routes rendered in a simulated DOM.

## QA not yet done
- Real-browser pixel-level checks and actual phone/PC visual inspection. The current headless browser environment blocked navigation, including localhost and local-file pages. A final manual review on actual devices is required before public promotion.
- Live Render/Cloudflare network and load checks. No live data has been touched by this package.
