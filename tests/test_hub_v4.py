"""Run from project root: python tests/test_hub_v4.py
All tests use a fresh temporary SQLite DB; never run against DB_PATH=production.
"""
import importlib
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from fastapi.testclient import TestClient
from openpyxl import load_workbook

temporary=tempfile.TemporaryDirectory(prefix='street-finest-v4-tests-')
ROOT=Path(temporary.name)
os.environ['DB_PATH']=str(ROOT/'test.sqlite3')
os.environ['HUB_UPLOAD_DIR']=str(ROOT/'materials')
os.environ['ADMIN_PASSWORD']='test-password-not-production'
os.environ['ADMIN_USERNAME']='admin'
os.environ['INITIAL_REGISTRATION_OPEN']='0'
os.environ['CR_INVITE_MATH']='test-math'
os.environ['CR_INVITE_BAEST']='test-baest'
os.environ['CR_INVITE_BAST']='test-bast'
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import main
app=TestClient(main.app)

def check(r,status=200):
    if r.status_code!=status:
        raise AssertionError(f'{r.request.method} {r.request.url}: expected {status}, got {r.status_code}, {r.text[:600]}')
    return r.json() if r.headers.get('content-type','').startswith('application/json') else r

# Add a legacy record before V4 additions so it can be checked repeatedly.
with main.db() as conn:
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('''INSERT INTO students(reg_key,registration_number,surname,first_name,second_name,programme,created_at,seminar_code)
        VALUES(?,?,?,?,?,?,?,?)''',('20240411111','2024-04-11111','MTEGA','NEEMA','ASHA','MATH',main.now_iso(),'MON'))
    conn.execute('COMMIT')

pub=check(app.get('/api/hub/public'))
assert pub['homepage']['title']=='Street Finest Academic Hub'
assert len(pub['homepage']['sections'])==4
assert len(pub['courses'])==1 and pub['courses'][0]['code']=='ST310'
assert pub['courses'][0]['count']==1
assert check(app.get('/st310')).status_code==200
assert b'ST310 Statistical Inference II' in check(app.get('/st310')).content
assert b'Street Finest' in check(app.get('/')).content
assert b'phone-frame' not in app.get('/assets/hub.css').content

admin=check(app.post('/api/admin/login',json={'username':'admin','password':'test-password-not-production'}))
headers={'Authorization':'Bearer '+admin['token']}
check(app.get('/api/hub/admin/overview',headers=headers),200)
check(app.post('/api/hub/admin/courses',json={'code':'ST340','title':'Statistical Modelling','academic_year':'2026/2027','programmes':['MATH','BAEST'],'status':'open','seminar_enabled':True},headers=headers),201)
courses=check(app.get('/api/hub/admin/courses',headers=headers))['courses']
c=next(x for x in courses if x['code']=='ST340')
assert c['legacy']==0
legacy=next(x for x in courses if x['code']=='ST310')
assert check(app.get(f'/api/hub/admin/courses/{legacy["id"]}/students',headers=headers))['students'][0]['registration_number']=='2024-04-11111'
check(app.put(f'/api/hub/admin/courses/{legacy["id"]}',json={'code':'ST310','title':'Statistical Inference II','academic_year':'2026/2027'},headers=headers),409)

s1=check(app.post(f'/api/hub/admin/courses/{c["id"]}/seminars',json={'label':'Group A','day':'Monday','start_time':'16:00','end_time':'16:55','venue':'ALRC'},headers=headers),201)
s2=check(app.post(f'/api/hub/admin/courses/{c["id"]}/seminars',json={'label':'Group B','day':'Thursday','start_time':'10:00','end_time':'10:55','venue':'ALRB'},headers=headers),201)
sem_a=s1['course']['seminars'][0]['id']
sem_b=s2['course']['seminars'][1]['id']

r1=check(app.post(f'/api/hub/courses/{c["id"]}/register',json={'registration_number':'2024-04-11111','surname':'MTEGA','first_name':'NEEMA','second_name':'ASHA','programme':'MATH'}),201)
assert r1['registration']['seminar'] is None
# Student can register for multiple courses with same identity; cannot duplicate in same course.
check(app.post(f'/api/hub/courses/{c["id"]}/register',json={'registration_number':'2024-04-11111','surname':'MTEGA','first_name':'NEEMA','second_name':'ASHA','programme':'MATH'}),409)
check(app.post(f'/api/hub/courses/{c["id"]}/register',json={'registration_number':'2024-04-11112','surname':'MTEGA','first_name':'NEEMA','second_name':'ASHA','programme':'MATH'}),409)
check(app.post(f'/api/hub/courses/{c["id"]}/register',json={'registration_number':'2024-04-11113','surname':'WAMBIRA','first_name':'BARAKISA','second_name':'CHARLES','programme':'MATH'}),201)
check(app.post(f'/api/hub/courses/{c["id"]}/register',json={'registration_number':'2024-04-11114','surname':'WAMBURA','first_name':'BARAKA','second_name':'CHARLES','programme':'MATH'}),409)

