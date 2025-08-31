# DANTE_Database.py - Multi-User Version with Fixed Session Management
import os
import sqlite3
import contextlib
import logging
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_socketio import SocketIO, emit
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

## AUTH UPGRADE: Import necessary libraries for authentication and sessions.
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# --- Load environment variables ---
load_dotenv()

# --- Configuration & Validation ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is required")

DATABASE_FILE = "dante_chat_history.db"
MAX_HISTORY_MESSAGES = 50
SUMMARIZATION_THRESHOLD = 40
MESSAGES_TO_SUMMARIZE = 30

# --- Flask App & Authentication Setup ---
app = Flask(__name__)
# It's crucial to set a secret key for session management.
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY", "a-strong-default-secret-key-for-dev")

# FIX: Configure session to expire when browser closes
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # Optional: set a timeout
app.permanent_session_lifetime = timedelta(minutes=30)

socketio = SocketIO(app)

## AUTH UPGRADE: Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Redirect to login page if user is not authenticated

# FIX: Configure Flask-Login session behavior
login_manager.session_protection = "strong"  # This helps with session security

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- AI Configuration ---
client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
universal_role = (
    "You are Dante, a professional AI assistant. Your primary goal is to provide structured and easy-to-scan answers. "
    "ALWAYS format your responses as follows:\n"
    "1. Start with a brief, one-sentence summary of the answer.\n"
    "2. Follow up with the main points presented as a bulleted or numbered list.\n"
    "3. Keep each point concise and to the point.\n"
    "AVOID writing long, dense paragraphs. Prioritize clarity and structure using lists."
)

# --- Database Connection Management ---
@contextlib.contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# --- User Model for Flask-Login ---
## AUTH UPGRADE: User class required by Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with get_db_connection() as conn:
        user_row = conn.execute('SELECT id, username FROM users WHERE id = ?', (user_id,)).fetchone()
        if user_row:
            return User(id=user_row['id'], username=user_row['username'])
    return None

# FIX: Add session cleanup on every request
@app.before_request
def make_session_non_permanent():
    """Ensure sessions don't persist beyond browser closure"""
    session.permanent = False

# --- Database Setup ---
def init_db():
    with get_db_connection() as conn:
        # AUTH UPGRADE: Create users table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        
        # AUTH UPGRADE: Modify history table to use user_id
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_timestamp ON history(user_id, timestamp)")
        
        # AUTH UPGRADE: Modify summaries table to use user_id
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                user_id INTEGER PRIMARY KEY,
                summary_content TEXT NOT NULL,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.commit()
    logger.info("Database initialized with users, history, and summaries tables.")

# --- Database Functions (Now User-Centric) ---
def load_memory_from_db(user_id, max_messages=MAX_HISTORY_MESSAGES):
    memory = [{"role": "system", "content": universal_role}]
    try:
        with get_db_connection() as conn:
            summary_row = conn.execute("SELECT summary_content FROM summaries WHERE user_id = ?", (user_id,)).fetchone()
            if summary_row:
                memory.append({"role": "system", "content": f"Summary of conversation so far: {summary_row['summary_content']}"})

            rows = conn.execute("""
                SELECT role, content FROM history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
            """, (user_id, max_messages)).fetchall()
            
            memory.extend([{"role": row['role'], "content": row['content']} for row in reversed(rows)])
            return memory
    except Exception as e:
        logger.error(f"Error loading memory for user {user_id}: {e}")
        return [{"role": "system", "content": universal_role}]

def add_message_to_db(user_id, role, content):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving message for user {user_id}: {e}")

# --- AI Response & Summarization ---
# --- AI Response & Summarization ---
# Update the model to a supported one
DEFAULT_MODEL = "llama-3.3-70b-versatile"

def get_ai_response(memory, model=DEFAULT_MODEL):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=memory,
            max_tokens=1500,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error connecting to Groq API: {e}")
        return "I'm experiencing technical difficulties. Please try again."

