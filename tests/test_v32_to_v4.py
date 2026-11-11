"""Verify an actual V3.2 schema upgrades through V3.3 to V4 without losing rows.

Uses the archived V3.2 backend when available. This test deliberately has no real
student information: its 111 generated students and CR approvals are synthetic.
"""
from pathlib import Path
import os,sqlite3,subprocess,sys,tempfile

ROOT=Path(__file__).resolve().parents[1]
OLD=Path(os.environ.get('ST310_V32_SOURCE','/mnt/data/ST310_Production_Ready_V3_2'))
if not (OLD/'main.py').is_file():
    print('SKIP: exact archived V3.2 source not available; run V4 test suite instead')
    sys.exit(0)

with tempfile.TemporaryDirectory(prefix='st310-v32-to-v4-') as temp:
    DB=Path(temp)/'st310-synthetic.sqlite3'
    env={**os.environ,'DB_PATH':str(DB),'ADMIN_PASSWORD':'test-unique-password',
         'ADMIN_USERNAME':'admin','INITIAL_REGISTRATION_OPEN':'0',
         'CR_INVITE_MATH':'mat-test','CR_INVITE_BAEST':'baest-test','CR_INVITE_BAST':'bast-test',
         'HUB_UPLOAD_DIR':str(Path(temp)/'uploads')}
    subprocess.run([sys.executable,'-c','import main'],cwd=OLD,env=env,check=True,capture_output=True)
    c=sqlite3.connect(DB)
    for i in range(111):
        reg=f'2024-04-{10000+i:05d}'
        c.execute('INSERT INTO students(reg_key,registration_number,surname,first_name,second_name,programme,created_at) VALUES(?,?,?,?,?,?,?)',
                  (reg.replace('-',''),reg,f'SYNTHETIC{i}','STUDENT',f'NAME{i}',('MATH','BAEST','BAST')[i%3],
                   '2026-11-11T00:00:00+00:00'))
    c.execute("UPDATE programme_status SET revision=2,cr_approved_at='2026-11-11T00:00:00+00:00',cr_approved_revision=2")
    c.execute("INSERT INTO audit_events(actor,event,detail,timestamp) VALUES('test','SYNTHETIC_AUDIT','keep','2026-11-11T00:00:00+00:00')")
    c.commit()
    expected={
      'student_count':c.execute('SELECT COUNT(*) FROM students').fetchone()[0],
      'approval_count':c.execute('SELECT COUNT(*) FROM programme_status WHERE cr_approved_at IS NOT NULL').fetchone()[0],
      'audit_count':c.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0],
      'students':c.execute('SELECT reg_key,registration_number,surname,first_name,second_name,programme,created_at FROM students ORDER BY id').fetchall()
    }
    c.close()
    for attempt in (1,2):
        completed=subprocess.run([sys.executable,'-c','import main'],cwd=ROOT,env=env,capture_output=True,text=True)
        if completed.returncode:
            raise AssertionError(f'V4 boot failed on migration pass {attempt}: {completed.stderr}')
        c=sqlite3.connect(DB)
        assert c.execute('SELECT COUNT(*) FROM students').fetchone()[0]==expected['student_count']
        assert c.execute('SELECT COUNT(*) FROM programme_status WHERE cr_approved_at IS NOT NULL').fetchone()[0]==expected['approval_count']
        assert c.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]==expected['audit_count']
        assert c.execute('SELECT reg_key,registration_number,surname,first_name,second_name,programme,created_at FROM students ORDER BY id').fetchall()==expected['students']
        assert c.execute('SELECT COUNT(*) FROM hub_courses WHERE legacy=1 AND code="ST310"').fetchone()[0]==1
        assert 'seminar_code' in {row[1] for row in c.execute('PRAGMA table_info(students)')}
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        c.close()
    print('PASS: archived V3.2 -> V4.0 migration twice, 111 synthetic students, CR approvals, audit and rows unchanged')