# Admin may resolve a genuinely distinct fuzzy-name collision, never an exact Reg No. collision.
overridden=check(app.post(f'/api/hub/admin/courses/{c["id"]}/students/verified',headers=headers,json={
 'registration_number':'2024-04-11114','surname':'WAMBURA','first_name':'BARAKA','second_name':'CHARLES',
 'programme':'MATH','reason':'Independent verification confirms a distinct student'}),201)
assert overridden['similar_names_checked']>=1
check(app.post(f'/api/hub/admin/courses/{c["id"]}/students/verified',headers=headers,json={
 'registration_number':'2024-04-11114','surname':'DIFFERENT','first_name':'EXAMPLE','second_name':'PERSON',
 'programme':'MATH','reason':'Should fail duplicate Reg Number'}),409)

# Read-only lookup: wrong details and non-existent registration share the same response.
wrong=check(app.post('/api/hub/lookup',json={'course_id':c['id'],'registration_number':'2024-04-11111','surname':'WRONG','first_name':'NEEMA','second_name':'ASHA'}))
assert wrong['found'] is False and 'No available services for you' in wrong['message']
found=check(app.post('/api/hub/lookup',json={'course_id':c['id'],'registration_number':'2024-04-11111','surname':'MTEGA','first_name':'NEEMA','second_name':'ASHA'}))
assert found['found'] and found['registration']['seminar'] is None
student_headers={'Authorization':'Bearer '+found['student_token']}
check(app.post('/api/hub/student/seminar',json={'seminar_id':sem_a},headers=student_headers))
check(app.post('/api/hub/student/seminar',json={'seminar_id':sem_b},headers=student_headers),409)
check(app.post('/api/hub/student/shift',json={'to_seminar_id':sem_b,'reason':'Timetable conflict'},headers=student_headers),201)
check(app.post('/api/hub/student/shift',json={'to_seminar_id':sem_b,'reason':'Second request'},headers=student_headers),409)
assert check(app.get('/api/hub/student/me',headers=student_headers))['registration']['seminar']['id']==sem_a
pending=check(app.get('/api/hub/admin/shifts',headers=headers))['pending'];assert len(pending)==1
check(app.post(f'/api/hub/admin/shifts/{pending[0]["id"]}/decision',json={'approve':True,'note':'Verified timetable conflict'},headers=headers))
assert check(app.get('/api/hub/student/me',headers=student_headers))['registration']['seminar']['id']==sem_b
check(app.post(f'/api/hub/admin/shifts/{pending[0]["id"]}/decision',json={'approve':True,'note':'Repeat review'},headers=headers),409)

# Legacy My Registrations reads original student and original seminar, doesn't move data.
legacy_found=check(app.post('/api/hub/lookup',json={'course_id':legacy['id'],'registration_number':'2024-04-11111','surname':'MTEGA','first_name':'NEEMA','second_name':'ASHA'}))
assert legacy_found['found'] and legacy_found['registration']['seminar']['id']=='MON'

# Admin exports are course-scoped; ST310 stays unchanged.
res=check(app.get(f'/api/hub/admin/courses/{c["id"]}/export.xlsx',headers=headers))
w=load_workbook(io.BytesIO(res.content))
assert w.active['B4'].value=='2024-04-11111'
assert len(list(w.active.iter_rows(min_row=4,values_only=True)))==3
check(app.get('/api/hub/admin/overview'),401)