def summarize_conversation(messages, model=DEFAULT_MODEL):
    summary_prompt = [{"role": "system", "content": "Summarize this conversation concisely, capturing key topics and conclusions."}] + messages
    try:
        response = client.chat.completions.create(
            model=model,
            messages=summary_prompt,
            max_tokens=500,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error during summarization: {e}")
        return None


def manage_conversation_history(user_id):
    try:
        with get_db_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM history WHERE user_id = ?", (user_id,)).fetchone()[0]
            if count < SUMMARIZATION_THRESHOLD:
                return

            logger.info(f"History for user {user_id} has {count} messages. Triggering summarization.")
            
            rows_to_summarize = conn.execute("SELECT id, role, content FROM history WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?", (user_id, MESSAGES_TO_SUMMARIZE)).fetchall()
            messages = [{"role": row['role'], "content": row['content']} for row in rows_to_summarize]
            ids_to_delete = [row['id'] for row in rows_to_summarize]

            new_summary_part = summarize_conversation(messages)
            if not new_summary_part:
                return

            existing_summary = conn.execute("SELECT summary_content FROM summaries WHERE user_id = ?", (user_id,)).fetchone()
            full_summary = f"{existing_summary['summary_content'] if existing_summary else ''}\n\n{new_summary_part}".strip()

            conn.execute("""
                INSERT INTO summaries (user_id, summary_content, last_updated) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET summary_content = excluded.summary_content, last_updated = excluded.last_updated;
            """, (user_id, full_summary))

            if ids_to_delete:
                conn.execute(f"DELETE FROM history WHERE id IN ({','.join('?' for _ in ids_to_delete)})", ids_to_delete)
            
            conn.commit()
            logger.info(f"Successfully summarized and pruned history for user {user_id}.")
    except Exception as e:
        logger.error(f"Error managing history for user {user_id}: {e}")

# --- Flask Routes for Authentication ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db_connection() as conn:
            user_row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user_row and check_password_hash(user_row['password_hash'], password):
                user = User(id=user_row['id'], username=user_row['username'])
                # FIX: Ensure session doesn't persist beyond browser closure
                login_user(user, remember=False)
                session.permanent = False  # Explicitly set session as non-permanent
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db_connection() as conn:
            if conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
                flash('Username already exists.')
            else:
                conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                             (username, generate_password_hash(password)))
                conn.commit()
                flash('Registration successful! Please log in.')
                return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    # FIX: Clear the entire session to ensure clean logout
    session.clear()
    return redirect(url_for('login'))

# --- Main Chat Route ---
@app.route('/')
@login_required
def index():
    # Pass the username to the template
    return render_template('index.html', username=current_user.username)

# --- Add logout route for frontend access ---
@app.route('/api/logout')
@login_required
def api_logout():
    logout_user()
    session.clear()
    return {'status': 'success', 'message': 'Logged out successfully'}

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False # Disconnect unauthorized users
    logger.info(f"User {current_user.username} (ID: {current_user.id}) connected.")
    emit('response', {'data': f"Welcome back, {current_user.username}! How can I help you?"})

@socketio.on('user_message')
def handle_user_message(json_data):
    if not current_user.is_authenticated:
        return
    
    user_message = json_data.get('message', '').strip()
    if not user_message:
        return

    user_id = current_user.id
    logger.info(f"Processing message from user {user_id}: {user_message[:50]}...")
    
    try:
        add_message_to_db(user_id, "user", user_message)
        memory = load_memory_from_db(user_id)
        ai_response = get_ai_response(memory)
        add_message_to_db(user_id, "assistant", ai_response)
        
        emit('response', {'data': ai_response})
        socketio.start_background_task(manage_conversation_history, user_id)
    except Exception as e:
        logger.error(f"Error processing message for user {user_id}: {e}")
        emit('response', {'data': "An error occurred while processing your request."})

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        logger.info(f"User {current_user.username} disconnected.")

# --- Main ---
if __name__ == '__main__':
    init_db()
    logger.info("Starting DANTE multi-user chatbot server...")
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)