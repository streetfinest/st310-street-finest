"""V3.3 -> V4.0 additive migration against 111 fake student registrations.
Never touches live data. Uses the archived V3.3 backend on the current machine when
available; otherwise prints a clear SKIP rather than claiming a real migration test.
"""
from pathlib import Path
import os,sqlite3,subprocess,sys,tempfile,shutil
ROOT=Path(__file__).resolve().parents[1]
OLD=Path(os.environ.get('ST310_V33_SOURCE',''))
if not OLD.is_file() and not (OLD/'main.py').is_file():
    OLD=Path('/mnt/data/ST310_StreetFinest_V3_3_FULL.zip')
with tempfile.TemporaryDirectory(prefix='st310-migration-') as td:
    target=Path(td)
    original=target/'old';original.mkdir()
    if OLD.suffix=='.zip':
        import zipfile
        with zipfile.ZipFile(OLD) as z:z.extractall(original)
    elif (OLD/'main.py').exists():
        shutil.copytree(OLD,original,dirs_exist_ok=True)
    else:
        print('SKIP: archived V3.3 source not available in this environment')
        sys.exit(0)
    DB=target/'db.sqlite3'
    ENV={**os.environ,'DB_PATH':str(DB),'ADMIN_PASSWORD':'migration-test-secret','ADMIN_USERNAME':'admin','INITIAL_REGISTRATION_OPEN':'0','CR_INVITE_MATH':'testinvite','CR_INVITE_BAEST':'testinvite2','CR_INVITE_BAST':'testinvite3'}
    subprocess.run([sys.executable,'-c','import main'],cwd=original,env=ENV,check=True,capture_output=True)
    conn=sqlite3.connect(DB)
    for i in range(111):
        num=f'2024-04-{10000+i:05d}'
        conn.execute('INSERT INTO students(reg_key,registration_number,surname,first_name,second_name,programme,created_at,seminar_code) VALUES(?,?,?,?,?,?,?,?)',
                     (num.replace('-',''),num,'TESTSURNAME'+str(i),'FIRST'+str(i),'THIRD'+str(i),
                     ['MATH','BAEST','BAST'][i%3],'2026-11-10T12:00:00+00:00',['MON','THU','FRI',None][i%4]))
    conn.execute("UPDATE programme_status SET revision=2,cr_approved_at='2026-11-10T12:00:00+00:00',cr_approved_revision=2")
    conn.execute("INSERT INTO audit_events(actor,event,detail,timestamp) VALUES('test','TEST_AUDIT','keep','2026-11-10T12:00:00+00:00')")
    conn.commit()
    before={'students':conn.execute('SELECT COUNT(*) FROM students').fetchone()[0],
            'approved':conn.execute('SELECT COUNT(*) FROM programme_status WHERE cr_approved_at IS NOT NULL').fetchone()[0],
            'audit':conn.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0],
            'seminars':conn.execute('SELECT seminar_code,COUNT(*) FROM students GROUP BY seminar_code ORDER BY seminar_code').fetchall()}
    assert before['students']==111 and before['approved']==3
    conn.close()
    for i in range(2):
        result=subprocess.run([sys.executable,'-c','import main'],cwd=ROOT,env=ENV,capture_output=True,text=True)
        if result.returncode!=0:raise RuntimeError('V4 migration failed: '+result.stderr)
        conn=sqlite3.connect(DB)
        after={'students':conn.execute('SELECT COUNT(*) FROM students').fetchone()[0],
               'approved':conn.execute('SELECT COUNT(*) FROM programme_status WHERE cr_approved_at IS NOT NULL').fetchone()[0],
               'audit':conn.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0],
               'seminars':conn.execute('SELECT seminar_code,COUNT(*) FROM students GROUP BY seminar_code ORDER BY seminar_code').fetchall()}
        assert after==before, (before,after)
        assert conn.execute('SELECT COUNT(*) FROM hub_courses WHERE legacy=1 AND code=?',('ST310',)).fetchone()[0]==1
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        conn.close()
    print('PASS: V3.3 -> V4.0 additive migration, 111 fake students, 3 CR approvals, seminars, audit, repeat initialization')
