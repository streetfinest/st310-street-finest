# Deploy STREET FINEST V4.0 to staging first

**Do NOT replace production now.** Keep existing Render `st310-street-finest` and its persistent disk unchanged.

1. In your private GitHub repo `streetfinest/st310-street-finest`, create **`v4-prep`** as a separate branch. Ensure it includes the V3.3 changes (if V3.3 is not yet merged to `main`, base it on `v3.3-prep`).
2. Extract the **FULL** V4 zip and upload its **contents**, retaining the paths in the ZIP. Root paths must include `main.py`, `hub_v4.py`, `Dockerfile`, `requirements.txt`, `static/`, `tests/`, `.github/workflows/street-finest-v4-preflight.yml`.
3. **Never upload** any `.sqlite3`, `.env`, `.local_credentials.txt`, `-wal`, `-shm`, real student data or secrets to GitHub.
4. Confirm GitHub Actions **Street Finest V4.0 preflight** is green on the `v4-prep` branch; inspect the test steps, not only the check icon.
5. In Render, create/adjust a **separate staging** web service using Docker, pointing to branch `v4-prep`. Use new staging-only secrets and `DB_PATH=/tmp/st310-v4-staging.sqlite3` and `HUB_UPLOAD_DIR=/tmp/st310-v4-materials`, **not** `/var/data/st310.sqlite3` on the production server. Staging tests use synthetic student records and fake files.
6. Visit staging `/` (universal Hub), `/st310` (old portal), and `/#admin-login` (new Admin). Test phone and desktop, all four public cards, course portal creation, lookup, seminar shift and approval, material upload and download, notices, opportunities, homepage settings and protected exports. No physical phone frame should be visible inside the page.
7. Before any production change, confirm which version is currently on production, disable auto-deploy, obtain and verify an **independent off-site backup** of the live DB, preserve the current student count and CR approvals, and agree on rollback steps. A backup on the same Render persistent disk is not sufficient against disk loss.
8. Once approved, use a controlled reviewed PR/merge/deploy window on your **existing production service** and compare actual database counts before/after. There must be no database replacement and no creation of a second production persistent disk.

**Important:** This is a staged code release only. It is not a claim that a live Render deployment or production migration has been performed.
