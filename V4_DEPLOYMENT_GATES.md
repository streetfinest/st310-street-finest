# Production release gates — Street Finest Academic Hub V4.0

## Required before merging/deployment

- [ ] Confirm which version is currently deployed on Render (`main` may still be V3.2; a green V3.3 PR alone does not make it live).
- [ ] Confirm Render production has auto-deploy disabled before any merge to `main`.
- [ ] Confirm V4 GitHub Actions pass on `v4-prep` and actual PR diff includes `hub_v4.py`, `main.py`, frontend assets, `Dockerfile`, requirements, tests, and retains ST310 V3.3 assets.
- [ ] Confirm V4 staging uses its own test DB, *not* the production persistent disk. Test public home and all pages at phone and PC widths (no phone device border in the browser page).
- [ ] Confirm legacy `/st310` page renders, legacy student register/login, CR, Master Admin, PDF/Excel exports, seminars and existing shift requests work against controlled test data.
- [ ] Check names and 11-digit format `XXXX-04-XXXXX`, exact and fuzzy duplicate behaviour, and one seminar per course.
- [ ] Verify user-submitted strings are escaped on frontend and export cells are protected against formula injection.
- [ ] Verify independent production DB backup off Render disk, with `PRAGMA integrity_check='ok'`, student count and CR approval records.
- [ ] Confirm `HUB_UPLOAD_DIR=/var/data/hub_uploads` (or another persistent path), enough disk space and backup policy for uploaded files.
- [ ] Confirm secrets and tokens are not committed; staging uses different credentials.
- [ ] Review weak Registration Number + Full Names lookup risks before broad rollout.

## Post-release

- [ ] Compare counts in legacy `students`, `cr_accounts`, `programme_status`, `audit_events`, and `seminar_shift_requests` before/after deployment.
- [ ] Confirm ST310 original data and CR approvals are untouched.
- [ ] Confirm homepage returns V4, `/st310` returns old ST310 portal and Cloudflare Worker passes both paths and new `/api/hub/*` requests.
- [ ] Test a new dummy V4 course only on staging; do not pollute production with test students.
- [ ] Document exact rollback commits, storage backup, and restart strategy.

Automatic SQLite migrations are additive, but deployment should always be treated as a production change with rollback procedures.
