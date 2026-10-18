"""Initialize a hosted installation, then start the application."""
import os
import sys

import server

server.initialize()
with server.connect() as db:
    has_admin = db.execute('SELECT 1 FROM admins LIMIT 1').fetchone()
    if not has_admin:
        username = os.environ.get('PROMEDICS_ADMIN_USERNAME', 'admin')
        password = os.environ.get('PROMEDICS_ADMIN_PASSWORD', '')
        if len(password) < 12:
            raise SystemExit('Set PROMEDICS_ADMIN_PASSWORD to at least 12 characters in hosting settings.')
        salt = server.secrets.token_hex(16)
        db.execute('INSERT INTO admins VALUES(?,?,?)', (username, salt, server.password_hash(password, salt)))
        print('Initial administrator created. Credentials are available in hosting settings.', flush=True)

# The password is only needed for the first initialization.
os.environ.pop('PROMEDICS_ADMIN_PASSWORD', None)
os.execv(sys.executable, [sys.executable, 'server.py', '--host', '0.0.0.0', '--port', os.environ.get('PORT', '8000')])
