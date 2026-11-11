# STREET FINEST Academic Hub — V4.0 Development Preview

**Status: STAGING CANDIDATE — NOT APPROVED FOR LIVE PRODUCTION.**

This is a working modular extension of **ST310 Street Finest V3.3** (not a new or separate student database).

## What is included

- Universal student homepage with exactly four cards: Course Registrations, Academic Hub, Announcements, Opportunities.
- Public registration portals published by Master Admin, plus **My Registrations** lookup by course, Registration Number, Surname, First Name, and optional Third/Second Name.
- ST310 records displayed directly from existing `students` table. ST310 classic UI remains at `/st310` and its Admin/CR/existing seminars continue to work.
- New course registrations use a **separate table** keyed uniquely by `(course_id, reg_key)`, supporting the same person in different courses while preventing duplicates in one course.
- One seminar per new-course registration; student shift request remains pending until Master Admin approval.
- Master Admin: create/edit/publish/close/archive registrations; hide/show ST310 public card without deleting legacy records; verified-student override for legitimate name collisions and enrolment correction with audit; per-course Excel; group-by-seminar workbook; materials course manager with file upload; announcement editor/publisher; opportunities editor/publisher; homepage text and four-card visibility/order; pending shift review.
- Frontend is **CSS/HTML responsive webpage only**. Smartphone frames, notches, phone housings and device artwork are *not* coded as page elements.

## Core architecture

- `main.py`: unchanged V3.3 API routes plus explicit module setup and new `/` vs `/st310` routing.
- `hub_v4.py`: V4 additive schema and public/admin APIs.
- `static/hub.html`, `static/assets/hub.js`, `static/assets/hub.css`: new universal responsive website.
- `static/assets/hub-campus.webp`: cropped from the established ST310 image design asset; matching UDSM crest, gateway, navy-gold plaque, glass card and Street Finest footer are used in CSS/HTML.
- `static/index.html`, `static/assets/app.js`, `styles.css`: classic V3.3 interface retained.
- `Dockerfile`: includes `hub_v4.py`.
- `requirements.txt`: adds `python-multipart` for file uploads.

## Starting locally

```bash
python -m pip install -r requirements.txt 'httpx>=0.27,<1'
# Set DB_PATH to an isolated staging file (do NOT point to /var/data/st310.sqlite3 on your PC):
export DB_PATH=/tmp/street-finest-v4-staging.sqlite3
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='CHANGE-THIS-STAGING-PASSWORD'
uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000/` for Academic Hub. `http://127.0.0.1:8000/st310` opens the classic ST310 frontend. Admin access is via Academic Hub footer (or `/#admin-login`).

On Windows PowerShell set environment variables using `$env:DB_PATH='...'` instead of `export`.

## File upload storage

Set `HUB_UPLOAD_DIR` to a path on Render's **persistent disk**, e.g. `/var/data/hub_uploads`. If unset, files are stored beside the configured SQLite DB. **Do not use `/tmp` in production**. Upload types: PDF, PPTX, DOCX, XLSX, PNG, JPG, max 15 MB each. Only authenticated Master Admin may upload.

Staging with Free plan has ephemeral storage: dummy files and registrations can disappear across restarts.

## Development tests

```bash
python tests/test_hub_v4.py
node --check static/assets/hub.js
node tests/check_frontend_render.cjs
```

`tests/test_legacy_migration.py` verifies repeated V3.3→V4 migrations, and `tests/test_v32_to_v4.py` tests V3.2→V4 migrations, each with 111 **synthetic** student records. Both passed locally against archived V3.x source. These historical-source tests print `SKIP` rather than pretending to test absent archives when run on GitHub.

We verified 14 page templates, exercised mobile navigation under a mocked API with a headless browser, and confirmed mobile renders at 390px with no horizontal overflow and no simulated smartphone housing. Browser navigation to the live backend was blocked by this environment; real staging browser screenshots, clicks and accessibility review are still mandatory before release.

## Important boundaries

1. ST310 V3.3 CR accounts and CR approvals remain in the classic module. **Creating CR roles for new V4 courses is not implemented yet**. Do not assume generic courses support CR sign-off.
2. Legacy ST310 *formal final approval* and 3-column submission export remain under `/st310`, not recreated in the generic course export.
3. Identity verification based only on registration number and names is **weak**. We implemented short-lived lookup tokens and basic rate limiting, but strong student access (OTP / school-linked login) is recommended before broad rollout.
4. The original live database is **not included in this package**. All tests used dummy data.
5. The V4 course database is additive, but this is still a major UI and server release. Keep V3.3 as rollback path and take **verified off-site backup** before production.

## Safe staged deployment plan

1. Do **not** overwrite the working production GitHub `main` branch now.
2. Create `v4-prep` from your actual GitHub production branch. Upload this full project source into `v4-prep`; keep the `.github/workflows` and `tests` folders with correct paths.
3. Create or reuse **a separate Render staging service** on `v4-prep`, using a fresh temporary `DB_PATH` and new staging passwords. Note: if this branch includes V3.3 but production is still V3.2, the initial staging test must cover both migrations.
4. Wait for the GitHub V4 preflight green; manually test mobile and desktop, all admin pages, ST310 legacy, file downloads, Excel, and duplicate/shift scenarios.
5. Verify a current **independent backup** of production `/var/data/st310.sqlite3` outside Render and record current student count/approvals. No live dummy registrations.
6. Only after approval: merge through reviewed PR, deploy in a controlled window, verify row counts and database integrity; preserve the original `/st310` route and rollback plan.

**Not deployed, merged or published by this package.**
