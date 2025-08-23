# DANTE2.py
import os
import json
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from openai import OpenAI
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

# --- AI Configuration ---
client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
MEMORY_FILE = "dante_memory.json"
universal_role = (
    "You are Dante, a versatile and stylish AI assistant with the ability to generate code, "
    "explain concepts, fetch info, give advice, and more. "
    "Speak in a confident, witty tone like Dante from Devil May Cry. Keep your responses concise and to the point."
)

# --- Flask App & SocketIO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key!'
socketio = SocketIO(app, cors_allowed_origins="*")  # Allow CORS for local testing

# --- Memory Functions ---
def load_memory():
    """Load conversation history or initialize with system prompt."""
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return [{"role": "system", "content": universal_role}]

def save_memory(memory):
    """Save conversation history."""
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=4)

# --- Chat Function ---
def groq_chat_with_memory(memory, user_input, model="llama3-8b-8192"):
    """Send user input to Groq API and get AI response, maintaining memory."""
    memory.append({"role": "user", "content": user_input})
    try:
        response = client.chat.completions.create(
            model=model,
            messages=memory
        )
        reply = response.choices[0].message.content
        memory.append({"role": "assistant", "content": reply})
        save_memory(memory)
        return reply
    except Exception as e:
        print(f"Error connecting to Groq API: {e}")
        return "Oops! Dante is having some trouble. Try again in a minute."

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    print("DEBUG: Client connected!")
    emit('response', {'data': "Locked and loaded. What's the job?"})

@socketio.on('user_message')
def handle_user_message(json_data):
    print(f"DEBUG: Received user message: {json_data}")
    user_message = json_data.get('message', '')
    if not user_message:
        return
    memory = load_memory()
    ai_response = groq_chat_with_memory(memory, user_message)
    print(f"DEBUG: Sending AI response: {ai_response}")
    emit('response', {'data': ai_response})

# --- Main ---
if __name__ == '__main__':
    # Use debug=False if you don't want hot reload, but debug=True is okay for local testing
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
