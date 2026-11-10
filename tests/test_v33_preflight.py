import os,sys,tempfile,zipfile,io,sqlite3,importlib.util,concurrent.futures
from fastapi.testclient import TestClient
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
assert (ROOT/"static/index.html").is_file(), "ST310 UI index.html missing"
assert (ROOT/"static/assets/app.js").is_file(), "ST310 UI app.js missing"
assert (ROOT/"static/assets/styles.css").is_file(), "ST310 UI styles.css missing"

tmp=tempfile.mkdtemp(prefix='st310-v33-')
os.environ['DB_PATH']=str(Path(tmp)/'existing.sqlite3')
os.environ['ADMIN_PASSWORD']='test-secret-long-just-for-local'
os.environ['ADMIN_USERNAME']='admin'
os.environ['CR_INVITE_MATH']='TEST-MATH-NOT-PROD'
os.environ['CR_INVITE_BAEST']='TEST-BAEST-NOT-PROD'
os.environ['CR_INVITE_BAST']='TEST-BAST-NOT-PROD'
os.environ['INITIAL_REGISTRATION_OPEN']='0'
spec=importlib.util.spec_from_file_location('main33', str(ROOT/'main.py'))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert all(k in m.SEMINARS for k in ('MON','THU','FRI'))
c=TestClient(m.app)

def pp(x):
    print(x.status_code,str(x.text)[:180]);return x

def admin_auth():
    r=c.post('/api/admin/login',json={'username':'admin','password':os.environ['ADMIN_PASSWORD']})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}

h=admin_auth()
assert c.get('/api/health').status_code==200
assert c.get('/api/public').json()['registration_open']==False
assert c.get('/api/admin/dashboard',headers=h).json()['total']==0
assert c.get('/api/admin/seminars',headers=h).json()['unassigned']==0
assert c.post('/api/admin/registration',json={'open':True},headers=h).status_code==200

def data(no, surname='WAMBURA',first='Baraka',second='Charles',prog='MATH'):
    return {'registration_number':f'2024-04-{no:05d}','surname':surname,'first_name':first,'second_name':second,'programme':prog}

first=c.post('/api/students/register',json=data(11456));assert first.status_code==201,first.text
obj=first.json();s_token=obj['student_token']
assert obj['student']['registration_number']=='2024-04-11456'
student_h={'Authorization':'Bearer '+s_token}
# previously missing seminar, no existing data lost
assert c.get('/api/students/me',headers=student_h).json()['student']['seminar_code'] is None
# same student, misspelled, different number blocked
other=c.post('/api/students/register',json=data(11463,'WAMBIRA','Barakisa','Charles'))
assert other.status_code==409,other.text
# additional student with different name
another=c.post('/api/students/register',json=data(11457,'JUMA','Hassan','Ali'))
assert another.status_code==201,another.text
# strict name identity
wrong=c.post('/api/students/verify',json={'registration_number':'2024-04-11456','surname':'WAMBURA','first_name':'Barakaaa','second_name':'Charles'})
assert wrong.status_code==401
verify=c.post('/api/students/verify',json={'registration_number':'2024-04-11456','surname':'Wambura','first_name':'Baraka','second_name':'Charles'})
assert verify.status_code==200,verify.text
vhead={'Authorization':'Bearer '+verify.json()['student_token']}
# first seminar succeeds, repeat rejected even same destination
assert c.post('/api/students/seminar',json={'seminar_code':'MON'},headers=vhead).status_code==200
assert c.post('/api/students/seminar',json={'seminar_code':'THU'},headers=vhead).status_code==409
assert c.get('/api/students/me',headers=vhead).json()['student']['seminar_code']=='MON'
# first shift accepted, second denied
r=c.post('/api/students/seminar/shift-request',json={'to_code':'THU','reason':'Thursday suits my timetable'},headers=vhead)
assert r.status_code==201,r.text
assert r.json()['student']['seminar_code']=='MON'
assert c.post('/api/students/seminar/shift-request',json={'to_code':'FRI','reason':'Want Friday'},headers=vhead).status_code==409
overview=c.get('/api/admin/seminars',headers=h).json()
req=[r for r in overview['shift_requests'] if r['status']=='pending'];assert len(req)==1
assert next(s['count'] for s in overview['seminars'] if s['code']=='MON')==1
assert next(s['count'] for s in overview['seminars'] if s['code']=='THU')==0
# no unauthorized exports, shift approval
assert c.get('/api/admin/seminars/export.xlsx').status_code==401
assert c.post(f'/api/admin/seminars/shift-requests/{req[0]["id"]}/decision',json={'action':'approve','note':'Verified timetable conflict'},headers=h).status_code==200
assert c.post(f'/api/admin/seminars/shift-requests/{req[0]["id"]}/decision',json={'action':'approve','note':'Again duplicate approval'},headers=h).status_code==409
assert c.get('/api/students/me',headers=vhead).json()['student']['seminar_code']=='THU'
# xlsx uses 3 sheets, title, no unassigned rows
xlsx=c.get('/api/admin/seminars/export.xlsx',headers=h)
assert xlsx.status_code==200
with zipfile.ZipFile(io.BytesIO(xlsx.content)) as z:
    workbook=z.read('xl/workbook.xml').decode()
    assert all(x in workbook for x in ['MONDAY','THURSDAY','FRIDAY']),workbook
    assert workbook.count('<sheet ')==3
assert c.get('/api/admin/seminars/THU/export.xlsx',headers=h).status_code==200
assert c.get('/api/admin/seminars/INVALID/export.xlsx',headers=h).status_code==404
# admin edit saves original and reset approval only on structural, can also change seminar
students=c.get('/api/admin/students',headers=h).json()['students']
student=next(s for s in students if s['registration_number']=='2024-04-11456')
assert student['seminar_code']=='THU'
edit=c.put(f'/api/admin/students/{student["id"]}',json={**data(11456,'WAMBURA','BARAKA','CHARLES'), 'seminar_code':'FRI','reason':'Verified academic timetable correction'},headers=h)
assert edit.status_code==200,edit.text
assert c.get('/api/students/me',headers=vhead).json()['student']['seminar_code']=='FRI'
# delete no records during migration repeat
m.migrate_v33()
conn=sqlite3.connect(os.environ['DB_PATH']);assert conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]==2
assert conn.execute('SELECT COUNT(*) FROM seminar_shift_requests').fetchone()[0]==1
assert conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]=='3.3'
conn.close()
# test true concurrent selection for same student: only one accepted
r2=another.json()['student_token'];h2={'Authorization':'Bearer '+r2}
def submit(code):return c.post('/api/students/seminar',json={'seminar_code':code},headers=h2).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    statuses=list(pool.map(submit,['MON','THU','FRI']))
assert statuses.count(200)==1 and statuses.count(409)==2,statuses
conn=sqlite3.connect(os.environ['DB_PATH']);assert conn.execute("SELECT COUNT(*) FROM students WHERE id=2 AND seminar_code IS NOT NULL").fetchone()[0]==1
conn.close()
print('PASS: migration, empty start, name matching, one seminar, shift workflow, admin review, exports, admin edits, atomic concurrent selections')