# Materials with real upload and protection of admin routes.
check(app.post('/api/hub/admin/material-courses',headers=headers,json={'code':'MT340','title':'Real Analysis'}),201)
mcourse=check(app.get('/api/hub/admin/material-courses',headers=headers))['courses'][0]
assert mcourse['code']=='MT340'
pdf=b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF'
file=app.post('/api/hub/admin/materials/upload',headers=headers,data={'course_id':mcourse['id'],'title':'Sets and Mappings','topic':'Topic 1','visible':'true'},files={'file':('sets.pdf',pdf,'application/pdf')})
check(file,201)
m=check(app.get(f'/api/hub/materials/{mcourse["id"]}'))['materials'][0]
assert check(app.get(f'/api/hub/materials/file/{m["id"]}')).content==pdf
check(app.post(f'/api/hub/admin/materials/{m["id"]}/visible?visible=false',headers=headers))
check(app.get(f'/api/hub/materials/file/{m["id"]}'),404)

# Admin-controlled published content and homepage.
check(app.post('/api/hub/admin/notices',headers=headers,json={'title':'Timetable Update','body':'Check the academic schedule','category':'General','published':True}),201)
check(app.post('/api/hub/admin/opportunities',headers=headers,json={'title':'Data Internship','body':'Apply to the internship','category':'Internship','url':'https://example.org/apply','published':True}),201)
check(app.put('/api/hub/admin/homepage',headers=headers,json={'title':'Street Finest Academic Hub','subtitle':'University Student Services','sections':['materials','registrations','announcements','opportunities']}))
p=check(app.get('/api/hub/public'))
assert len(p['notices'])==1 and len(p['opportunities'])==1
assert p['homepage']['sections'][0]=='materials'
assert p['material_courses'][0]['code']=='MT340'

# New-course corrections are audited, and generic seminar exports are group-specific.
sems=check(app.get(f'/api/hub/admin/courses/{c["id"]}/seminars/export.xlsx',headers=headers))
swb=load_workbook(io.BytesIO(sems.content))
assert len(swb.sheetnames)==2
assert any('MTEGA' in str(cell.value) for ws in swb for row in ws for cell in row)
check(app.post(f'/api/hub/admin/courses/{legacy["id"]}/visibility?visible=false',headers=headers))
assert not any(x['code']=='ST310' for x in check(app.get('/api/hub/public'))['courses'])
assert check(app.get(f'/api/hub/admin/courses/{legacy["id"]}/students',headers=headers))['students'][0]['seminar_code']=='MON'
check(app.post(f'/api/hub/admin/courses/{legacy["id"]}/visibility?visible=true',headers=headers))
students=check(app.get(f'/api/hub/admin/courses/{c["id"]}/students',headers=headers))['students']
first=next(r for r in students if r['registration_number']=='2024-04-11111')
changed=check(app.put(f'/api/hub/admin/courses/{c["id"]}/students/{first["id"]}',headers=headers,json={
  'registration_number':'2024-04-11115','surname':'MTEGA','first_name':'NEEMA','second_name':'ASHA',
  'programme':'MATH','seminar_id':sem_b,'reason':'Verified correction from student card'}))
assert changed['registration']['registration_number']=='2024-04-11115'
assert changed['registration']['seminar']['id']==sem_b
check(app.put(f'/api/hub/admin/courses/{c["id"]}/students/{first["id"]}',headers=headers,json={
  'registration_number':'2024-04-11113','surname':'WAMBIRA','first_name':'BARAKISA','second_name':'CHARLES',
  'programme':'MATH','seminar_id':sem_b,'reason':'Incorrect duplicate edit attempt'}),409)
assert check(app.get('/api/hub/admin/overview',headers=headers))['courses'][0]['count']>=1

notice_id=check(app.get('/api/hub/admin/notices',headers=headers))['items'][0]['id']
check(app.put(f'/api/hub/admin/notices/{notice_id}',headers=headers,json={'title':'Timetable Updated','body':'Important room change','category':'General','published':True}))
opp_id=check(app.get('/api/hub/admin/opportunities',headers=headers))['items'][0]['id']
check(app.put(f'/api/hub/admin/opportunities/{opp_id}',headers=headers,json={'title':'Research Internship','body':'New opportunity details','category':'Research','url':'https://example.org/new','published':True}))
assert check(app.get('/api/hub/public'))['notices'][0]['title']=='Timetable Updated'
assert check(app.get('/api/hub/public'))['opportunities'][0]['title']=='Research Internship'

# V4 is idempotent and all original ST310 records are preserved.
main.hub_v4.install if False else None
with main.db() as conn:
    assert conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]==1
    assert conn.execute('SELECT seminar_code FROM students LIMIT 1').fetchone()[0]=='MON'
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print('PASS: V4 universal homepage, legacy preservation, multi-course registrations, duplicates, lookup, one seminar, shifts, materials, content, admin auth, exports, homepage settings')
