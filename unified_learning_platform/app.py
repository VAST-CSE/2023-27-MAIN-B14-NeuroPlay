import json, os, sqlite3, uuid
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'platform.db')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')

GAMES = {
    'reading': {'name': 'Reading Adventure', 'icon': '🦊', 'color': 'reading', 'description': 'Sounds, letters, decoding, memory, fluency and comprehension.'},
    'number': {'name': 'Treasure Number Race', 'icon': '🏴‍☠️', 'color': 'number', 'description': 'Number sense, magnitude comparison and numerical distance.'},
    'focus': {'name': 'Focus Balloon Pop', 'icon': '🎈', 'color': 'focus', 'description': 'Selective attention, inhibition and reaction-time practice.'},
}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = db()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS parents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        age INTEGER NOT NULL,
        grade TEXT DEFAULT '',
        language TEXT DEFAULT 'English',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(parent_id) REFERENCES parents(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS results (
        id TEXT PRIMARY KEY,
        parent_id INTEGER NOT NULL,
        child_id INTEGER NOT NULL,
        game_key TEXT NOT NULL,
        score REAL,
        accuracy REAL,
        duration_ms INTEGER,
        payload_json TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(parent_id) REFERENCES parents(id) ON DELETE CASCADE,
        FOREIGN KEY(child_id) REFERENCES children(id) ON DELETE CASCADE
    );
    ''')
    con.commit(); con.close()

init_db()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'parent_id' not in session:
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def get_child(child_id):
    con = db(); row = con.execute('SELECT * FROM children WHERE id=? AND parent_id=?', (child_id, session['parent_id'])).fetchone(); con.close(); return row

@app.route('/')
def index():
    if 'parent_id' in session: return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name','').strip(); email = request.form.get('email','').strip().lower(); password = request.form.get('password','')
        if not name or not email or len(password) < 6:
            flash('Enter your name, a valid email, and a password of at least 6 characters.', 'error'); return render_template('register.html')
        con = db()
        try:
            cur = con.execute('INSERT INTO parents(name,email,password_hash) VALUES(?,?,?)', (name,email,generate_password_hash(password)))
            con.commit(); session['parent_id']=cur.lastrowid; session['parent_name']=name
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            flash('An account with that email already exists.', 'error')
        finally: con.close()
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        con=db(); p=con.execute('SELECT * FROM parents WHERE email=?',(email,)).fetchone(); con.close()
        if p and check_password_hash(p['password_hash'], password):
            session.clear(); session['parent_id']=p['id']; session['parent_name']=p['name']; return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Incorrect email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/milestone')
@login_required
def milestone():
    # Open the original Milestone app inside the same platform.
    # The original RAR archive remains unchanged in static/milestone/.
    return send_from_directory(os.path.join(BASE, 'static', 'milestone_app'), 'index.html')

@app.route('/assets/<path:filename>')
def milestone_assets(filename):
    # Assets belong to the original built Milestone page.
    return send_from_directory(os.path.join(BASE, 'static', 'milestone_app', 'assets'), filename)

@app.route('/dashboard')
@login_required
def dashboard():
    con=db(); children=con.execute('SELECT * FROM children WHERE parent_id=? ORDER BY name',(session['parent_id'],)).fetchall()
    selected_id=request.args.get('child', type=int)
    if not selected_id and children: selected_id=children[0]['id']
    child=None; results=[]
    if selected_id:
        child=con.execute('SELECT * FROM children WHERE id=? AND parent_id=?',(selected_id,session['parent_id'])).fetchone()
        results=con.execute('SELECT * FROM results WHERE child_id=? AND parent_id=? ORDER BY created_at DESC',(selected_id,session['parent_id'])).fetchall()
    con.close()
    return render_template('dashboard.html', children=children, child=child, results=results, games=GAMES)

@app.route('/children/add', methods=['POST'])
@login_required
def add_child():
    name=request.form.get('name','').strip(); age=request.form.get('age', type=int); grade=request.form.get('grade','').strip(); language=request.form.get('language','English').strip() or 'English'
    if not name or not age or age<5 or age>10: flash('Please enter a child name and an age from 5 to 10.', 'error'); return redirect(url_for('dashboard'))
    con=db(); con.execute('INSERT INTO children(parent_id,name,age,grade,language) VALUES(?,?,?,?,?)',(session['parent_id'],name,age,grade,language)); con.commit(); con.close(); flash('Child profile added.', 'success'); return redirect(url_for('dashboard'))

@app.route('/game/<game_key>/<int:child_id>')
@login_required
def game(game_key, child_id):
    if game_key not in GAMES: return 'Game not found',404
    child=get_child(child_id)
    if not child: return 'Child not found',404
    return render_template(f'game_{game_key}.html', game=GAMES[game_key], child=child)

@app.route('/api/results', methods=['POST'])
@login_required
def save_result():
    data=request.get_json(force=True); child_id=int(data.get('child_id',0)); game_key=data.get('game_key')
    if game_key not in GAMES or not get_child(child_id): return jsonify({'ok':False,'error':'Invalid game or child'}),400
    rid=str(uuid.uuid4()); payload=data.get('payload',{})
    con=db(); con.execute('INSERT INTO results(id,parent_id,child_id,game_key,score,accuracy,duration_ms,payload_json) VALUES(?,?,?,?,?,?,?,?)',(rid,session['parent_id'],child_id,game_key,data.get('score'),data.get('accuracy'),data.get('duration_ms'),json.dumps(payload))); con.commit(); con.close()
    return jsonify({'ok':True,'id':rid,'redirect':url_for('dashboard',child=child_id)})

@app.route('/report/<int:child_id>')
@login_required
def report(child_id):
    child=get_child(child_id)
    if not child: return 'Child not found',404
    con=db(); rows=con.execute('SELECT * FROM results WHERE child_id=? AND parent_id=? ORDER BY created_at DESC',(child_id,session['parent_id'])).fetchall(); con.close()
    # Aggregate game-level profile. These are descriptive prototype metrics, not clinical norms.
    game_stats=[]
    for key,g in GAMES.items():
        rr=[r for r in rows if r['game_key']==key]
        if rr:
            acc=[r['accuracy'] for r in rr if r['accuracy'] is not None]
            game_stats.append({'key':key,'name':g['name'],'icon':g['icon'],'sessions':len(rr),'accuracy':round(sum(acc)/len(acc),1) if acc else None})
        else: game_stats.append({'key':key,'name':g['name'],'icon':g['icon'],'sessions':0,'accuracy':None})
    return render_template('report.html', child=child, rows=rows, game_stats=game_stats, games=GAMES)

if __name__=='__main__':
    port = int(os.environ.get("PORT",10000))
    app.run(debug=True, host='127.0.0.1', port=5000)
