# ST310 Street Finest — clean deployment checklist

This package is source-only. It contains **no local SQLite student database, no student registrations, no saved admin passwords, no test-suite fixtures, and no demo-mode records**. Production preview mode is disabled. A fresh persistent disk initializes the database with zero students, zero CRs and registration **closed**.

## Before connecting GitHub

- Create a **private** GitHub repository and upload the **contents** of this directory, so `main.py`, `render.yaml`, `requirements.txt`, and `static/` are in the repo root.
- Never upload `.env`, `.local_credentials.txt`, `st310.sqlite3`, `st310.sqlite3-wal`, `st310.sqlite3-shm`, `.venv`, or any old local database.
- Do not upload the ZIP file itself and expect Render to run it.

## Render deployment

1. Open https://dashboard.render.com and use **New → Blueprint**.
2. Link your private GitHub repository and select `render.yaml` from its root.
3. Review the service: Python, Starter plan, **one worker**, **1 GB persistent disk** at `/var/data`.
4. Supply each private `sync: false` secret when asked: strong `ADMIN_PASSWORD`, different private `CR_INVITE_MATH`, `CR_INVITE_BAEST`, `CR_INVITE_BAST`. The blueprint generates `APP_SECRET_KEY`.
5. Verify `DB_PATH=/var/data/st310.sqlite3` and `INITIAL_REGISTRATION_OPEN=0`.
6. Once live, check `https://YOUR-SERVICE.onrender.com/api/health` and sign into Master Admin. Confirm **0 students**, all CRs unregistered, and **registration closed**. Keep registration closed until the production launch.
7. Run any throwaway registration tests only in a separate local/staging database, not in the production database. If you accidentally register fake students in production, verify cleanup through an authenticated admin review before opening enrolment.
8. Configure routine database backups and access restrictions. When ready, issue the CR invite codes separately and **open registration** in the Master Admin dashboard.

**Warning:** Render persistent disks are not the same as managed database backups. Arrange backups. The paid Starter service and disk can incur charges. A public site using university logos should be clearly presented as an independently organized student class list, not an official university system.

## Submission Excel (V3.2)

Once all three CRs and the Master Admin have approved the final class list, open Master Admin and choose **Export Excel for Submission**. This generates one sheet with exactly three data columns: STUDENT NAMES, REGISTRATION NUMBER, COURSE. Student names combine surname, first name and optional second name. Records are grouped MATH, BAEST, BAST, and alphabetized within each group. Existing detailed Excel and PDF exports remain available.

## Expected registration traffic

One always-on Render Starter instance + one persistent SQLite disk is the least complicated deployment for a typical class list. The application uses SQLite WAL and BEGIN IMMEDIATE for atomic writes, and each request has a 30-second busy timeout. Concurrent local tests are included in the release QA results but are *not* a guarantee of network latency or uptime under all conditions. Test on the paid deployed service before sending the link to students, and upgrade to Render Standard if CPU metrics or response times require it. A Render persistent disk prevents horizontal scaling and adds a short service interruption during redeploys. Back up the database regularly and keep registration closed until verification is complete.
