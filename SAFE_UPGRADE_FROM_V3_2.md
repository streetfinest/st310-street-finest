# ST310 Street Finest V3.3 — SAFE update from the current LIVE V3.2

**Do not reset or re-create the Render service or disk. Never delete `/var/data/st310.sqlite3`.**

This release uses the existing Render service, single Python worker, and attached SQLite disk. It changes only code and static assets. Cloudflare Worker configuration and public website links stay unchanged.

## 1. Verify the production DB and make a consistent backup BEFORE committing

Open **Render > st310-street-finest > Shell**, then paste the following entire command. It copies a consistent snapshot using SQLite's backup API (safe even with WAL mode). The backup is created under the persistent mount.

```bash
python - <<'PY'
import sqlite3, pathlib, datetime, os
source=pathlib.Path(os.getenv('DB_PATH','/var/data/st310.sqlite3'))
if not source.is_file():
    raise SystemExit('STOP: database not found at '+str(source))
folder=source.parent/'backups'
folder.mkdir(parents=True,exist_ok=True)
out=folder/('ST310_BEFORE_V33_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'.sqlite3')
with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as original:
    with sqlite3.connect(out) as backup:
        original.backup(backup)
    count=original.execute('SELECT COUNT(*) FROM students').fetchone()[0]
with sqlite3.connect(out) as check:
    integrity=check.execute('PRAGMA integrity_check').fetchone()[0]
    saved=check.execute('SELECT COUNT(*) FROM students').fetchone()[0]
print('BACKUP FILE:',out)
print('STUDENTS LIVE:',count,'STUDENTS BACKUP:',saved,'INTEGRITY:',integrity)
if integrity!='ok' or count!=saved:raise SystemExit('STOP: backup verification failed')
PY
```

**Important:** A copy on the same disk is **not** an off-site backup. Copy the verified backup to your computer or another secure location using Render's supported file transfer process; protect it because it contains student data. Check the Render documentation on persistent disks and file transfer. Never push the database or backup to your GitHub source repository. If your Render account cannot transfer files easily, arrange an independent backup before applying a live migration.

Record the exact **live student count**, **CR approval statuses**, and **registration open/closed state** from Master Admin; compare after deployment.

## 2. Upload updated code to GitHub — but not the database

From the V3.3 patch ZIP, replace exactly these files in your existing **private** GitHub repository, preserving the paths:

- `main.py`
- `static/assets/app.js`
- `static/assets/styles.css`
- `static/index.html`

The full project ZIP is also provided if you prefer replacing the source-tree contents. Keep your `render.yaml`, disk mount, admin credentials and Cloudflare Worker unchanged. Do **not** upload a `.sqlite3`, `.sqlite3-wal`, `.sqlite3-shm`, `.env` or `.local_credentials.txt` file.

The existing Render setting **Auto-Deploy: On Commit** will deploy the updated code after GitHub commit. Deployments of disk-backed services can involve a short interruption. Choose a quiet period.

## 3. How the database migration works

On startup `setup()` retains old tables and values, then `migrate_v33()` runs an **additive transaction**:

- Adds nullable `students.seminar_code` if missing; existing students start as `NULL` (**Not selected**).
- Creates `seminar_shift_requests` to store pending and reviewed change requests, with a UNIQUE index allowing **only one pending request per student**.
- Preserves student IDs, registrations, existing CR accounts, approval status, existing audit rows, and export endpoints.
- Migration is idempotent: restarting or redeploying doesn't duplicate rows or reset seminar assignments.

Do not run any scripts that drop or recreate the database.

## 4. Verify production before inviting students

- Confirm `https://st310-street-finest.onrender.com/api/health` responds with `healthy`.
- Log in as Master Admin: registered count **must match the pre-deploy number**.
- Open **Seminar Management**: existing students appear under **Not selected** until they choose one; group counts initially 0 unless V3.3 data exists.
- Confirm the three groups: Monday 16:00–16:55 ALRC, Thursday 10:00–10:55 ALRB, Friday 18:00–18:55 ALRD.
- Test the student workflow **on staging with dummy records**, not production; verify first assignment, refusal of another direct assignment, pending shift request, Admin approve/reject, Excel exports, admin edits, and mobile/desktop layouts.
- Confirm CR Dashboard still has **one programme approval button** and the full list is scrollable.
- Ensure the Cloudflare Worker public link continues to reach the Render backend and `/api/health`.

## 5. Rollback guidance

If the new UI fails, revert the GitHub commit to V3.2 and let Render deploy the previous code. The additive V3.3 database columns/tables remain on disk, so older code can continue reading its old fields. **Do not delete or restore the production database casually.** Restoring old snapshots can lose data registered after that snapshot. Preserve the verified off-site database backup.

## Security limitation of the agreed Option B

Existing students use **registration number + all names** to access seminar selection and request a shift. These are not secret credentials. A person who knows another student's details could impersonate them, so requests must be reviewed by Master Admin and this access cannot edit personal records. For stronger identity assurance later, switch to private student PINs or authenticated university login.
