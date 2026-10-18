import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.database = str(Path(cls.temp.name) / 'test.sqlite3')
        cls.env = dict(os.environ, PROMEDICS_DB=cls.database, PROMEDICS_ADMIN_PASSWORD='Test-only-password-2026')
        subprocess.run([sys.executable, 'server.py', '--create-admin', 'admin'], cwd=ROOT, env=cls.env, check=True, capture_output=True)
        cls.process = subprocess.Popen([sys.executable, 'server.py', '--port', '18008'], cwd=ROOT, env=cls.env, stdout=subprocess.DEVNULL)
        cls.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for _ in range(50):
            try:
                urllib.request.urlopen('http://127.0.0.1:18008/').close()
                break
            except OSError:
                time.sleep(.1)
        cls.csrf = ''

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.temp.cleanup()

    def request(self, path, method='GET', data=None, csrf=True):
        request = urllib.request.Request('http://127.0.0.1:18008'+path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type':'application/json', 'X-CSRF-Token':self.csrf if csrf else ''})
        try:
            with self.client.open(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_patient_workflow_and_access_controls(self):
        self.assertEqual(self.request('/api/patients')[0], 401)
        self.assertEqual(self.request('/api/login', 'POST', {'username':'admin','password':'incorrect'})[0],401)
        status, session = self.request('/api/login','POST',{'username':'admin','password':'Test-only-password-2026'})
        self.assertEqual(status,200)
        self.csrf = session['csrf']
        patient = {'name':'Test Patient','dob':'1990-04-12','phone':'555 0123','notes':'Fictional record','gender':'Female','blood_type':'O+','allergies':'Penicillin: rash','disabilities':'Wheelchair access','height_cm':'168.5','weight_kg':'64'}
        self.assertEqual(self.request('/api/patients','POST',patient,csrf=False)[0],403)
        status, created = self.request('/api/patients','POST',patient)
        self.assertEqual(status,200)
        pid = created['id']
        status, result = self.request('/api/patients?q=test')
        self.assertEqual(len(result['patients']),1)
        code = result['patients'][0]['code']
        self.assertRegex(code,r'^[A-Z0-9]{7}$')
        self.assertTrue(re.search('[A-Z]',code) and re.search('[0-9]',code))
        self.assertEqual(len(self.request('/api/patients?q='+code.lower())[1]['patients']),1)
        second = self.request('/api/patients','POST',dict(patient, name='Second Patient', code=code))[1]
        second_record = self.request('/api/patients/'+str(second['id']))[1]['patient']
        self.assertNotEqual(second_record['code'], code)
        patient['name'] = 'Updated Patient'
        patient['allergies'] = 'Penicillin: rash; latex'
        invalid = dict(patient, height_cm='-1')
        self.assertEqual(self.request(f'/api/patients/{pid}','PUT',invalid)[0],400)
        self.assertEqual(self.request(f'/api/patients/{pid}','PUT',dict(patient,blood_type='X+'))[0],400)
        self.assertEqual(self.request(f'/api/patients/{pid}','PUT',patient)[0],200)
        for date, reason, medicine in [('2025-01-12','Routine check','None'),('2025-02-12','Headache','Example medicine, as prescribed')]:
            self.assertEqual(self.request(f'/api/patients/{pid}/visits','POST',{'date':date,'reason':reason,'medicine':medicine,'notes':'Fictional visit'})[0],201)
        record = self.request(f'/api/patients/{pid}')[1]
        self.assertEqual(record['patient']['name'],'Updated Patient')
        self.assertEqual(record['patient']['code'],code)
        for key in ['gender','blood_type','allergies','disabilities','height_cm','weight_kg']:
            self.assertEqual(record['patient'][key],patient[key])
        self.assertEqual(record['visits'][0]['reason'],'Headache')
        self.assertEqual(record['visits'][0]['medicine'],'Example medicine, as prescribed')
        self.assertEqual(len(record['visits']),2)
        self.assertEqual(self.request(f'/api/patients/{pid}/visits','POST',{'date':'2099-01-01','reason':'Invalid','medicine':'None'})[0],400)
        self.assertEqual(self.request('/api/patients?q=missing')[1]['patients'],[])
        self.assertEqual(self.request('/api/patients/99999')[0],404)
        self.assertEqual(self.request('/api/logout','POST',{})[0],200)
        self.assertEqual(self.request(f'/api/patients/{pid}')[0],401)
        import sqlite3
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM visits').fetchone()[0],2)

class Migration(unittest.TestCase):
    def test_existing_patient_is_preserved(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'legacy.sqlite3')
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, dob TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL)")
                db.execute("INSERT INTO patients VALUES(1,'ABC1234','Existing Patient','1990-01-01','','','2025-01-01')")
            script = "import server; server.initialize(); server.initialize()"
            subprocess.run([sys.executable, '-c', script],cwd=ROOT,env=dict(os.environ,PROMEDICS_DB=path),check=True)
            with sqlite3.connect(path) as db:
                row = db.execute('SELECT name,code,allergies,height_cm FROM patients').fetchone()
                self.assertEqual(row,('Existing Patient','ABC1234','',''))

if __name__ == '__main__':
    unittest.main()
