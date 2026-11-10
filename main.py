"""ST310 Street Finest registration portal — FastAPI + SQLite.

Launch from this folder with: uvicorn main:app --host 0.0.0.0 --port 8000
Set environment variables in .env or via your host before public deployment.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import unicodedata
from difflib import SequenceMatcher
import time
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"


def load_local_env() -> None:
    f = BASE / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_local_env()
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE / "st310.sqlite3"))).resolve()
ACADEMIC_YEAR = os.environ.get("ACADEMIC_YEAR", "2026/2027")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
PROGRAMMES = {
    "MATH": "BSc Mathematics & Statistics",
    "BAEST": "BAEST",
    "BAST": "BAST",
}
INVITE_ENV = {"MATH": "CR_INVITE_MATH", "BAEST": "CR_INVITE_BAEST", "BAST": "CR_INVITE_BAST"}
APP = FastAPI(title="ST310 Street Finest Portal", docs_url=None, redoc_url=None)
app = APP


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def fetch_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,value))


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 240000)
    return salt.hex() + ":" + digest.hex()


def check_secret(secret: str, value: str | None) -> bool:
    if not value:
        return False
    try:
        salt, expected = value.split(":", 1)
        real = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), 240000)
        return hmac.compare_digest(real, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def setup() -> None:
    conn = db()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reg_key TEXT NOT NULL UNIQUE,
                registration_number TEXT NOT NULL,
                surname TEXT NOT NULL,
                first_name TEXT NOT NULL,
                second_name TEXT NOT NULL DEFAULT '',
                programme TEXT NOT NULL CHECK(programme IN ('MATH','BAEST','BAST')),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS students_by_programme ON students(programme,surname,first_name);
            CREATE TABLE IF NOT EXISTS cr_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                programme TEXT NOT NULL UNIQUE CHECK(programme IN ('MATH','BAEST','BAST')),
                reg_key TEXT NOT NULL UNIQUE,
                registration_number TEXT NOT NULL,
                surname TEXT NOT NULL,
                first_name TEXT NOT NULL,
                second_name TEXT NOT NULL DEFAULT '',
                pin_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS programme_status (
                programme TEXT PRIMARY KEY CHECK(programme IN ('MATH','BAEST','BAST')),
                revision INTEGER NOT NULL DEFAULT 0,
                cr_approved_at TEXT,
                cr_approved_revision INTEGER
            );
            CREATE TABLE IF NOT EXISTS duplicate_exemptions (
                student_a INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                student_b INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                verified_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                PRIMARY KEY (student_a,student_b),
                CHECK (student_a < student_b)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL
            );
        """)
        for p in PROGRAMMES:
            conn.execute("INSERT OR IGNORE INTO programme_status(programme) VALUES(?)", (p,))
        if fetch_setting(conn, "registration_open") is None:
            set_setting(conn, "registration_open", "1" if os.environ.get("INITIAL_REGISTRATION_OPEN", "0") == "1" else "0")
        bootstrap = []
        if fetch_setting(conn, "token_secret") is None:
            set_setting(conn, "token_secret", os.environ.get("APP_SECRET_KEY") or secrets.token_urlsafe(48))
        if fetch_setting(conn, "admin_password_hash") is None:
            admin_password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(16)
            set_setting(conn, "admin_password_hash", hash_secret(admin_password))
            if not os.environ.get("ADMIN_PASSWORD"):
                bootstrap += ["ADMIN LOGIN", "Username: " + (os.environ.get("ADMIN_USERNAME") or "admin"), "Password: " + admin_password, ""]
        for code, varname in INVITE_ENV.items():
            if fetch_setting(conn, "invite_" + code) is None:
                invite = os.environ.get(varname) or secrets.token_hex(5).upper()
                set_setting(conn, "invite_" + code, hash_secret(invite))
                if not os.environ.get(varname):
                    bootstrap.append("CR invite code for " + PROGRAMMES[code] + ": " + invite)
        if bootstrap:
            p = DB_PATH.parent / ".local_credentials.txt"
            with p.open("a", encoding="utf-8") as f:
                f.write("\n=== ST310 INITIAL SETUP (KEEP PRIVATE) ===\n" + "\n".join(bootstrap) + "\n")
            try: p.chmod(0o600)
            except OSError: pass
            print("\n" + "\n".join(bootstrap) + f"\nCredentials saved to {p}\n")
    finally:
        conn.close()


setup()


def token_encode(role: str, actor: str, programme: str | None = None) -> str:
    conn = db()
    try: key = fetch_setting(conn, "token_secret") or ""
    finally: conn.close()
    payload = {"role":role,"sub":actor,"programme":programme,"exp":int(time.time()+7*24*3600)}
    raw = base64.urlsafe_b64encode(json.dumps(payload,separators=(",",":"),sort_keys=True).encode()).rstrip(b"=").decode()
    mac = hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+"."+mac


def token_decode(token: str) -> dict[str,Any]:
    try:
        raw, sig = token.split(".",1)
        conn = db()
        try: key = fetch_setting(conn,"token_secret") or ""
        finally: conn.close()
        exp_sig = hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp_sig,sig): raise ValueError("signature")
        obj = json.loads(base64.urlsafe_b64decode(raw+"="*(-len(raw)%4)))
        if int(obj["exp"]) < time.time(): raise ValueError("expired")
        return obj
    except (ValueError,KeyError,TypeError,UnicodeDecodeError):
        raise HTTPException(401,"Please log in again.")


def auth(authorization: str | None = Header(default=None)) -> dict[str,Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"Login required.")
    return token_decode(authorization[7:])


def required_role(role: str):
    def dep(user: dict=Depends(auth)):
        if user.get("role") != role: raise HTTPException(403,"Access denied.")
        return user
    return dep


def reg_key(val: str) -> str:
    return re.sub(r"[\s\-_/]+", "", val.upper())


def name_val(v: str, title: str, required: bool = True) -> str:
    v = re.sub(r"\s+", " ", v.strip())
    if (required and not v) or len(v)>65 or (v and not any(c.isalpha() for c in v)):
        raise HTTPException(422,f"Please enter a valid {title}.")
    if any(ch.isdigit() or ord(ch)<32 for ch in v):
        raise HTTPException(422,f"Please enter a valid {title}.")
    return v.upper() if title=="surname" else v.title()


