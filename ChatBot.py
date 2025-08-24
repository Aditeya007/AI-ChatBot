# DANTE_Database.py - Improved Version
import os
import sqlite3
import contextlib
import logging
import time
from collections import defaultdict
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# --- Load environment variables ---
load_dotenv()

# --- Configuration & Validation ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is required")

DATABASE_FILE = "dante_chat_history.db"
MAX_MESSAGE_LENGTH = 1000
MAX_HISTORY_MESSAGES = 50

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Rate Limiting ---
user_requests = defaultdict(list)

def is_rate_limited(session_id, max_requests=10, time_window=60):
    """Simple rate limiting: max_requests per time_window seconds."""
    now = time.time()
    requests = user_requests[session_id]
    
    # Remove old requests
    user_requests[session_id] = [req_time for req_time in requests if now - req_time < time_window]
    
    if len(user_requests[session_id]) >= max_requests:
        return True
    
    user_requests[session_id].append(now)
    return False

# --- AI Configuration ---
client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
universal_role = (
    "You are Dante, a professional AI assistant. Your purpose is to provide clear, accurate, and concise information. "
    "You can assist with code generation, explaining complex concepts, providing information, and offering well-reasoned advice. "
    "Communicate in a friendly, helpful, and direct tone. Structure complex information with lists or bullet points where appropriate."
)

# --- Database Connection Management ---
@contextlib.contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        yield conn
    finally:
        conn.close()

# --- Database Setup ---
def init_db():
    """Initializes the database and creates the history table if it doesn't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add index for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_timestamp ON history(session_id, timestamp)")
        conn.commit()
    logger.info("Database initialized successfully")

# --- Database Functions ---
def load_memory_from_db(session_id, max_messages=MAX_HISTORY_MESSAGES):
    """Load recent conversation history for a specific session from the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, content FROM history 
                WHERE session_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (session_id, max_messages))
            rows = cursor.fetchall()
        
        # Reverse to get chronological order
        rows.reverse()
        
        # Start with the system role and add the conversation history
        memory = [{"role": "system", "content": universal_role}]
        for row in rows:
            memory.append({"role": row[0], "content": row[1]})
        return memory
    except Exception as e:
        logger.error(f"Error loading memory from database: {e}")
        return [{"role": "system", "content": universal_role}]

def add_message_to_db(session_id, role, content):
    """Save a new message to the database for a specific session."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO history (session_id, role, content) VALUES (?, ?, ?)", 
                          (session_id, role, content))
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving message to database: {e}")

def cleanup_old_sessions(days_old=30):
    """Remove conversation history older than specified days."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM history 
                WHERE timestamp < datetime('now', '-{} days')
            """.format(days_old))
            deleted_count = cursor.rowcount
            conn.commit()
        logger.info(f"Cleaned up {deleted_count} old messages (older than {days_old} days)")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# --- Input Validation ---
def validate_message(message):
    """Validate user message input."""
    if not message or not isinstance(message, str):
        return False, "Invalid message format"
    
    message = message.strip()
    if not message:
        return False, "Please enter a message"
    
    if len(message) > MAX_MESSAGE_LENGTH:
        return False, f"Message too long (max {MAX_MESSAGE_LENGTH} characters)"
    
    return True, None

# --- AI Response Function ---
def get_ai_response(memory, model="llama3-8b-8192"):
    """Send conversation history to Groq API and get AI response."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=memory,
            max_tokens=1000,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error connecting to Groq API: {e}")
        return "I'm experiencing technical difficulties. Please try again in a moment."

# --- Flask App & SocketIO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key!'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    session_id = request.sid
    logger.info(f"Client connected with session ID: {session_id}")
    emit('response', {'data': "Hey there! Need some help?"})

@socketio.on('user_message')
def handle_user_message(json_data):
    session_id = request.sid
    user_message = json_data.get('message', '').strip()
    
    # Input validation
    is_valid, error_msg = validate_message(user_message)
    if not is_valid:
        emit('response', {'data': error_msg})
        return
    
    # Rate limiting
    if is_rate_limited(session_id):
        emit('response', {'data': "Please slow down. Too many requests in a short time."})
        return
    
    logger.info(f"Processing message from {session_id}: {user_message[:50]}...")
    
    try:
        # Save the user's message to the DB
        add_message_to_db(session_id, "user", user_message)
        
        # Load the full conversation history for this session
        memory = load_memory_from_db(session_id)
        
        # Get the AI's response
        ai_response = get_ai_response(memory)
        
        # Save the AI's response to the DB
        add_message_to_db(session_id, "assistant", ai_response)
        
        logger.info(f"Successfully processed message for session {session_id}")
        emit('response', {'data': ai_response})
        
    except Exception as e:
        logger.error(f"Error processing message for session {session_id}: {e}")
        emit('response', {'data': "An error occurred while processing your request. Please try again."})

@socketio.on('disconnect')
def handle_disconnect():
    session_id = request.sid
    logger.info(f"Client disconnected: {session_id}")
    # Clean up rate limiting data for disconnected users
    if session_id in user_requests:
        del user_requests[session_id]

# --- Main ---
if __name__ == '__main__':
    try:
        init_db()
        # Optional: Clean up old sessions on startup
        cleanup_old_sessions(30)
        logger.info("Starting DANTE chatbot server...")
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise