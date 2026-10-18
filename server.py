import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('PROMEDICS_DB', ROOT / 'data/promedics.sqlite3'))
SESSIONS = {}
FAILURES = {}

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS admins (username TEXT PRIMARY KEY, salt TEXT, hash TEXT);
        CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, dob TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
          date TEXT NOT NULL, reason TEXT NOT NULL, medicine TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
        ''')
        # Add profile fields without losing records in an existing database.
        columns = {row['name'] for row in db.execute('PRAGMA table_info(patients)')}
        for name in ('gender', 'blood_type', 'allergies', 'disabilities', 'height_cm', 'weight_kg'):
            if name not in columns:
                db.execute(f"ALTER TABLE patients ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")

def field(data, key, required=True, limit=2000):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError('Please provide a valid ' + key + '.')
    return value.strip()

def date_field(data, key):
    value = field(data, key)
    parsed = dt.date.fromisoformat(value)
    if parsed > dt.date.today():
        raise ValueError(key + ' cannot be in the future.')
    return value

def patient_code():
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(7))
        if any(c.isalpha() for c in code) and any(c.isdigit() for c in code):
            return code

def profile_fields(data):
    gender = field(data, 'gender', False, 60)
    blood = field(data, 'blood_type', False, 10)
    if gender not in ('', 'Female', 'Male', 'Non-binary', 'Other', 'Prefer not to say'):
        raise ValueError('Invalid gender')
    if blood not in ('', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'):
        raise ValueError('Invalid blood type')
    measurements = []
    for key, maximum in (('height_cm', 300), ('weight_kg', 700)):
        value = field(data, key, False, 20)
        if value and not 0 < float(value) <= maximum:
            raise ValueError('Invalid measurement')
        measurements.append(value)
    return (gender, blood, field(data, 'allergies', False), field(data, 'disabilities', False), *measurements)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Avoid recording search terms or other patient information in access logs.
        pass

    def reply(self, status, obj, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', ''))
            token = jar['session'].value if 'session' in jar else ''
        except cookies.CookieError:
            return None
        session = SESSIONS.get(token)
        if session and session['expires'] > dt.datetime.now().timestamp():
            return session
        return None

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_PUT(self):
        self.handle_request('PUT')

    def handle_request(self, method):
        from urllib.parse import urlsplit, parse_qs
        url = urlsplit(self.path)
        path = url.path
        if not path.startswith('/api/'):
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if method != 'GET' or path not in files:
                return self.reply(404, {'error': 'Not found'})
            filename, mime = files[path]
            body = (ROOT / 'static' / filename).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            data = {}
            session = self.session()
            if method != 'GET':
                if int(self.headers.get('Content-Length', 0)) > 20000:
                    return self.reply(413, {'error': 'Request too large'})
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.reply(415, {'error': 'JSON required'})
                if self.headers.get('Origin') and urlsplit(self.headers['Origin']).netloc != self.headers.get('Host'):
                    return self.reply(403, {'error': 'Invalid origin'})
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                if not isinstance(data, dict):
                    raise ValueError('Invalid request')
            if path == '/api/login' and method == 'POST':
                now = dt.datetime.now().timestamp()
                attempts = [t for t in FAILURES.get(self.client_address[0], []) if t > now - 900]
                if len(attempts) >= 10:
                    return self.reply(429, {'error': 'Too many attempts. Try again in 15 minutes.'})
                with connect() as db:
                    admin = db.execute('SELECT * FROM admins WHERE username=?', (field(data, 'username'),)).fetchone()
                if not admin or not hmac.compare_digest(admin['hash'], password_hash(field(data, 'password'), admin['salt'])):
                    FAILURES[self.client_address[0]] = attempts + [now]
                    return self.reply(401, {'error': 'Incorrect username or password'})
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                SESSIONS[token] = {'username': admin['username'], 'csrf': csrf, 'expires': now + 28800}
                secure = '; Secure' if os.environ.get('PROMEDICS_SECURE_COOKIE') == '1' else ''
                return self.reply(200, SESSIONS[token], f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}')
            if not session:
                return self.reply(401, {'error': 'Please sign in'})
            if method != 'GET' and not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                return self.reply(403, {'error': 'Please refresh and try again'})
            if path == '/api/me':
                return self.reply(200, session)
            if path == '/api/logout' and method == 'POST':
                for key in list(SESSIONS):
                    if SESSIONS[key] is session:
                        del SESSIONS[key]
                return self.reply(200, {}, 'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            with connect() as db:
                if path == '/api/patients' and method == 'GET':
                    query = parse_qs(url.query).get('q', [''])[0].strip()
                    rows = db.execute('''SELECT p.*, (SELECT MAX(date) FROM visits WHERE patient_id=p.id) last_visit,
                      (SELECT COUNT(*) FROM visits WHERE patient_id=p.id) visit_count FROM patients p
                      WHERE instr(lower(name),lower(?))>0 OR instr(lower(code),lower(?))>0 ORDER BY name''', (query, query)).fetchall()
                    stats = dict(db.execute('''SELECT (SELECT COUNT(*) FROM patients) patients,
                      (SELECT COUNT(*) FROM visits) visits, (SELECT COUNT(*) FROM visits WHERE date=?) today''', (dt.date.today().isoformat(),)).fetchone())
                    return self.reply(200, {'patients': [dict(r) for r in rows], 'stats': stats})
                match = re.fullmatch(r'/api/patients/(\d+)(/visits)?', path)
                if path == '/api/patients' and method == 'POST' or match and method == 'PUT' and not match[2]:
                    values = (field(data, 'name', limit=150), date_field(data, 'dob'), field(data, 'phone', False, 50), field(data, 'notes', False))
                    profile = profile_fields(data)
                    if match:
                        pid = int(match[1])
                        if not db.execute('SELECT id FROM patients WHERE id=?', (pid,)).fetchone():
                            return self.reply(404, {'error': 'Patient not found'})
                        db.execute('UPDATE patients SET name=?,dob=?,phone=?,notes=? WHERE id=?', values + (pid,))
                    else:
                        code = patient_code()
                        while db.execute('SELECT id FROM patients WHERE code=?', (code,)).fetchone():
                            code = patient_code()
                        pid = db.execute('INSERT INTO patients(name,dob,phone,notes,code,created) VALUES(?,?,?,?,?,?)', values + (code, dt.date.today().isoformat())).lastrowid
                    db.execute('UPDATE patients SET gender=?,blood_type=?,allergies=?,disabilities=?,height_cm=?,weight_kg=? WHERE id=?', profile + (pid,))
                    return self.reply(200, {'id': pid})
                if match:
                    patient = db.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
                    if not patient:
                        return self.reply(404, {'error': 'Patient not found'})
                    if match[2] and method == 'POST':
                        db.execute('INSERT INTO visits(patient_id,date,reason,medicine,notes) VALUES(?,?,?,?,?)', (patient['id'], date_field(data, 'date'), field(data, 'reason'), field(data, 'medicine'), field(data, 'notes', False)))
                        return self.reply(201, {'ok': True})
                    if not match[2] and method == 'GET':
                        return self.reply(200, {'patient': dict(patient), 'visits': [dict(v) for v in db.execute('SELECT * FROM visits WHERE patient_id=? ORDER BY date DESC,id DESC', (patient['id'],))]})
            self.reply(404, {'error': 'Not found'})
        except (ValueError, TypeError, KeyError):
            self.reply(400, {'error': 'Check the required fields and dates, then try again.'})
        except Exception:
            self.reply(500, {'error': 'Unable to complete request. Please try again.'})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--create-admin', metavar='USERNAME')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    initialize()
    if args.create_admin:
        import getpass
        password = os.environ.get('PROMEDICS_ADMIN_PASSWORD') or getpass.getpass('Admin password (at least 12 characters): ')
        if len(password) < 12:
            raise SystemExit('Use at least 12 characters')
        salt = secrets.token_hex(16)
        with connect() as db:
            db.execute('INSERT INTO admins VALUES(?,?,?)', (args.create_admin, salt, password_hash(password, salt)))
        print('Admin created.')
    else:
        print(f'Promedics listening on port {args.port}', flush=True)
        ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
