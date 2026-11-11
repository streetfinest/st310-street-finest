"""Street Finest Academic Hub V4.0 — additive modules beside the original ST310 app.

Never modifies or deletes original ST310 tables. Legacy ST310 remains available via
its original endpoints and /st310 browser route. Run against a test DB before
upgrading an existing deployment.
"""

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import zipfile
from collections import defaultdict
from urllib.parse import urlparse

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def install(app, *, db, DB_PATH, PROGRAMMES, ACADEMIC_YEAR, auth, required_role,
            token_encode, reg_key, name_val, normalized_name, similarity_kind,
            validate_person, audit, fetch_setting, set_setting, now_iso):
    """Register V4 routes. Dependencies passed explicitly; no circular imports."""
    MEDIA_DIR = Path(os.environ.get('HUB_UPLOAD_DIR',str(DB_PATH.parent / 'hub_uploads'))).resolve()
    public_sections = ('registrations','materials','announcements','opportunities')
    default_home = {'title':'Street Finest Academic Hub',
                    'subtitle':'Your Gateway to Academic Services & Opportunities',
                    'sections':list(public_sections)}
    def jd(value):
        try: return json.loads(value)
        except (ValueError, TypeError): return []

    def setup_hub():
        conn=db()
        try:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS hub_courses (
                  id INTEGER PRIMARY KEY,code TEXT NOT NULL,title TEXT NOT NULL,
                  academic_year TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL CHECK(status IN ('draft','open','closed','archived')),
                  programmes TEXT NOT NULL,legacy INTEGER NOT NULL DEFAULT 0,
                  seminar_enabled INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,updated_at TEXT NOT NULL,visible INTEGER NOT NULL DEFAULT 1,
                  UNIQUE(code,academic_year)
                );
                CREATE TABLE IF NOT EXISTS hub_seminars (
                  id INTEGER PRIMARY KEY,course_id INTEGER NOT NULL REFERENCES hub_courses(id),
                  label TEXT NOT NULL,day TEXT NOT NULL,start_time TEXT NOT NULL,
                  end_time TEXT NOT NULL,venue TEXT NOT NULL,
                  UNIQUE(course_id,label)
                );
                CREATE TABLE IF NOT EXISTS hub_enrollments (
                  id INTEGER PRIMARY KEY,course_id INTEGER NOT NULL REFERENCES hub_courses(id),
                  reg_key TEXT NOT NULL,registration_number TEXT NOT NULL,
                  surname TEXT NOT NULL,first_name TEXT NOT NULL,second_name TEXT NOT NULL DEFAULT '',
                  programme TEXT NOT NULL,seminar_id INTEGER REFERENCES hub_seminars(id),
                  created_at TEXT NOT NULL,UNIQUE(course_id,reg_key)
                );
                CREATE INDEX IF NOT EXISTS hub_enrollments_lookup ON hub_enrollments(course_id,reg_key);
                CREATE TABLE IF NOT EXISTS hub_shifts (
                  id INTEGER PRIMARY KEY,course_id INTEGER NOT NULL REFERENCES hub_courses(id),
                  enrollment_id INTEGER NOT NULL REFERENCES hub_enrollments(id),
                  from_seminar_id INTEGER NOT NULL REFERENCES hub_seminars(id),
                  to_seminar_id INTEGER NOT NULL REFERENCES hub_seminars(id),
                  reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                  created_at TEXT NOT NULL,reviewed_at TEXT,review_note TEXT,
                  CHECK(from_seminar_id <> to_seminar_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS hub_one_pending_shift ON hub_shifts(enrollment_id) WHERE status='pending';
                CREATE TABLE IF NOT EXISTS hub_material_courses (
                  id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,title TEXT NOT NULL,
                  description TEXT NOT NULL DEFAULT '',visible INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hub_materials (
                  id INTEGER PRIMARY KEY,course_id INTEGER NOT NULL REFERENCES hub_material_courses(id),
                  title TEXT NOT NULL,topic TEXT NOT NULL,kind TEXT NOT NULL,
                  file_name TEXT NOT NULL,storage_key TEXT NOT NULL,
                  file_size INTEGER NOT NULL,visible INTEGER NOT NULL DEFAULT 1,
                  uploaded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hub_notices (
                  id INTEGER PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,
                  category TEXT NOT NULL,course_code TEXT NOT NULL DEFAULT '',
                  published INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hub_opportunities (
                  id INTEGER PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,
                  category TEXT NOT NULL,deadline TEXT NOT NULL DEFAULT '',
                  url TEXT NOT NULL DEFAULT '',published INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hub_homepage (
                  id INTEGER PRIMARY KEY CHECK(id=1),title TEXT NOT NULL,
                  subtitle TEXT NOT NULL,sections TEXT NOT NULL
                );
            ''')
            cols={r['name'] for r in conn.execute('PRAGMA table_info(hub_courses)')}
            if 'visible' not in cols:conn.execute('ALTER TABLE hub_courses ADD COLUMN visible INTEGER NOT NULL DEFAULT 1')
            conn.execute('BEGIN IMMEDIATE')
            # ST310 stays a *view* of the real legacy database. No old row is copied.
            if not conn.execute("SELECT id FROM hub_courses WHERE legacy=1 AND code='ST310'").fetchone():
                conn.execute('''INSERT OR IGNORE INTO hub_courses
              (code,title,academic_year,description,status,programmes,legacy,seminar_enabled,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?)''',
              ('ST310','Statistical Inference II',ACADEMIC_YEAR,'Third Year Student Registration',
               'closed',json.dumps(list(PROGRAMMES)),1,1,now_iso(),now_iso()))
            conn.execute('INSERT OR IGNORE INTO hub_homepage(id,title,subtitle,sections) VALUES (1,?,?,?)',
                         (default_home['title'],default_home['subtitle'],json.dumps(default_home['sections'])))
            conn.execute('COMMIT')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()
    setup_hub()

    def trimmed(v:str, label:str, limit=180,required=True):
        result=' '.join(v.split()).strip()
        if (required and not result) or len(result)>limit:
            raise HTTPException(422,f'Provide a valid {label} (max {limit} characters).')
        return result
    def course_dict(conn,row):
        data=dict(row)
        data['programmes']=jd(data['programmes'])
        if data['legacy']:
            data['status']='open' if fetch_setting(conn,'registration_open')=='1' else 'closed'
            data['count']=conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]
            data['seminars']=[{'id':s['code'],'label':s['label'],'day':s['day'],'start_time':s['time'].split('–')[0],
                              'end_time':s['time'].split('–')[-1],'venue':s['venue']} for s in (
                {'code':'MON','label':'Monday Seminar','day':'Monday','time':'16:00–16:55','venue':'ALRC'},
                {'code':'THU','label':'Thursday Seminar','day':'Thursday','time':'10:00–10:55','venue':'ALRB'},
                {'code':'FRI','label':'Friday Seminar','day':'Friday','time':'18:00–18:55','venue':'ALRD'})]
        else:
            data['count']=conn.execute('SELECT COUNT(*) FROM hub_enrollments WHERE course_id=?',(row['id'],)).fetchone()[0]
            data['seminars']=[dict(r) for r in conn.execute('SELECT id,label,day,start_time,end_time,venue FROM hub_seminars WHERE course_id=? ORDER BY id',(row['id'],))]
        return data
    def lookup_course(conn,course_id):
        row=conn.execute('SELECT * FROM hub_courses WHERE id=?',(course_id,)).fetchone()
        if not row:raise HTTPException(404,'Course not found.')
        return row
    def require_writable(row):
        if row['legacy']:
            raise HTTPException(409,'ST310 is managed by the existing V3.3 tools. Its student records are protected.')
    def ensure_access_course(conn,cid):
        row=lookup_course(conn,cid)
        if row['status']=='draft' or row['status']=='archived':
            if not row['legacy']:raise HTTPException(404,'Course not available.')
        return row
    def validate_seminar(conn,course_id,seminar_id):
        row=conn.execute('SELECT * FROM hub_seminars WHERE id=? AND course_id=?',(seminar_id,course_id)).fetchone()
        if row is None:raise HTTPException(422,'Choose a seminar for this course.')
        return row
    def safe_filename(name):
        return Path(str(name)).name.replace('\x00','')[:160]
    def check_external_url(url):
        if not url:return ''
        u=urlparse(url)
        if u.scheme!='https' or not u.netloc or u.username or u.password:
            raise HTTPException(422,'Only full HTTPS opportunity links are allowed.')
        return url

    class CourseForm(BaseModel):
        code:str=Field(min_length=2,max_length=20)
        title:str=Field(min_length=3,max_length=140)
        academic_year:str=Field(min_length=4,max_length=20)
        description:str=Field(default='',max_length=500)
        programmes:list[str]=Field(default_factory=lambda:list(PROGRAMMES))
        seminar_enabled:bool=False
        status:str='draft'
    class SeminarForm(BaseModel):
        label:str=Field(min_length=2,max_length=80)
        day:str=Field(min_length=3,max_length=20)
        start_time:str=Field(pattern=r'^\d{2}:\d{2}$')
        end_time:str=Field(pattern=r'^\d{2}:\d{2}$')
        venue:str=Field(min_length=2,max_length=80)
    class RegistrationForm(BaseModel):
        programme:str
        registration_number:str
        surname:str
        first_name:str
        second_name:str=''
    class LookupForm(BaseModel):
        course_id:int
        registration_number:str
        surname:str
        first_name:str
        second_name:str=''
    class SeminarPick(BaseModel):
        seminar_id:int
    class ShiftForm(BaseModel):
        to_seminar_id:int
        reason:str=Field(min_length=5,max_length=400)
    class ShiftReview(BaseModel):
        approve:bool
        note:str=Field(min_length=5,max_length=400)
    class MaterialCourseForm(BaseModel):
        code:str=Field(min_length=2,max_length=20)
        title:str=Field(min_length=3,max_length=140)
        description:str=Field(default='',max_length=500)
        visible:bool=True
    class NoticeForm(BaseModel):
        title:str=Field(min_length=3,max_length=170)
        body:str=Field(min_length=3,max_length=4000)
        category:str='General'
        course_code:str=''
        published:bool=False
    class OpportunityForm(BaseModel):
        title:str=Field(min_length=3,max_length=170)
        body:str=Field(min_length=3,max_length=4000)
        category:str='Internship'
        deadline:str=''
        url:str=''
        published:bool=False
    class HomeForm(BaseModel):
        title:str=Field(min_length=3,max_length=100)
        subtitle:str=Field(min_length=3,max_length=200)
        sections:list[str]

    @app.get('/api/hub/public')
    def public_hub():
        conn=db()
        try:
            home=conn.execute('SELECT title,subtitle,sections FROM hub_homepage WHERE id=1').fetchone()
            courses=[course_dict(conn,r) for r in conn.execute('SELECT * FROM hub_courses WHERE visible=1 ORDER BY legacy DESC,code') if r['status'] not in ('draft','archived') or r['legacy']]
            m_courses=[dict(r) for r in conn.execute('SELECT * FROM hub_material_courses WHERE visible=1 ORDER BY code')]
            notices=[dict(r) for r in conn.execute('SELECT * FROM hub_notices WHERE published=1 ORDER BY id DESC LIMIT 100')]
            opportunities=[dict(r) for r in conn.execute('SELECT * FROM hub_opportunities WHERE published=1 ORDER BY id DESC LIMIT 100')]
            return {'homepage':{'title':home['title'],'subtitle':home['subtitle'], 'sections':jd(home['sections'])},
                    'courses':courses,'material_courses':m_courses,'notices':notices,'opportunities':opportunities}
        finally:conn.close()

    @app.get('/api/hub/materials/{course_id}')
    def public_materials(course_id:int):
        conn=db()
        try:
            course=conn.execute('SELECT * FROM hub_material_courses WHERE id=? AND visible=1',(course_id,)).fetchone()
            if not course:raise HTTPException(404,'Course materials not published.')
            return {'course':dict(course),'materials':[dict(r) for r in conn.execute('''SELECT id,course_id,title,topic,kind,file_name,file_size,uploaded_at
                         FROM hub_materials WHERE course_id=? AND visible=1 ORDER BY topic,title''',(course_id,))]}
        finally:conn.close()

    @app.get('/api/hub/materials/file/{material_id}')
    def download_material(material_id:int):
        conn=db()
        try:
            row=conn.execute('''SELECT m.*,c.visible AS course_visible FROM hub_materials m
                JOIN hub_material_courses c ON c.id=m.course_id WHERE m.id=?''',(material_id,)).fetchone()
            if not row or not row['visible'] or not row['course_visible']:raise HTTPException(404,'Material not available.')
            f=MEDIA_DIR/row['storage_key']
            if not f.is_file():raise HTTPException(404,'Material file unavailable on this server.')
            from urllib.parse import quote
            filename=safe_filename(row['file_name'])
            return FileResponse(f,media_type='application/octet-stream',filename=filename,
                       headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
        finally:conn.close()

    _lookup_attempts=defaultdict(list)
    def limit_lookup(registration_number):
        # In-memory rate limiting is best-effort with one worker; production should use shared limits.
        key=reg_key(registration_number)
        now=time.monotonic()
        arr=[x for x in _lookup_attempts[key] if now-x<900]
        if len(arr)>=10:raise HTTPException(429,'Too many searches. Try again later.')
        arr.append(now);_lookup_attempts[key]=arr
        if len(_lookup_attempts)>20000:_lookup_attempts.clear()

    def enrollment_details(conn,row):
        r=dict(row)
        sem=(conn.execute('SELECT id,label,day,start_time,end_time,venue FROM hub_seminars WHERE id=?',(r['seminar_id'],)).fetchone() if r['seminar_id'] else None)
        shift=conn.execute('''SELECT sh.id,sh.status,sh.reason,sh.created_at,s.label AS target_label
                FROM hub_shifts sh JOIN hub_seminars s ON s.id=sh.to_seminar_id
                WHERE sh.enrollment_id=? AND sh.status='pending' ''',(r['id'],)).fetchone()
        r['seminar']=dict(sem) if sem else None
        r['pending_shift']=dict(shift) if shift else None
        return r
    def authorized_enrollment(conn,user):
        if user.get('role')!='hub_student':raise HTTPException(403,'Verify your registration first.')
        try:cid,sid=map(int,str(user['sub']).split(':',1))
        except (ValueError,TypeError):raise HTTPException(401,'Search your registration again.')
        row=conn.execute('SELECT * FROM hub_enrollments WHERE id=? AND course_id=?',(sid,cid)).fetchone()
        if not row:raise HTTPException(401,'Registration is no longer available.')
        return row

    @app.post('/api/hub/lookup')
    def lookup_registration(body:LookupForm):
        limit_lookup(body.registration_number)
        conn=db()
        try:
            course=ensure_access_course(conn,body.course_id)
            if not re.fullmatch(r'[0-9]{4}-04-[0-9]{5}',body.registration_number):
                raise HTTPException(422,'Use registration number XXXX-04-XXXXX.')
            table='students' if course['legacy'] else 'hub_enrollments'
            query='SELECT * FROM students WHERE reg_key=?' if course['legacy'] else 'SELECT * FROM hub_enrollments WHERE course_id=? AND reg_key=?'
            params=(reg_key(body.registration_number),) if course['legacy'] else (course['id'],reg_key(body.registration_number))
            row=conn.execute(query,params).fetchone()
            expected=tuple(normalized_name(row[k]) for k in ('surname','first_name','second_name')) if row else None
            got=tuple(normalized_name(getattr(body,k)) for k in ('surname','first_name','second_name'))
            if not expected or expected!=got:
                # Same message for non-existent students and incorrect credentials.
                return {'found':False,'message':'No matching registration found — No available services for you.'}
            if course['legacy']:
                sem_code=row['seminar_code']
                sem={'MON':{'id':'MON','label':'Monday Seminar','day':'Monday','start_time':'16:00','end_time':'16:55','venue':'ALRC'},
                     'THU':{'id':'THU','label':'Thursday Seminar','day':'Thursday','start_time':'10:00','end_time':'10:55','venue':'ALRB'},
                     'FRI':{'id':'FRI','label':'Friday Seminar','day':'Friday','start_time':'18:00','end_time':'18:55','venue':'ALRD'}}.get(sem_code)
                pending=conn.execute("SELECT id,to_code,status FROM seminar_shift_requests WHERE student_id=? AND status='pending'",(row['id'],)).fetchone()
                info={'id':row['id'],'registration_number':row['registration_number'],'surname':row['surname'],
                       'first_name':row['first_name'],'second_name':row['second_name'],
                       'programme':row['programme'],'created_at':row['created_at'],
                       'seminar':sem,'pending_shift':dict(pending) if pending else None}
                token=token_encode('student',str(row['id']),ttl=1200)
            else:
                info=enrollment_details(conn,row)
                token=token_encode('hub_student',f"{course['id']}:{row['id']}",ttl=1200)
            return {'found':True,'course':course_dict(conn,course),'registration':info,'student_token':token}
        finally:conn.close()

    @app.get('/api/hub/student/me')
    def student_self(user=Depends(auth)):
        conn=db()
        try:return {'registration':enrollment_details(conn,authorized_enrollment(conn,user))}
        finally:conn.close()

    @app.post('/api/hub/courses/{course_id}/register',status_code=201)
    def register_for_course(course_id:int,body:RegistrationForm):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            course=lookup_course(conn,course_id);require_writable(course)
            if course['status']!='open':raise HTTPException(403,'Course registration is closed.')
            p=validate_person(body)
            if p['programme'] not in jd(course['programmes']):raise HTTPException(422,'Your programme is not eligible for this course.')
            existing=conn.execute('SELECT reg_key,surname,first_name,second_name FROM hub_enrollments WHERE course_id=?',(course_id,))
            for r in existing:
                if r['reg_key']==p['reg_key']:raise HTTPException(409,'This registration number is already registered for this course.')
                if similarity_kind(r,p):raise HTTPException(409,'A very similar name is already registered for this course. Contact Master Admin if this is another student.')
            cur=conn.execute('''INSERT INTO hub_enrollments(course_id,reg_key,registration_number,surname,first_name,second_name,programme,created_at)
               VALUES(?,?,?,?,?,?,?,?)''',(course_id,p['reg_key'],p['registration_number'],p['surname'],p['first_name'],p['second_name'],p['programme'],now_iso()))
            audit(conn,'hub:'+p['reg_key'],'HUB_COURSE_REGISTERED',str(course_id))
            conn.execute('COMMIT')
            return {'registration':enrollment_details(conn,conn.execute('SELECT * FROM hub_enrollments WHERE id=?',(cur.lastrowid,)).fetchone()),
                    'student_token':token_encode('hub_student',f'{course_id}:{cur.lastrowid}',ttl=1200)}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'Student is already registered for this course.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/student/seminar')
    def choose_course_seminar(body:SeminarPick,user=Depends(auth)):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            enrollment=authorized_enrollment(conn,user)
            course=lookup_course(conn,enrollment['course_id'])
            if not course['seminar_enabled']:raise HTTPException(409,'Seminar selection is not enabled.')
            validate_seminar(conn,course['id'],body.seminar_id)
            if enrollment['seminar_id']:raise HTTPException(409,'You already selected a seminar. Use Request Shift.')
            conn.execute('UPDATE hub_enrollments SET seminar_id=? WHERE id=? AND seminar_id IS NULL',(body.seminar_id,enrollment['id']))
            audit(conn,str(enrollment['id']),'HUB_SEMINAR_SELECTED',str(body.seminar_id))
            conn.execute('COMMIT')
            return {'registration':enrollment_details(conn,conn.execute('SELECT * FROM hub_enrollments WHERE id=?',(enrollment['id'],)).fetchone())}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/student/shift',status_code=201)
    def request_course_shift(body:ShiftForm,user=Depends(auth)):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            r=authorized_enrollment(conn,user)
            if not r['seminar_id']:raise HTTPException(409,'Choose a seminar before requesting a shift.')
            if r['seminar_id']==body.to_seminar_id:raise HTTPException(409,'You are already in this seminar.')
            validate_seminar(conn,r['course_id'],body.to_seminar_id)
            if conn.execute("SELECT id FROM hub_shifts WHERE enrollment_id=? AND status='pending'",(r['id'],)).fetchone():
                raise HTTPException(409,'You already have a pending shift request.')
            reason=trimmed(body.reason,'shift reason',400)
            conn.execute('''INSERT INTO hub_shifts(course_id,enrollment_id,from_seminar_id,to_seminar_id,reason,created_at)
                VALUES(?,?,?,?,?,?)''',(r['course_id'],r['id'],r['seminar_id'],body.to_seminar_id,reason,now_iso()))
            audit(conn,str(r['id']),'HUB_SHIFT_REQUESTED',str(body.to_seminar_id))
            conn.execute('COMMIT')
            return {'registration':enrollment_details(conn,conn.execute('SELECT * FROM hub_enrollments WHERE id=?',(r['id'],)).fetchone())}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/overview')
    def admin_overview(user=Depends(required_role('admin'))):
        conn=db()
        try:
            courses=[course_dict(conn,r) for r in conn.execute('SELECT * FROM hub_courses ORDER BY legacy DESC,id DESC')]
            return {'courses':courses,'total_registrations':sum(x['count'] for x in courses),
                    'materials':conn.execute('SELECT COUNT(*) FROM hub_materials').fetchone()[0],
                    'announcements':conn.execute('SELECT COUNT(*) FROM hub_notices WHERE published=1').fetchone()[0],
                    'opportunities':conn.execute('SELECT COUNT(*) FROM hub_opportunities WHERE published=1').fetchone()[0],
                    'pending_shifts':conn.execute("SELECT COUNT(*) FROM hub_shifts WHERE status='pending'").fetchone()[0]+conn.execute("SELECT COUNT(*) FROM seminar_shift_requests WHERE status='pending'").fetchone()[0],
                    'recent':[dict(x) for x in conn.execute('SELECT event,timestamp FROM audit_events ORDER BY id DESC LIMIT 8')]}
        finally:conn.close()

    @app.get('/api/hub/admin/courses')
    def list_admin_courses(user=Depends(required_role('admin'))):
        conn=db()
        try:return {'courses':[course_dict(conn,r) for r in conn.execute('SELECT * FROM hub_courses ORDER BY id DESC')]}
        finally:conn.close()

    def check_course_form(body):
        code=body.code.strip().upper()
        if not re.fullmatch(r'[A-Z]{2,6}[0-9]{2,4}[A-Z]?',code):raise HTTPException(422,'Use course code such as ST310 or MT340.')
        if not re.fullmatch(r'20\d{2}/20\d{2}',body.academic_year):raise HTTPException(422,'Academic year should be YYYY/YYYY.')
        if body.status not in ('draft','open','closed','archived'):raise HTTPException(422,'Invalid portal status.')
        if not body.programmes or any(p not in PROGRAMMES for p in body.programmes):raise HTTPException(422,'Choose eligible programmes.')
        return code,trimmed(body.title,'course title',140),trimmed(body.description,'description',500,False)

    @app.post('/api/hub/admin/courses',status_code=201)
    def create_course(body:CourseForm,user=Depends(required_role('admin'))):
        code,title,desc=check_course_form(body)
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('''INSERT INTO hub_courses(code,title,academic_year,description,status,programmes,legacy,seminar_enabled,created_at,updated_at)
                VALUES(?,?,?,?,?,?,0,?,?,?)''',(code,title,body.academic_year,desc,body.status,json.dumps(body.programmes),int(body.seminar_enabled),now_iso(),now_iso()))
            audit(conn,'master-admin','HUB_COURSE_CREATED',f'{code} {body.academic_year}')
            conn.execute('COMMIT')
            return {'course':course_dict(conn,lookup_course(conn,row.lastrowid))}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'This course already exists for the selected academic year.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.put('/api/hub/admin/courses/{course_id}')
    def update_course(course_id:int,body:CourseForm,user=Depends(required_role('admin'))):
        code,title,desc=check_course_form(body)
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            original=lookup_course(conn,course_id)
            require_writable(original)
            if conn.execute('SELECT COUNT(*) FROM hub_enrollments WHERE course_id=?',(course_id,)).fetchone()[0] and (code!=original['code'] or body.academic_year!=original['academic_year']):
                raise HTTPException(409,'Cannot change course identity while registrations exist. Archive it and create a new academic-year portal.')
            conn.execute('''UPDATE hub_courses SET code=?,title=?,academic_year=?,description=?,status=?,programmes=?,seminar_enabled=?,updated_at=? WHERE id=?''',
                         (code,title,body.academic_year,desc,body.status,json.dumps(body.programmes),int(body.seminar_enabled),now_iso(),course_id))
            audit(conn,'master-admin','HUB_COURSE_UPDATED',f'{course_id}: {body.status}')
            conn.execute('COMMIT')
            return {'course':course_dict(conn,lookup_course(conn,course_id))}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'This course and academic year already exist.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/courses/{course_id}/visibility')
    def set_course_visibility(course_id:int,visible:bool,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            lookup_course(conn,course_id)
            conn.execute('UPDATE hub_courses SET visible=? WHERE id=?',(int(visible),course_id))
            audit(conn,'master-admin','HUB_COURSE_VISIBILITY',f'{course_id}:{visible}')
            conn.execute('COMMIT')
            return {'visible':visible}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/courses/{course_id}/seminars',status_code=201)
    def add_seminar(course_id:int,body:SeminarForm,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            course=lookup_course(conn,course_id);require_writable(course)
            if not body.start_time<body.end_time:raise HTTPException(422,'End time must be later than start time.')
            x=conn.execute('INSERT INTO hub_seminars(course_id,label,day,start_time,end_time,venue) VALUES(?,?,?,?,?,?)',
                           (course_id,trimmed(body.label,'seminar label',80),trimmed(body.day,'day',20),body.start_time,body.end_time,trimmed(body.venue,'venue',80)))
            audit(conn,'master-admin','HUB_SEMINAR_ADDED',f'{course_id}:{x.lastrowid}')
            conn.execute('COMMIT')
            return {'course':course_dict(conn,lookup_course(conn,course_id))}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'This seminar label already exists.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/courses/{course_id}/students')
    def course_students(course_id:int,user=Depends(required_role('admin'))):
        conn=db()
        try:
            course=lookup_course(conn,course_id)
            if course['legacy']:
                rows=[dict(r) for r in conn.execute('''SELECT id,registration_number,surname,first_name,second_name,programme,seminar_code,created_at
                    FROM students ORDER BY surname,first_name''')]
            else:
                rows=[enrollment_details(conn,r) for r in conn.execute('SELECT * FROM hub_enrollments WHERE course_id=? ORDER BY surname,first_name',(course_id,))]
            return {'course':course_dict(conn,course),'students':rows}
        finally:conn.close()

    class AdminEnrollmentEdit(RegistrationForm):
        reason:str=Field(min_length=8,max_length=400)
        seminar_id:int|None=None

    @app.put('/api/hub/admin/courses/{course_id}/students/{enrollment_id}')
    def admin_update_enrollment(course_id:int,enrollment_id:int,body:AdminEnrollmentEdit,
                                user=Depends(required_role('admin'))):
        p=validate_person(body)
        reason=trimmed(body.reason,'reason for correction',400)
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            course=lookup_course(conn,course_id);require_writable(course)
            current=conn.execute('SELECT * FROM hub_enrollments WHERE course_id=? AND id=?',(course_id,enrollment_id)).fetchone()
            if not current:raise HTTPException(404,'Student registration not found.')
            if p['programme'] not in jd(course['programmes']):raise HTTPException(422,'Programme not eligible for this course.')
            for r in conn.execute('SELECT reg_key,surname,first_name,second_name FROM hub_enrollments WHERE course_id=? AND id<>?',(course_id,enrollment_id)):
                if r['reg_key']==p['reg_key']:raise HTTPException(409,'Registration number belongs to another student in this course.')
                if similarity_kind(r,p):raise HTTPException(409,'Possible duplicate student; verify the record before editing.')
            if body.seminar_id is not None:validate_seminar(conn,course_id,body.seminar_id)
            before=dict(current)
            conn.execute('''UPDATE hub_enrollments SET reg_key=?,registration_number=?,surname=?,first_name=?,second_name=?,programme=?,seminar_id=?
                WHERE id=?''',(p['reg_key'],p['registration_number'],p['surname'],p['first_name'],p['second_name'],p['programme'],body.seminar_id,enrollment_id))
            if before['seminar_id']!=body.seminar_id:
                conn.execute('''UPDATE hub_shifts SET status='rejected',reviewed_at=?,review_note=?
                    WHERE enrollment_id=? AND status='pending' ''',(now_iso(),'Superseded by Master Admin correction',enrollment_id))
            audit(conn,'master-admin','HUB_STUDENT_EDITED',json.dumps({'course_id':course_id,'student_id':enrollment_id,'before':before,
                             'after':{**p,'seminar_id':body.seminar_id},'reason':reason},ensure_ascii=False))
            conn.execute('COMMIT')
            return {'registration':enrollment_details(conn,conn.execute('SELECT * FROM hub_enrollments WHERE id=?',(enrollment_id,)).fetchone())}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'Registration number already exists in this course.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    class AdminVerifiedEnrollment(RegistrationForm):
        reason:str=Field(min_length=8,max_length=400)

    @app.post('/api/hub/admin/courses/{course_id}/students/verified',status_code=201)
    def admin_verified_enrollment(course_id:int,body:AdminVerifiedEnrollment,user=Depends(required_role('admin'))):
        p=validate_person(body)
        reason=trimmed(body.reason,'verification reason',400)
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            course=lookup_course(conn,course_id);require_writable(course)
            if p['programme'] not in jd(course['programmes']):
                raise HTTPException(422,'Programme not eligible for this course.')
            if conn.execute('SELECT id FROM hub_enrollments WHERE course_id=? AND reg_key=?',(course_id,p['reg_key'])).fetchone():
                raise HTTPException(409,'This registration number already exists in the course.')
            similar=[]
            for r in conn.execute('SELECT surname,first_name,second_name FROM hub_enrollments WHERE course_id=?',(course_id,)):
                if similarity_kind(r,p):
                    similar.append(' '.join([r['surname'],r['first_name'],r['second_name']]))
            cur=conn.execute('''INSERT INTO hub_enrollments(course_id,reg_key,registration_number,surname,first_name,second_name,programme,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',(course_id,p['reg_key'],p['registration_number'],p['surname'],p['first_name'],p['second_name'],p['programme'],now_iso()))
            audit(conn,'master-admin','HUB_VERIFIED_STUDENT_ADDED',json.dumps({'course_id':course_id,'student_id':cur.lastrowid,
                           'similar_existing_names':similar[:10],'reason':reason},ensure_ascii=False))
            conn.execute('COMMIT')
            return {'message':'Verified student added by Master Admin.','id':cur.lastrowid,'similar_names_checked':len(similar)}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'Registration number already exists in this course.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/shifts')
    def admin_hub_shifts(user=Depends(required_role('admin'))):
        conn=db()
        try:
            generic=[dict(r) for r in conn.execute('''SELECT h.id,h.course_id,h.reason,h.status,h.created_at,h.from_seminar_id,h.to_seminar_id,
                   c.code, e.registration_number,e.surname,e.first_name,e.second_name,
                   fs.label AS from_label, ts.label AS to_label
                   FROM hub_shifts h JOIN hub_courses c ON c.id=h.course_id JOIN hub_enrollments e ON e.id=h.enrollment_id
                   JOIN hub_seminars fs ON fs.id=h.from_seminar_id JOIN hub_seminars ts ON ts.id=h.to_seminar_id
                   WHERE h.status='pending' ORDER BY h.created_at''')]
            return {'pending':generic}
        finally:conn.close()

    @app.post('/api/hub/admin/shifts/{shift_id}/decision')
    def review_hub_shift(shift_id:int,body:ShiftReview,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            shift=conn.execute('SELECT * FROM hub_shifts WHERE id=?',(shift_id,)).fetchone()
            if not shift:raise HTTPException(404,'Shift not found.')
            if shift['status']!='pending':raise HTTPException(409,'Shift request was already reviewed.')
            enrol=conn.execute('SELECT * FROM hub_enrollments WHERE id=?',(shift['enrollment_id'],)).fetchone()
            if enrol['seminar_id']!=shift['from_seminar_id']:
                raise HTTPException(409,'Student seminar changed since this request was submitted.')
            if body.approve:
                conn.execute('UPDATE hub_enrollments SET seminar_id=? WHERE id=?',(shift['to_seminar_id'],enrol['id']))
            conn.execute('UPDATE hub_shifts SET status=?,reviewed_at=?,review_note=? WHERE id=?',
                         ('approved' if body.approve else 'rejected',now_iso(),trimmed(body.note,'review note',400),shift_id))
            audit(conn,'master-admin','HUB_SHIFT_REVIEWED',f'{shift_id}:{body.approve}')
            conn.execute('COMMIT')
            return {'message':'Shift request reviewed.'}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/courses/{course_id}/export.xlsx')
    def course_export(course_id:int,user=Depends(required_role('admin'))):
        conn=db()
        try:
            course=lookup_course(conn,course_id)
            if course['legacy']:
                rows=[dict(r) for r in conn.execute('SELECT * FROM students ORDER BY surname,first_name')]
                for r in rows:r['seminar_label']={'MON':'Monday','THU':'Thursday','FRI':'Friday'}.get(r['seminar_code'],'Not selected')
            else:
                rows=[dict(r) for r in conn.execute('''SELECT e.*,s.label seminar_label FROM hub_enrollments e LEFT JOIN hub_seminars s ON e.seminar_id=s.id WHERE e.course_id=? ORDER BY e.surname,e.first_name''',(course_id,))]
            wb=Workbook();ws=wb.active;ws.title='Registrations';ws.append([f'{course["code"]} — {course["title"]} ({course["academic_year"]})']);ws.append([])
            headers=['STUDENT NAMES','REGISTRATION NUMBER','COURSE','PROGRAMME','SEMINAR']
            ws.append(headers)
            for r in rows:
                name=' '.join(filter(None,(r['surname'],r['first_name'],r['second_name'])))
                def sf(value):
                    value=str(value or '')
                    return "'"+value if value.startswith(('=','+','-','@')) else value
                ws.append([sf(name),sf(r['registration_number']),course['code'],PROGRAMMES.get(r['programme'],r['programme']),sf(r.get('seminar_label') or 'Not selected')])
            for c in ws[3]:c.fill=PatternFill('solid',fgColor='082657');c.font=Font(bold=True,color='FFFFFF')
            for k,w in {'A':40,'B':24,'C':15,'D':35,'E':26}.items():ws.column_dimensions[k].width=w
            ws.freeze_panes='A4';ws.sheet_view.showGridLines=False
            buf=BytesIO();wb.save(buf)
            return Response(buf.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  headers={'Content-Disposition':f'attachment; filename="{course["code"]}_Registrations.xlsx"','Cache-Control':'no-store'})
        finally:conn.close()

    @app.get('/api/hub/admin/material-courses')
    def material_courses_admin(user=Depends(required_role('admin'))):
        conn=db()
        try:return {'courses':[dict(x) for x in conn.execute('SELECT * FROM hub_material_courses ORDER BY code')],
                    'materials':[dict(x) for x in conn.execute('SELECT * FROM hub_materials ORDER BY id DESC')]}
        finally:conn.close()

    @app.post('/api/hub/admin/material-courses',status_code=201)
    def create_material_course(body:MaterialCourseForm,user=Depends(required_role('admin'))):
        code=body.code.strip().upper()
        if not re.fullmatch(r'[A-Z]{2,6}[0-9]{2,4}[A-Z]?',code):raise HTTPException(422,'Use course code ST310, MT340, etc.')
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            c=conn.execute('INSERT INTO hub_material_courses(code,title,description,visible,created_at) VALUES(?,?,?,?,?)',
                           (code,trimmed(body.title,'title',140),trimmed(body.description,'description',500,False),int(body.visible),now_iso()))
            audit(conn,'master-admin','HUB_MATERIAL_COURSE_CREATED',code)
            conn.execute('COMMIT')
            return {'id':c.lastrowid}
        except sqlite3.IntegrityError:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise HTTPException(409,'This academic course already exists.')
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/material-courses/{course_id}/visible')
    def toggle_material_course(course_id:int,visible:bool,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_material_courses WHERE id=?',(course_id,)).fetchone():raise HTTPException(404,'Academic course not found.')
            conn.execute('UPDATE hub_material_courses SET visible=? WHERE id=?',(int(visible),course_id))
            audit(conn,'master-admin','HUB_MATERIAL_COURSE_VISIBILITY',f'{course_id}:{visible}')
            conn.execute('COMMIT');return {'visible':visible}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/materials/upload',status_code=201)
    async def upload_material(course_id:int=Form(...),title:str=Form(...),topic:str=Form('General'),
                     visible:bool=Form(True),file:UploadFile=File(...),user=Depends(required_role('admin'))):
        allowed={'.pdf':'pdf','.pptx':'slides','.docx':'document','.xlsx':'spreadsheet',
                 '.png':'image','.jpg':'image','.jpeg':'image'}
        name=safe_filename(file.filename or '')
        suffix=Path(name).suffix.lower()
        if suffix not in allowed:raise HTTPException(422,'Upload PDF, PPTX, DOCX, XLSX, PNG or JPG only.')
        payload=await file.read(15*1024*1024+1)
        if not payload or len(payload)>15*1024*1024:raise HTTPException(413,'Upload must be 15 MB or less.')
        if suffix=='.pdf' and not payload.startswith(b'%PDF-'):raise HTTPException(422,'Invalid PDF file.')
        if suffix in ('.pptx','.docx','.xlsx'):
            try:
                with zipfile.ZipFile(BytesIO(payload)) as z:
                    if len(z.namelist())>5000:raise ValueError('Too many entries')
                    if not any(n=='[Content_Types].xml' for n in z.namelist()):raise ValueError('Not Office format')
            except (zipfile.BadZipFile,ValueError):raise HTTPException(422,'Invalid Office document.')
        if suffix=='.png' and not payload.startswith(b'\x89PNG\r\n\x1a\n'):raise HTTPException(422,'Invalid PNG.')
        if suffix in ('.jpg','.jpeg') and not payload.startswith(b'\xff\xd8\xff'):raise HTTPException(422,'Invalid JPEG.')
        title=trimmed(title,'material title',180);topic=trimmed(topic,'topic',120)
        conn=db();storage_key=secrets.token_hex(18)+suffix;target=MEDIA_DIR/storage_key
        try:
            if not conn.execute('SELECT 1 FROM hub_material_courses WHERE id=?',(course_id,)).fetchone():raise HTTPException(404,'Academic course not found.')
            MEDIA_DIR.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f:f.write(payload)
            conn.execute('BEGIN IMMEDIATE')
            cur=conn.execute('''INSERT INTO hub_materials(course_id,title,topic,kind,file_name,storage_key,file_size,visible,uploaded_at)
                 VALUES(?,?,?,?,?,?,?,?,?)''',(course_id,title,topic,allowed[suffix],name,storage_key,len(payload),int(visible),now_iso()))
            audit(conn,'master-admin','HUB_MATERIAL_UPLOADED',f'{course_id}:{title}')
            conn.execute('COMMIT');return {'id':cur.lastrowid,'title':title}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            if target.is_file():target.unlink()
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/materials/{material_id}/visible')
    def toggle_material(material_id:int,visible:bool,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_materials WHERE id=?',(material_id,)).fetchone():raise HTTPException(404,'Material not found.')
            conn.execute('UPDATE hub_materials SET visible=? WHERE id=?',(int(visible),material_id))
            audit(conn,'master-admin','HUB_MATERIAL_VISIBILITY',f'{material_id}:{visible}')
            conn.execute('COMMIT');return {'visible':visible}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/notices')
    def notices_admin(user=Depends(required_role('admin'))):
        conn=db()
        try:return {'items':[dict(r) for r in conn.execute('SELECT * FROM hub_notices ORDER BY id DESC')]}
        finally:conn.close()

    @app.post('/api/hub/admin/notices',status_code=201)
    def add_notice(body:NoticeForm,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            c=conn.execute('INSERT INTO hub_notices(title,body,category,course_code,published,created_at) VALUES(?,?,?,?,?,?)',
                           (trimmed(body.title,'title',170),trimmed(body.body,'body',4000),trimmed(body.category,'category',50),
                            trimmed(body.course_code,'course code',20,False),int(body.published),now_iso()))
            audit(conn,'master-admin','HUB_NOTICE_CREATED',str(c.lastrowid));conn.execute('COMMIT')
            return {'id':c.lastrowid}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/notices/{item_id}/published')
    def publish_notice(item_id:int,published:bool,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_notices WHERE id=?',(item_id,)).fetchone():raise HTTPException(404,'Notice not found.')
            conn.execute('UPDATE hub_notices SET published=? WHERE id=?',(int(published),item_id))
            audit(conn,'master-admin','HUB_NOTICE_PUBLICATION',f'{item_id}:{published}')
            conn.execute('COMMIT');return {'published':published}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/opportunities')
    def opportunities_admin(user=Depends(required_role('admin'))):
        conn=db()
        try:return {'items':[dict(r) for r in conn.execute('SELECT * FROM hub_opportunities ORDER BY id DESC')]}
        finally:conn.close()

    @app.post('/api/hub/admin/opportunities',status_code=201)
    def add_opportunity(body:OpportunityForm,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            item=conn.execute('INSERT INTO hub_opportunities(title,body,category,deadline,url,published,created_at) VALUES(?,?,?,?,?,?,?)',
                (trimmed(body.title,'title',170),trimmed(body.body,'description',4000),trimmed(body.category,'category',50),
                 trimmed(body.deadline,'deadline',30,False),check_external_url(body.url.strip()),int(body.published),now_iso()))
            audit(conn,'master-admin','HUB_OPPORTUNITY_CREATED',str(item.lastrowid));conn.execute('COMMIT')
            return {'id':item.lastrowid}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.post('/api/hub/admin/opportunities/{item_id}/published')
    def publish_opportunity(item_id:int,published:bool,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_opportunities WHERE id=?',(item_id,)).fetchone():raise HTTPException(404,'Opportunity not found.')
            conn.execute('UPDATE hub_opportunities SET published=? WHERE id=?',(int(published),item_id))
            audit(conn,'master-admin','HUB_OPPORTUNITY_PUBLICATION',f'{item_id}:{published}')
            conn.execute('COMMIT');return {'published':published}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/courses/{course_id}/seminars/export.xlsx')
    def seminar_groups_export(course_id:int,user=Depends(required_role('admin'))):
        conn=db()
        try:
            course=lookup_course(conn,course_id)
            wb=Workbook();wb.remove(wb.active)
            if course['legacy']:
                groups=[('MON','MONDAY 16:00–16:55 ALRC'),('THU','THURSDAY 10:00–10:55 ALRB'),('FRI','FRIDAY 18:00–18:55 ALRD')]
                rows_for=lambda code:conn.execute('''SELECT surname,first_name,second_name,registration_number,programme FROM students
                       WHERE seminar_code=? ORDER BY programme,surname,first_name''',(code,)).fetchall()
            else:
                groups=[(s['id'],s['label']+' — '+s['day']+' '+s['start_time']+'–'+s['end_time']+' '+s['venue'])
                     for s in conn.execute('SELECT * FROM hub_seminars WHERE course_id=? ORDER BY id',(course_id,))]
                rows_for=lambda code:conn.execute('''SELECT surname,first_name,second_name,registration_number,programme FROM hub_enrollments
                       WHERE course_id=? AND seminar_id=? ORDER BY programme,surname,first_name''',(course_id,code)).fetchall()
            for i,(code,label) in enumerate(groups):
                ws=wb.create_sheet(re.sub(r'[^a-zA-Z0-9 ]','',label.split(' — ')[0])[:30] or 'Seminar '+str(i+1))
                ws.append([f'{course["code"]} — {course["title"]}'])
                ws.append([label]);ws.append(['STUDENT NAMES','REGISTRATION NUMBER','COURSE'])
                for r in rows_for(code):
                    def excel_safe(value):
                        value=str(value)
                        return "'"+value if value.startswith(('=','+','-','@')) else value
                    ws.append([excel_safe(' '.join(filter(None,[r['surname'],r['first_name'],r['second_name']]))),
                               excel_safe(r['registration_number']),course['code']])
                for cell in ws[3]:cell.fill=PatternFill('solid',fgColor='082657');cell.font=Font(color='FFFFFF',bold=True)
                ws.column_dimensions['A'].width=44;ws.column_dimensions['B'].width=26;ws.column_dimensions['C'].width=18
                ws.freeze_panes='A4';ws.sheet_view.showGridLines=False
            if not groups:
                ws=wb.create_sheet('No Seminars');ws.append(['No seminars configured for this course.'])
            blob=BytesIO();wb.save(blob)
            return Response(content=blob.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':f'attachment; filename="{course["code"]}_Seminar_Groups.xlsx"','Cache-Control':'no-store'})
        finally:conn.close()

    @app.put('/api/hub/admin/notices/{item_id}')
    def edit_notice(item_id:int,body:NoticeForm,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_notices WHERE id=?',(item_id,)).fetchone():
                raise HTTPException(404,'Announcement not found.')
            conn.execute('UPDATE hub_notices SET title=?,body=?,category=?,course_code=?,published=? WHERE id=?',
                         (trimmed(body.title,'title',170),trimmed(body.body,'body',4000),trimmed(body.category,'category',50),
                          trimmed(body.course_code,'course code',20,False),int(body.published),item_id))
            audit(conn,'master-admin','HUB_NOTICE_EDITED',str(item_id))
            conn.execute('COMMIT');return {'message':'Announcement updated.'}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.put('/api/hub/admin/opportunities/{item_id}')
    def edit_opportunity(item_id:int,body:OpportunityForm,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_opportunities WHERE id=?',(item_id,)).fetchone():
                raise HTTPException(404,'Opportunity not found.')
            conn.execute('UPDATE hub_opportunities SET title=?,body=?,category=?,deadline=?,url=?,published=? WHERE id=?',
                         (trimmed(body.title,'title',170),trimmed(body.body,'body',4000),trimmed(body.category,'category',50),
                          trimmed(body.deadline,'deadline',30,False),check_external_url(body.url.strip()),int(body.published),item_id))
            audit(conn,'master-admin','HUB_OPPORTUNITY_EDITED',str(item_id))
            conn.execute('COMMIT');return {'message':'Opportunity updated.'}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.put('/api/hub/admin/materials/{material_id}')
    def edit_material(material_id:int,title:str,topic:str,visible:bool,user=Depends(required_role('admin'))):
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM hub_materials WHERE id=?',(material_id,)).fetchone():
                raise HTTPException(404,'Material not found.')
            conn.execute('UPDATE hub_materials SET title=?,topic=?,visible=? WHERE id=?',
                         (trimmed(title,'title',180),trimmed(topic,'topic',120),int(visible),material_id))
            audit(conn,'master-admin','HUB_MATERIAL_EDITED',str(material_id))
            conn.execute('COMMIT');return {'message':'Material updated.'}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()

    @app.get('/api/hub/admin/homepage')
    def admin_homepage(user=Depends(required_role('admin'))):
        conn=db()
        try:
            row=conn.execute('SELECT title,subtitle,sections FROM hub_homepage WHERE id=1').fetchone()
            return {'title':row['title'],'subtitle':row['subtitle'],'sections':jd(row['sections'])}
        finally:conn.close()

    @app.put('/api/hub/admin/homepage')
    def update_homepage(body:HomeForm,user=Depends(required_role('admin'))):
        if len(body.sections)!=len(set(body.sections)) or any(s not in public_sections for s in body.sections):
            raise HTTPException(422,'Homepage sections must be unique valid service names.')
        conn=db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE hub_homepage SET title=?,subtitle=?,sections=? WHERE id=1',
                         (trimmed(body.title,'title',100),trimmed(body.subtitle,'subtitle',200),json.dumps(body.sections)))
            audit(conn,'master-admin','HUB_HOMEPAGE_UPDATED',json.dumps(body.sections))
            conn.execute('COMMIT');return {'message':'Homepage published.'}
        except Exception:
            if conn.in_transaction:conn.execute('ROLLBACK')
            raise
        finally:conn.close()