def validate_person(data: Any) -> dict[str,str]:
    code = data.programme
    if code not in PROGRAMMES: raise HTTPException(422,"Please choose a programme.")
    num = data.registration_number
    if not re.fullmatch(r"[0-9]{4}-04-[0-9]{5}", num, flags=re.ASCII):
        raise HTTPException(
            status_code=422,
            detail="Registration number must be XXXX-04-XXXXX (example: 2024-04-11456). Only digits and the two hyphens are allowed."
        )
    return {
        "programme":code,
        "registration_number":num,
        "reg_key":reg_key(num),
        "surname":name_val(data.surname,"surname"),
        "first_name":name_val(data.first_name,"first name"),
        "second_name":name_val(data.second_name or "","second name",False),
    }



def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if ch.isalpha() and not unicodedata.combining(ch))


def jaro_winkler(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    window = max(len(left), len(right)) // 2 - 1
    left_match = [False] * len(left)
    right_match = [False] * len(right)
    matches = 0
    for i, character in enumerate(left):
        for j in range(max(0, i-window), min(len(right), i+window+1)):
            if not right_match[j] and character == right[j]:
                left_match[i] = right_match[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = 0
    position = 0
    for i, character in enumerate(left):
        if left_match[i]:
            while not right_match[position]:
                position += 1
            transpositions += character != right[position]
            position += 1
    jaro = (matches/len(left) + matches/len(right) + (matches-transpositions/2)/matches) / 3
    prefix = 0
    for a, b in zip(left[:4], right[:4]):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1-jaro) if jaro > 0.7 else jaro


def name_similarity(left: str, right: str) -> float:
    a, b = normalized_name(left), normalized_name(right)
    if not a or not b:
        return 0.0
    return 0.62 * jaro_winkler(a,b) + 0.38 * SequenceMatcher(None,a,b).ratio()


def similarity_kind(left: dict | sqlite3.Row, right: dict | sqlite3.Row) -> str | None:
    """Use all three name components; avoid treating one shared name as identity."""
    fields = ("surname", "first_name", "second_name")
    a = [normalized_name(left[key]) for key in fields]
    b = [normalized_name(right[key]) for key in fields]
    if not all(a) or not all(b):
        return None
    if a == b:
        return "matching_name"
    scores = [name_similarity(x, y) for x, y in zip(a, b)]
    # Two mildly misspelled name parts plus one exact part count as suspicious.
    # Example: WAMBIRA Barakisa Charles / WAMBURA Baraka Charles.
    if (min(scores) >= .88 and sum(scores) / 3 >= .925
            and (max(scores) >= .985 or sum(x >= .94 for x in scores) >= 2)):
        return "similar_name"
    swapped = [scores[0], name_similarity(a[1],b[2]), name_similarity(a[2],b[1])]
    if min(swapped) >= .91 and sum(swapped) / 3 >= .953:
        return "similar_name"
    return None


def unresolved_duplicates(conn: sqlite3.Connection, programme: str | None = None) -> list[dict]:
    rows = [dict(row) for row in conn.execute(
        "SELECT id,reg_key,registration_number,surname,first_name,second_name,programme,created_at FROM students ORDER BY id"
    ).fetchall()]
    exempt = {(row["student_a"], row["student_b"]) for row in conn.execute(
        "SELECT student_a,student_b FROM duplicate_exemptions").fetchall()}
    pairs = []
    for idx, a in enumerate(rows):
        for b in rows[idx+1:]:
            if programme and programme not in (a["programme"], b["programme"]):
                continue
            if (a["id"], b["id"]) in exempt:
                continue
            if not a["second_name"] or not b["second_name"]:
                continue
            # Fast candidate pruning for largely different names.
            if normalized_name(a["surname"])[:2] != normalized_name(b["surname"])[:2]:
                continue
            kind = similarity_kind(a,b)
            if kind:
                pairs.append({"first":a, "second":b, "kind":kind})
    return pairs


def duplicate_match(conn: sqlite3.Connection, person: dict[str,str]) -> str | None:
    """Atomic check before insertion; registration number always wins."""
    rows = conn.execute("SELECT reg_key,surname,first_name,second_name FROM students").fetchall()
    for existing in rows:
        if existing["reg_key"] == person["reg_key"]:
            return "registration_number"
        kind = similarity_kind(existing,person)
        if kind:
            return kind
    return None


def duplicate_error(match: str) -> HTTPException:
    if match == "registration_number":
        return HTTPException(409,{"code":"ALREADY_REGISTERED","message":"This registration number has already been registered for ST310."})
    if match == "matching_name":
        return HTTPException(409,{"code":"ALREADY_REGISTERED","message":"A student with these three names is already registered for ST310, even though the registration number differs. If two students truly share the same names, contact the Master Admin."})
    return HTTPException(409,{"code":"POSSIBLE_DUPLICATE","message":"This name is very similar to an existing ST310 registration. Please check your spelling. If this is a different student, contact the Master Admin for verification."})


def audit(conn, actor: str, event: str, detail: str = ""):
    conn.execute("INSERT INTO audit_events(actor,event,detail,timestamp) VALUES(?,?,?,?)",(actor,event,detail,now_iso()))


class PersonData(BaseModel):
    programme: str
    surname: str = Field(min_length=1,max_length=120)
    first_name: str = Field(min_length=1,max_length=120)
    second_name: str = ""
    registration_number: str = Field(min_length=5,max_length=90)

class CRData(PersonData):
    pin: str
    invite_code: str

class CRLogin(BaseModel):
    registration_number: str
    pin: str

class AdminLogin(BaseModel):
    username: str
    password: str

class ApprovalRequest(BaseModel):
    revision: int
    count: int

class OpenRequest(BaseModel):
    open: bool

class DuplicateResolution(BaseModel):
    first_id: int = Field(gt=0)
    second_id: int = Field(gt=0)
    action: str
    remove_id: int | None = None
    reason: str = Field(min_length=8,max_length=350)


class AdminStudentOverride(PersonData):
    reason: str = Field(min_length=8,max_length=240)


@APP.get("/api/health")
def health():
    return {"status":"healthy","service":"Street Finest ST310 Portal"}

@APP.get("/api/public")
def public():
    conn=db()
    try:
        return {"registration_open":fetch_setting(conn,"registration_open")=="1", "course":"ST310 Statistical Inference II","programmes":PROGRAMMES}
    finally: conn.close()

@APP.post("/api/students/register",status_code=201)
def student_register(body:PersonData):
    p=validate_person(body)
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if fetch_setting(conn,"registration_open")!="1":
            raise HTTPException(403,"Registration is currently closed.")
        match = duplicate_match(conn,p)
        if match:
            raise duplicate_error(match)
        conn.execute("INSERT INTO students (reg_key,registration_number,surname,first_name,second_name,programme,created_at) VALUES (:reg_key,:registration_number,:surname,:first_name,:second_name,:programme,:created_at)", {**p,"created_at":now_iso()})
        conn.execute("UPDATE programme_status SET revision=revision+1,cr_approved_at=NULL,cr_approved_revision=NULL WHERE programme=?",(p["programme"],))
        audit(conn,p["reg_key"],"STUDENT_REGISTERED",p["programme"])
        conn.execute("COMMIT")
        return {"message":"Registration successful.","student":{k:p[k] for k in ("registration_number","surname","first_name","second_name","programme")}}
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        raise duplicate_error("registration_number")
    except Exception:
        if conn.in_transaction: conn.execute("ROLLBACK")
        raise
    finally: conn.close()

@APP.post("/api/cr/register",status_code=201)
def cr_register(body:CRData):
    p=validate_person(body)
    if not 4<=len(body.pin)<=72: raise HTTPException(422,"Use a PIN/password of at least 4 characters.")
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if fetch_setting(conn,"registration_open")!="1": raise HTTPException(403,"Registration is closed.")
        if not check_secret(body.invite_code.strip(), fetch_setting(conn,"invite_"+p["programme"])):
            raise HTTPException(403,"Invalid Class Representative invite code.")
        if conn.execute("SELECT 1 FROM cr_accounts WHERE programme=?",(p["programme"],)).fetchone():
            raise HTTPException(409,"This programme already has a Class Representative.")
        if conn.execute("SELECT 1 FROM cr_accounts WHERE reg_key=?",(p["reg_key"],)).fetchone():
            raise HTTPException(409,"You are already registered as a Class Representative.")
        existing=conn.execute("SELECT programme,surname,first_name FROM students WHERE reg_key=?",(p["reg_key"],)).fetchone()
        if existing and (existing["programme"]!=p["programme"] or existing["surname"].casefold()!=p["surname"].casefold() or existing["first_name"].casefold()!=p["first_name"].casefold()):
            raise HTTPException(409,"Your registration number exists with different details. Contact the administrator.")
        if not existing:
            possible_duplicate = duplicate_match(conn,p)
            if possible_duplicate:
                raise duplicate_error(possible_duplicate)
            conn.execute("INSERT INTO students(reg_key,registration_number,surname,first_name,second_name,programme,created_at) VALUES (:reg_key,:registration_number,:surname,:first_name,:second_name,:programme,:created_at)",{**p,"created_at":now_iso()})
            conn.execute("UPDATE programme_status SET revision=revision+1,cr_approved_at=NULL,cr_approved_revision=NULL WHERE programme=?",(p["programme"],))
        conn.execute("INSERT INTO cr_accounts(programme,reg_key,registration_number,surname,first_name,second_name,pin_hash,created_at) VALUES (?,?,?,?,?,?,?,?)",(p["programme"],p["reg_key"],p["registration_number"],p["surname"],p["first_name"],p["second_name"],hash_secret(body.pin),now_iso()))
        audit(conn,p["reg_key"],"CR_REGISTERED",p["programme"])
        conn.execute("COMMIT")
        return {"token":token_encode("cr",p["reg_key"],p["programme"]),"programme":p["programme"]}
    except sqlite3.IntegrityError:
        if conn.in_transaction: conn.execute("ROLLBACK")
        raise HTTPException(409,"This CR account or programme is already registered.")
    except Exception:
        if conn.in_transaction: conn.execute("ROLLBACK")
        raise
    finally: conn.close()

_attempts: dict[str,list[float]]=defaultdict(list)

def throttle(request: Request):
    key=(request.client.host if request.client else "unknown")
    now=time.time()
    history=[x for x in _attempts[key] if now-x<900]
    if len(history)>=25: raise HTTPException(429,"Too many login attempts. Please try again later.")
    history.append(now); _attempts[key]=history

@APP.post("/api/cr/login")
def cr_login(body:CRLogin,request:Request):
    throttle(request)
    conn=db()
    try:
        if not re.fullmatch(r"[0-9]{4}-04-[0-9]{5}", body.registration_number, flags=re.ASCII):
            raise HTTPException(422,"Registration number must be XXXX-04-XXXXX (example: 2024-04-11456).")
        cr=conn.execute("SELECT * FROM cr_accounts WHERE reg_key=?",(reg_key(body.registration_number),)).fetchone()
        if not cr or not check_secret(body.pin,cr["pin_hash"]):
            raise HTTPException(401,"Incorrect registration number or PIN.")
        return {"token":token_encode("cr",cr["reg_key"],cr["programme"]),"programme":cr["programme"]}
    finally: conn.close()

@APP.get("/api/cr/dashboard")
def cr_dashboard(user:dict=Depends(required_role("cr"))):
    conn=db()
    try:
        cr=conn.execute("SELECT surname,first_name,second_name,programme FROM cr_accounts WHERE reg_key=? AND programme=?",(user["sub"],user["programme"])).fetchone()
        if not cr: raise HTTPException(401,"CR account not found.")
        stats=conn.execute("SELECT * FROM programme_status WHERE programme=?",(cr["programme"],)).fetchone()
        rows=conn.execute("SELECT surname,first_name,second_name,registration_number,created_at FROM students WHERE programme=? ORDER BY surname COLLATE NOCASE,first_name COLLATE NOCASE,reg_key",(cr["programme"],)).fetchall()
        return {"cr":dict(cr),"programme":cr["programme"],"programme_name":PROGRAMMES[cr["programme"]],"revision":stats["revision"],"approved_at":stats["cr_approved_at"],"students":[dict(r) for r in rows],"duplicate_alert_count":len(unresolved_duplicates(conn,cr["programme"])),"registration_open":fetch_setting(conn,"registration_open")=="1"}
    finally: conn.close()

@APP.post("/api/cr/approve")
def cr_approve(body:ApprovalRequest,user:dict=Depends(required_role("cr"))):
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        stats=conn.execute("SELECT revision FROM programme_status WHERE programme=?",(user["programme"],)).fetchone()
        count=conn.execute("SELECT COUNT(*) as n FROM students WHERE programme=?",(user["programme"],)).fetchone()["n"]
        if not stats or count==0: raise HTTPException(422,"There are no students to approve.")
        if unresolved_duplicates(conn,user["programme"]):
            raise HTTPException(409,"Possible duplicate registrations were found. Ask the Master Admin to review them before approving the programme list.")
        if stats["revision"]!=body.revision or count!=body.count:
            raise HTTPException(409,"The student list has changed. Refresh the dashboard before approving.")
        when=now_iso()
        conn.execute("UPDATE programme_status SET cr_approved_at=?,cr_approved_revision=revision WHERE programme=?",(when,user["programme"]))
        audit(conn,user["sub"],"CR_APPROVED",user["programme"]+f" ({count} students)")
        conn.execute("COMMIT")
        return {"approved_at":when,"count":count}
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
    finally:conn.close()

@APP.post("/api/admin/login")
def admin_login(body:AdminLogin,request:Request):
    throttle(request)
    conn=db()
    try:
        if not hmac.compare_digest(body.username.strip(),os.environ.get("ADMIN_USERNAME","admin")) or not check_secret(body.password,fetch_setting(conn,"admin_password_hash")):
            raise HTTPException(401,"Invalid administrator credentials.")
        return {"token":token_encode("admin","master-admin")}
    finally:conn.close()


def read_admin_data(conn):
    stats=[]
    for code,label in PROGRAMMES.items():
        row=conn.execute("SELECT revision,cr_approved_at FROM programme_status WHERE programme=?",(code,)).fetchone()
        count=conn.execute("SELECT count(*) n FROM students WHERE programme=?",(code,)).fetchone()["n"]
        stats.append({"code":code,"label":label,"count":count,"approved_at":row["cr_approved_at"],"revision":row["revision"]})
    recent=conn.execute("SELECT actor,event,detail,timestamp FROM audit_events ORDER BY id DESC LIMIT 6").fetchall()
    return {"programmes":stats,"total":sum(x["count"] for x in stats),"approvals":sum(bool(x["approved_at"]) for x in stats),"duplicate_alert_count":len(unresolved_duplicates(conn)),"registration_open":fetch_setting(conn,"registration_open")=="1","final_approved_at":fetch_setting(conn,"final_approved_at"),"recent":[dict(r) for r in recent]}

@APP.get("/api/admin/dashboard")
def admin_dashboard(user:dict=Depends(required_role("admin"))):
    conn=db()
    try: return read_admin_data(conn)
    finally:conn.close()

@APP.get("/api/admin/students")
def admin_students(user:dict=Depends(required_role("admin"))):
    conn=db()
    try:
        rows=conn.execute("SELECT id,surname,first_name,second_name,registration_number,programme,created_at FROM students ORDER BY CASE programme WHEN 'MATH' THEN 1 WHEN 'BAEST' THEN 2 ELSE 3 END,surname COLLATE NOCASE,first_name COLLATE NOCASE").fetchall()
        return {"students":[dict(r) for r in rows]}
    finally:conn.close()

@APP.get("/api/admin/duplicates")
def admin_duplicate_list(user:dict=Depends(required_role("admin"))):
    conn=db()
    try:
        return {"pairs":unresolved_duplicates(conn)}
    finally:
        conn.close()


@APP.post("/api/admin/duplicates/resolve")
def admin_resolve_duplicate(body:DuplicateResolution,user:dict=Depends(required_role("admin"))):
    if body.action not in ("keep_distinct","remove_record"):
        raise HTTPException(422,"Choose a valid resolution action.")
    if body.first_id == body.second_id:
        raise HTTPException(422,"Choose two distinct registrations.")
    first_id,second_id = sorted((body.first_id,body.second_id))
    reason=" ".join(body.reason.strip().split())
    if len(reason)<8:
        raise HTTPException(422,"Enter a verification reason of at least 8 characters.")
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        matches=[pair for pair in unresolved_duplicates(conn)
                 if (pair["first"]["id"],pair["second"]["id"])==(first_id,second_id)]
        if not matches:
            raise HTTPException(409,"This pair no longer needs review. Refresh the list.")
        pair=matches[0]
        if fetch_setting(conn,"final_approved_at"):
            raise HTTPException(409,"Reopen registration before correcting a final-approved list.")
        if body.action=="keep_distinct":
            conn.execute("INSERT INTO duplicate_exemptions(student_a,student_b,verified_by,reason,reviewed_at) VALUES(?,?,?,?,?)",
                         (first_id,second_id,user["sub"],reason,now_iso()))
            event="DUPLICATE_PAIR_VERIFIED_DISTINCT"
        else:
            if body.remove_id not in (first_id,second_id):
                raise HTTPException(422,"Choose which registration record to remove.")
            removed = pair["first"] if body.remove_id==first_id else pair["second"]
            if conn.execute("SELECT 1 FROM cr_accounts WHERE reg_key=?",(removed["reg_key"],)).fetchone():
                raise HTTPException(409,"This record belongs to a Class Representative. Contact the administrator before changing the CR account.")
            conn.execute("DELETE FROM students WHERE id=?",(body.remove_id,))
            conn.execute("UPDATE programme_status SET revision=revision+1,cr_approved_at=NULL,cr_approved_revision=NULL WHERE programme=?",(removed["programme"],))
            event="DUPLICATE_RECORD_REMOVED"
        audit(conn,user["sub"],event,f"{first_id}/{second_id} | removed={body.remove_id if body.action=='remove_record' else 'none'} | {reason}")
        conn.execute("COMMIT")
        return {"resolved":True,"action":body.action,"remaining":len(unresolved_duplicates(conn))}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@APP.post("/api/admin/students/override",status_code=201)
def admin_student_override(body:AdminStudentOverride,user:dict=Depends(required_role("admin"))):
    """Manual resolution when two genuinely different students have near-identical names."""
    p=validate_person(body)
    reason = re.sub(r"\s+"," ",body.reason.strip())
    if len(reason)<8:
        raise HTTPException(422,"Provide a short verification reason.")
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if fetch_setting(conn,"registration_open")!="1":
            raise HTTPException(403,"Registration is currently closed.")
        if conn.execute("SELECT 1 FROM students WHERE reg_key=?",(p["reg_key"],)).fetchone():
            raise duplicate_error("registration_number")
        near=[int(row["id"]) for row in conn.execute("SELECT id,surname,first_name,second_name FROM students") if similarity_kind(row,p)]
        cursor=conn.execute("INSERT INTO students (reg_key,registration_number,surname,first_name,second_name,programme,created_at) VALUES (:reg_key,:registration_number,:surname,:first_name,:second_name,:programme,:created_at)",{**p,"created_at":now_iso()})
        new_id=int(cursor.lastrowid)
        for existing_id in near:
            x,y=sorted((existing_id,new_id))
            conn.execute("INSERT OR IGNORE INTO duplicate_exemptions(student_a,student_b,verified_by,reason,reviewed_at) VALUES(?,?,?,?,?)",
                         (x,y,user["sub"],reason,now_iso()))
        conn.execute("UPDATE programme_status SET revision=revision+1,cr_approved_at=NULL,cr_approved_revision=NULL WHERE programme=?",(p["programme"],))
        audit(conn,"master-admin","DUPLICATE_REVIEW_OVERRIDE",f"{p['reg_key']} | {reason}")
        conn.execute("COMMIT")
        return {"message":"Student added after administrator verification.","student":{k:p[k] for k in ("registration_number","surname","first_name","second_name","programme")}}
    except sqlite3.IntegrityError:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise duplicate_error("registration_number")
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@APP.post("/api/admin/final-approve")
def final_approve(user:dict=Depends(required_role("admin"))):
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        valid=conn.execute("SELECT COUNT(*) n FROM programme_status WHERE cr_approved_at IS NOT NULL AND cr_approved_revision=revision").fetchone()["n"]
        if unresolved_duplicates(conn):
            raise HTTPException(409,"Review all possible duplicate registrations before final approval.")
        if valid!=3: raise HTTPException(409,"All three Class Representatives must approve their programme lists first.")
        when=now_iso()
        set_setting(conn,"final_approved_at",when)
        set_setting(conn,"registration_open","0")
        audit(conn,"master-admin","FINAL_APPROVED","3 programmes")
        conn.execute("COMMIT")
        return {"final_approved_at":when,"registration_open":False}
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
    finally:conn.close()

@APP.post("/api/admin/registration")
def toggle_registration(body:OpenRequest,user:dict=Depends(required_role("admin"))):
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        currently=fetch_setting(conn,"registration_open")=="1"
        if body.open and not currently:
            # Reopening invalidates the previous finalized snapshot and requires all CRs to reapprove.
            conn.execute("UPDATE programme_status SET cr_approved_at=NULL,cr_approved_revision=NULL")
            set_setting(conn,"final_approved_at","")
        set_setting(conn,"registration_open","1" if body.open else "0")
        audit(conn,"master-admin","REGISTRATION_OPENED" if body.open else "REGISTRATION_CLOSED")
        conn.execute("COMMIT")
        return {"registration_open":body.open}
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
    finally:conn.close()


def approved_export_rows():
    conn=db()
    try:
        if not fetch_setting(conn,"final_approved_at"):
            raise HTTPException(409,"Approve the final list before exporting.")
        if unresolved_duplicates(conn):
            raise HTTPException(409,"Resolve the possible duplicate registrations before exporting.")
        rows=conn.execute("SELECT surname,first_name,second_name,registration_number,programme FROM students ORDER BY CASE programme WHEN 'MATH' THEN 1 WHEN 'BAEST' THEN 2 ELSE 3 END,surname COLLATE NOCASE,first_name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows],fetch_setting(conn,"final_approved_at")
    finally:conn.close()

NAVY="092654"; NAVY2="113F80"; GOLD="D7A329"; PALE_GOLD="FBE5A0"; WHITE="FFFFFF"


def excel_safe(s:str)->str:
    return "'"+s if s.lstrip().startswith(("=","+","-","@")) else s


def render_sheet(ws, rows, title, all_programmes=False):
    ws.sheet_view.showGridLines=False
    ws.merge_cells("A1:F2")
    a=ws["A1"]; a.value="ST310  |  STATISTICAL INFERENCE II"; a.fill=PatternFill("solid",fgColor=NAVY);a.font=Font(name="Aptos Display",size=20,bold=True,color=WHITE);a.alignment=Alignment(vertical="center",horizontal="center")
    for row in ws["A1:F2"]:
        for c in row:c.fill=PatternFill("solid",fgColor=NAVY)
    ws.merge_cells("A3:F3"); c=ws["A3"];c.value="UNIVERSITY OF DAR ES SALAAM   •   THIRD YEAR STUDENT REGISTRATION LIST";c.font=Font(size=11,color=WHITE,bold=True);c.fill=PatternFill("solid",fgColor=NAVY2);c.alignment=Alignment(horizontal="center",vertical="center")
    for row in ws["A3:F3"]:
        for c in row:c.fill=PatternFill("solid",fgColor=NAVY2)
    ws.merge_cells("A5:D5");ws["A5"]="Programme: "+ title;ws["A5"].font=Font(bold=True,color=NAVY,size=11)
    ws.merge_cells("E5:F5");ws["E5"]="Registered: "+str(len(rows));ws["E5"].font=Font(bold=True,color=NAVY,size=11)
    ws.merge_cells("A6:D6");ws["A6"]="Academic Year: "+ACADEMIC_YEAR;ws["A6"].font=Font(color="6A7382")
    ws.merge_cells("E6:F6");ws["E6"]="Exported: "+datetime.now().strftime("%d %b %Y");ws["E6"].font=Font(color="6A7382")
    ws.merge_cells("A8:F8");ws["A8"]="COMPLETE LIST OF REGISTERED STUDENTS";ws["A8"].font=Font(bold=True,color=WHITE,size=12);ws["A8"].fill=PatternFill("solid",fgColor=NAVY);ws["A8"].alignment=Alignment(horizontal="center",vertical="center")
    for row in ws["A8:F8"]:
        for c in row:c.fill=PatternFill("solid",fgColor=NAVY)
    header=["S/N","Surname","First Name","Second Name","Registration Number","Programme"]
    for col,label in enumerate(header,1):
        c=ws.cell(9,col,label);c.fill=PatternFill("solid",fgColor="F0BF4D");c.font=Font(bold=True,color=NAVY);c.alignment=Alignment(horizontal="center",vertical="center");c.border=Border(bottom=Side(style="medium",color=GOLD))
    shades={"MATH":"E8F5E9","BAEST":"E2F1FC","BAST":"F1E8FA"}
    for i,s in enumerate(rows,1):
        values=[i,excel_safe(s["surname"]),excel_safe(s["first_name"]),excel_safe(s["second_name"]),excel_safe(s["registration_number"]),PROGRAMMES[s["programme"]]]
        rownum=i+9
        for j,v in enumerate(values,1):
            c=ws.cell(rownum,j,v);c.font=Font(name="Aptos",size=10,color=NAVY,bold=j==2)
            c.alignment=Alignment(vertical="center",horizontal="center" if j==1 else "left")
            c.fill=PatternFill("solid",fgColor=(shades[s["programme"]] if j==6 else ("FFFFFF" if i%2 else "F3F6FB")))
            c.border=Border(bottom=Side(style="hair",color="D5DFED"))
        ws.row_dimensions[rownum].height=22
    ws.row_dimensions[1].height=25;ws.row_dimensions[2].height=25;ws.row_dimensions[3].height=26;ws.row_dimensions[8].height=27;ws.row_dimensions[9].height=27
    for col,width in {"A":8,"B":22,"C":22,"D":23,"E":26,"F":35}.items():ws.column_dimensions[col].width=width
    ws.freeze_panes="B10"
    ws.auto_filter.ref=f"A9:F{max(10,9+len(rows))}"
    ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.orientation="landscape";ws.page_setup.paperSize=ws.PAPERSIZE_A4;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    ws.print_title_rows="1:9"
    ws.page_margins=PageMargins(left=.25,right=.25,top=.5,bottom=.5,header=.2,footer=.2)
    ws.oddFooter.center.text="Street Finest Academic Systems  |  Page &P of &N"
    if all_programmes:
        for column, width in {"G":3,"H":33,"I":16,"J":17}.items():
            ws.column_dimensions[column].width=width
        ws.merge_cells("H1:J2")
        brand=ws["H1"]
        brand.value="SF  |  Street Finest"
        brand.fill=PatternFill("solid",fgColor=NAVY)
        brand.font=Font(name="Georgia",size=18,bold=True,color="F5CE6B")
        brand.alignment=Alignment(horizontal="center",vertical="center")
        for row in ws["H1:J2"]:
            for c in row:c.fill=PatternFill("solid",fgColor=NAVY)
        ws.merge_cells("H3:J3")
        tagline=ws["H3"]
        tagline.value="ACADEMIC SYSTEMS  •  2026/2027"
        tagline.fill=PatternFill("solid",fgColor=NAVY2)
        tagline.font=Font(size=10,color=WHITE,bold=True)
        tagline.alignment=Alignment(horizontal="center",vertical="center")
        for row in ws["H3:J3"]:
            for c in row:c.fill=PatternFill("solid",fgColor=NAVY2)
        ws.merge_cells("H5:J6")
        total=ws["H5"]
        total.value=f"TOTAL REGISTERED STUDENTS     {len(rows):,}"
        total.fill=PatternFill("solid",fgColor=NAVY)
        total.font=Font(name="Aptos Display",size=14,color="FBE6AC",bold=True)
        total.alignment=Alignment(horizontal="center",vertical="center")
        for row in ws["H5:J6"]:
            for c in row:c.fill=PatternFill("solid",fgColor=NAVY)
        ws.merge_cells("H8:J8")
        ws["H8"]="REGISTRATION SUMMARY"
        ws["H8"].font=Font(size=12,bold=True,color=WHITE)
        ws["H8"].alignment=Alignment(horizontal="center",vertical="center")
        for row in ws["H8:J8"]:
            for c in row:c.fill=PatternFill("solid",fgColor=NAVY)
        for column,header in [("H","Programme"),("I","Students"),("J","Share")]:
            cell=ws[f"{column}9"]
            cell.value=header
            cell.font=Font(size=10,bold=True,color=NAVY)
            cell.fill=PatternFill("solid",fgColor="F0BF4D")
            cell.alignment=Alignment(horizontal="center",vertical="center")
        for rowno,(code,label) in enumerate(PROGRAMMES.items(),start=10):
            fill=PatternFill("solid",fgColor=shades[code])
            ws[f"H{rowno}"]=label
            ws[f"I{rowno}"]=sum(student["programme"]==code for student in rows)
            ws[f"J{rowno}"]=f"=IFERROR(I{rowno}/$I$13,0)"
            ws[f"J{rowno}"].number_format="0.0%"
            for col in "HIJ":
                cell=ws[f"{col}{rowno}"]
                cell.fill=fill
                cell.font=Font(size=10,color=NAVY,bold=col=="H")
                cell.alignment=Alignment(vertical="center",horizontal="center" if col!="H" else "left")
                cell.border=Border(bottom=Side(style="hair",color="C7D3E2"))
        for column,value in [("H","TOTAL"),("I","=SUM(I10:I12)"),("J","=SUM(J10:J12)")]:
            c=ws[f"{column}13"]
            c.value=value
            c.fill=PatternFill("solid",fgColor=NAVY)
            c.font=Font(size=11,bold=True,color=WHITE)
            c.alignment=Alignment(horizontal="center" if column!="H" else "left",vertical="center")
        ws["J13"].number_format="0.0%"
        ws.merge_cells("H15:J15")
        ws["H15"]="FINAL CLASS LIST  •  ST310"
        ws["H15"].fill=PatternFill("solid",fgColor="F0BF4D")
        ws["H15"].font=Font(bold=True,color=NAVY)
        ws["H15"].alignment=Alignment(horizontal="center")
        ws.merge_cells("H16:J17")
        ws["H16"]="Prepared for course coordination after CR and Master Admin approval."
        ws["H16"].font=Font(size=10,color="435573")
        ws["H16"].alignment=Alignment(wrap_text=True,vertical="center")



def build_xlsx(rows):
    wb=Workbook(); all_sheet=wb.active;all_sheet.title="ALL STUDENTS"
    render_sheet(all_sheet,rows,"ALL PROGRAMMES",True)
    for code in PROGRAMMES:
        ws=wb.create_sheet("BSc Math & Stats" if code=="MATH" else code)
        render_sheet(ws,[r for r in rows if r["programme"]==code],PROGRAMMES[code])
    summ=wb.create_sheet("Summary",0);summ.sheet_view.showGridLines=False
    summ.merge_cells("A1:D2");summ["A1"]="ST310  |  REGISTRATION SUMMARY";summ["A1"].font=Font(size=18,bold=True,color=WHITE)
    for row in summ["A1:D2"]:
        for c in row:c.fill=PatternFill("solid",fgColor=NAVY)
    summ.merge_cells("A4:D4");summ["A4"]="Statistical Inference II • Third Year • "+ACADEMIC_YEAR;summ["A4"].font=Font(size=11,color=NAVY,bold=True)
    for j,val in enumerate(["Programme","Students","Share","Status"],1):
        c=summ.cell(6,j,val);c.fill=PatternFill("solid",fgColor="F0BF4D");c.font=Font(bold=True,color=NAVY)
    for i,(code,label) in enumerate(PROGRAMMES.items(),7):
        count=sum(r["programme"]==code for r in rows)
        summ.cell(i,1,label);summ.cell(i,2,count);summ.cell(i,3,f"=IFERROR(B{i}/B10,0)");summ.cell(i,3).number_format="0.0%";summ.cell(i,4,"CR Approved")
        for c in summ[i][:4]:c.fill=PatternFill("solid",fgColor="FFFFFF" if i%2 else "EDF4FA");c.font=Font(color=NAVY)
    summ.cell(10,1,"TOTAL");summ.cell(10,2,"=SUM(B7:B9)");summ.cell(10,3,"=SUM(C7:C9)");summ.cell(10,3).number_format="0.0%";summ.cell(10,4,"FINAL APPROVED")
    for c in summ[10][:4]:c.fill=PatternFill("solid",fgColor=NAVY);c.font=Font(bold=True,color=WHITE)
    for col,w in {"A":39,"B":18,"C":18,"D":23}.items():summ.column_dimensions[col].width=w
    summ.merge_cells("A13:D13");summ["A13"]="Prepared by Street Finest  •  Student-led ST310 Registration Portal";summ["A13"].font=Font(size=10,italic=True,color="526783")
    buf=BytesIO();wb.save(buf);return buf.getvalue()



def build_submission_xlsx(rows):
    """A single-sheet, three-column final roster for lecturer submission."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "ST310 SUBMISSION"
    sheet.sheet_view.showGridLines = False

    navy = "102C57"
    gold = "C99B37"
    text_color = "182B45"
    muted = "65748A"
    edge = Side(style="hair", color="D7DEE7")

    sheet.merge_cells("A1:C1")
    title = sheet["A1"]
    title.value = "ST310 — STATISTICAL INFERENCE II"
    title.font = Font(name="Aptos Display", size=17, bold=True, color=navy)
    title.alignment = Alignment(vertical="center", horizontal="left")
    sheet.row_dimensions[1].height = 38

    sheet.merge_cells("A2:C2")
    subtitle = sheet["A2"]
    subtitle.value = "THIRD YEAR STUDENT REGISTRATION LIST — FOR SUBMISSION"
    subtitle.font = Font(name="Aptos", size=10, bold=True, color=muted)
    subtitle.alignment = Alignment(vertical="center")
    sheet.row_dimensions[2].height = 24

    sheet.merge_cells("A3:C3")
    academic = sheet["A3"]
    academic.value = f"Academic Year: {ACADEMIC_YEAR}"
    academic.font = Font(name="Aptos", size=10, color=text_color)
    academic.alignment = Alignment(vertical="center")
    sheet.row_dimensions[3].height = 24
    for cell in sheet[4][:3]:
        cell.fill = PatternFill("solid", fgColor=gold)
    sheet.row_dimensions[4].height = 4

    headers = ("STUDENT NAMES", "REGISTRATION NUMBER", "COURSE")
    for col, heading in enumerate(headers, start=1):
        cell = sheet.cell(5, col, heading)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.font = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    sheet.row_dimensions[5].height = 31

    order = {programme: i for i, programme in enumerate(PROGRAMMES)}
    ordered = sorted(
        rows,
        key=lambda row: (
            order.get(row["programme"], len(order)),
            row["surname"].casefold(),
            row["first_name"].casefold(),
            (row["second_name"] or "").casefold(),
            row["registration_number"],
        ),
    )
    last_programme = None
    for row_num, person in enumerate(ordered, start=6):
        full_name = " ".join(
            part.strip() for part in (
                person["surname"], person["first_name"], person["second_name"]
            ) if part and part.strip()
        ).upper()
        values = (
            excel_safe(full_name),
            excel_safe(person["registration_number"]),
            PROGRAMMES[person["programme"]],
        )
        is_new_group = last_programme is not None and last_programme != person["programme"]
        shade = "FFFFFF" if row_num % 2 == 0 else "F5F7FA"
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row_num, col, value)
            cell.fill = PatternFill("solid", fgColor=shade)
            cell.font = Font(name="Aptos", size=10, color=text_color,
                             bold=col == 1)
            cell.alignment = Alignment(vertical="center", horizontal="left", indent=1,
                                       wrap_text=col == 3)
            cell.border = Border(top=Side(style="medium", color=gold) if is_new_group else edge,
                                 bottom=edge, left=edge, right=edge)
            if col == 2:
                cell.number_format = "@"
        sheet.row_dimensions[row_num].height = 24
        last_programme = person["programme"]

    sheet.column_dimensions["A"].width = 43
    sheet.column_dimensions["B"].width = 26
    sheet.column_dimensions["C"].width = 35
    sheet.freeze_panes = "A6"
    end_row = max(6, 5 + len(ordered))
    if ordered:
        sheet.auto_filter.ref = f"A5:C{end_row}"
    sheet.print_options.horizontalCentered = True
    sheet.print_area = f"A1:C{end_row}"
    sheet.print_title_rows = "1:5"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_margins = PageMargins(left=0.25, right=0.25, top=0.45,
                                     bottom=0.45, header=0.2, footer=0.2)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def pdf_fonts():
    regular=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if regular.exists() and "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu",str(regular)))
        pdfmetrics.registerFont(TTFont("DejaVuBold",str(bold)))
    return ("DejaVu","DejaVuBold") if regular.exists() else ("Helvetica","Helvetica-Bold")


def build_pdf(rows):
    plain,bold=pdf_fonts(); buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=28,leftMargin=28,topMargin=35,bottomMargin=36,title="ST310 Statistical Inference II - Final Class List",author="Street Finest Academic Systems")
    styles=getSampleStyleSheet()
    header=ParagraphStyle("STHead",parent=styles["Title"],fontName=bold,fontSize=20,leading=26,textColor=colors.HexColor("#092654"),alignment=TA_CENTER,spaceAfter=8)
    sub=ParagraphStyle("STSub",parent=styles["Normal"],fontName=plain,fontSize=10,textColor=colors.HexColor("#24436B"),alignment=TA_CENTER,spaceAfter=15)
    section=ParagraphStyle("STSection",parent=styles["Heading2"],fontName=bold,fontSize=12,textColor=colors.HexColor("#092654"),spaceBefore=15,spaceAfter=7)
    small=ParagraphStyle("STCell",parent=styles["Normal"],fontName=plain,fontSize=7,leading=10)
    smallbold=ParagraphStyle("STCellB",parent=small,fontName=bold)
    story=[Paragraph("ST310 — Statistical Inference II",header),Paragraph("UNIVERSITY OF DAR ES SALAAM  |  THIRD YEAR STUDENT REGISTRATION  |  "+xml_escape(ACADEMIC_YEAR),sub)]
    counts=[(PROGRAMMES[c],sum(x["programme"]==c for x in rows)) for c in PROGRAMMES]
    summary=Table([[Paragraph(x,smallbold) for x in ("Programme","Registered Students")]]+[[Paragraph(str(a),small),Paragraph(str(b),small)] for a,b in counts]+[[Paragraph("TOTAL",smallbold),Paragraph(str(len(rows)),smallbold)]],colWidths=[390,150],hAlign="CENTER")
    summary.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#F0BF4D")),("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#DDE8F6")),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#B7C9DB")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    story.extend([summary,Spacer(1,12)])
    hdr=["S/N","Surname","First Name","Second Name","Registration Number","Programme"]
    for code,label in PROGRAMMES.items():
        group=[r for r in rows if r["programme"]==code]
        story.append(Paragraph(f"{xml_escape(label)}  —  {len(group)} registered students",section))
        table_data=[[Paragraph(xml_escape(h),smallbold) for h in hdr]]
        for i,r in enumerate(group,1):
            vals=[str(i),r["surname"],r["first_name"],r["second_name"],r["registration_number"],label]
            table_data.append([Paragraph(xml_escape(v),small) for v in vals])
        t=Table(table_data,colWidths=[35,122,118,120,155,235],repeatRows=1,hAlign="CENTER")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#F0BF4D")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#EDF3FB")]),("LINEBELOW",(0,0),(-1,-1),.25,colors.HexColor("#C7D3E2")),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),6)]))
        story.append(t)
    def footer(canvas,document):
        canvas.saveState();width,height=landscape(A4)
        canvas.setStrokeColor(colors.HexColor("#D7A329"));canvas.line(28,26,width-28,26)
        canvas.setFont(plain,7);canvas.setFillColor(colors.HexColor("#334D71"))
        canvas.drawString(28,13,"ST310 | Street Finest Academic Systems | Student-led course roster")
        canvas.drawRightString(width-28,13,f"Page {document.page}")
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

@APP.get("/api/admin/export.xlsx")
def export_xlsx(user:dict=Depends(required_role("admin"))):
    rows,_=approved_export_rows()
    return Response(content=build_xlsx(rows),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=ST310_Final_Registered_Students.xlsx","Cache-Control":"no-store"})


@APP.get("/api/admin/export-submission.xlsx")
def export_submission_xlsx(user: dict = Depends(required_role("admin"))):
    rows, _ = approved_export_rows()
    return Response(
        content=build_submission_xlsx(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=ST310_Students_Submission.xlsx",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )

@APP.get("/api/admin/export.pdf")
def export_pdf(user:dict=Depends(required_role("admin"))):
    rows,_=approved_export_rows()
    return Response(content=build_pdf(rows),media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=ST310_Final_Class_List.pdf","Cache-Control":"no-store"})

APP.mount("/assets",StaticFiles(directory=str(STATIC/"assets")),name="assets")

@APP.get("/{full_path:path}")
def frontend(full_path:str):
    if full_path.startswith("api/"):
        raise HTTPException(404,"Not found")
    return FileResponse(STATIC/"index.html")
