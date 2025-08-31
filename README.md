# AI ChatBot - DANTE

A **Flask-based multi-user AI chatbot** application that provides real-time conversations with an AI assistant named **"Dante"** using **Groq's API**.

---

## 🚀 Features
- **Multi-user authentication system** with secure password hashing *(ChatBot.py:74-87)*
- **Real-time chat interface** using Socket.IO for bidirectional communication *(ChatBot.py:272-307)*
- **Intelligent conversation memory management** with automatic summarization *(ChatBot.py:177-208)*
- **Persistent chat history** stored in SQLite database *(ChatBot.py:96-130)*
- **Modern responsive UI** with theme switching capabilities *(index.html:912-926)*

---

## 🛠 Technology Stack
- **Backend:** Flask, Flask-SocketIO, Flask-Login  
- **Database:** SQLite (optimized schema for multi-user chat history)  
- **AI Integration:** OpenAI Client with Groq API  
- **Frontend:** HTML5, CSS3, JavaScript with Socket.IO client  
- **Authentication:** Werkzeug password hashing *(ChatBot.py:7-15)*  

---

## ⚙️ Installation

1. **Clone the repository**
   git clone https://github.com/Aditeya007/AI-ChatBot.git
   cd AI-ChatBot
   
2. Install dependencies
   pip install flask flask-socketio flask-login openai python-dotenv
   
3. Set up environment variables
   Create a .env file in the project root:
   GROQ_API_KEY=your_groq_api_key_here
   FLASK_SECRET_KEY=your_secret_key_here

4. Run the application
   python ChatBot.py

Usage

1.Register a new account at /register or login with existing credentials at /login (ChatBot.py:211-246)

2.Start chatting with Dante on the main interface (ChatBot.py:257-261)

3.Switch themes using the theme toggle button (index.html:918-922)

4.Logout using the logout button in the user section (index.html:798-801)

🏗 Architecture

The application uses a three-table SQLite database design:

users: User credentials and authentication

history: Individual chat messages with user association

summaries: Conversation summaries for memory optimization
(ChatBot.py:96-130)

🧠 Memory Management

The system implements intelligent conversation memory management with configurable thresholds:

MAX_HISTORY_MESSAGES = 50 → Maximum messages kept in active memory

SUMMARIZATION_THRESHOLD = 40 → Message count that triggers summarization

MESSAGES_TO_SUMMARIZE = 30 → Number of oldest messages to summarize and prune
(ChatBot.py:25-28)

🔧 Configuration

Requires GROQ_API_KEY (environment variable)

Optionally accepts FLASK_SECRET_KEY for session management (ChatBot.py:32-37)

Database file automatically created as dante_chat_history.db in the app root (ChatBot.py:25)

🔒 Security Features

Session security with non-permanent sessions (expire on browser closure) (ChatBot.py:89-94)

Password hashing using Werkzeug's secure methods (ChatBot.py:14)

Authentication protection on all chat routes (ChatBot.py:274-276)
