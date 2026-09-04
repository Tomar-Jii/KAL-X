# ============================================
# 🚀 KAL-X - FAST CHAT API & WEB UI FOR VERCEL 🚀
# Developer: Tomar Ji
# Ready for Vercel Deployment
# ============================================

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
import json
import re
import uuid
import time
import sqlite3
import os
import logging
from datetime import datetime
from functools import lru_cache
from bs4 import BeautifulSoup
from collections import defaultdict

# ============================================
# APP INITIALIZATION
# ============================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'KAL-X-chat-api-2026'
CORS(app, origins='*')

rate_limits = defaultdict(list)

def check_rate_limit(ip, limit=100, window=60):
    now = time.time()
    rate_limits[ip] = [t for t in rate_limits[ip] if t > now - window]
    if len(rate_limits[ip]) >= limit:
        return False
    rate_limits[ip].append(now)
    return True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# DATABASE SETUP (SQLite for Vercel)
# ============================================

def init_database():
    try:
        db_path = '/tmp/kalx_chat.db'
        if not os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                response TEXT NOT NULL,
                time_taken REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.commit()
            conn.close()
            logger.info("Database initialized!")
        return db_path
    except Exception as e:
        logger.error(f"Database error: {e}")
        return None

DB_PATH = init_database()

def get_db():
    if DB_PATH:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    return None

# ============================================
# GEMINI API SCRAPER LOGIC
# ============================================

session_cache = {
    'data': None,
    'timestamp': 0,
    'ttl': 300
}

def extract_snlm0e_token(html):
    patterns = [
        r'"SNlM0e":"([^"]+)"',
        r"'SNlM0e':'([^']+)'",
        r'SNlM0e["\']?\\s*[:=]\\s*["\']([^"\']+)["\']',
        r'"FdrFJe":"([^"]+)"',
        r"'FdrFJe':'([^']+)'",
        r'FdrFJe["\']?\\s*[:=]\\s*["\']([^"\']+)["\']',
        r'"cfb2h":"([^"]+)"',
        r"'cfb2h':'([^']+)'",
        r'cfb2h["\']?\\s*[:=]\\s*["\']([^"\']+)["\']',
        r'at["\']?\\s*[:=]\\s*["\']([^"\']{50,})["\']',
        r'"at":"([^"]+)"',
        r'"token":"([^"]+)"',
        r'data-token["\']?\\s*=\\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            token = match.group(1)
            if len(token) > 20:
                return token
    return None

def extract_from_script_tags(html):
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script'):
        if script.string:
            if 'SNlM0e' in script.string or 'FdrFJe' in script.string:
                token = extract_snlm0e_token(script.string)
                if token:
                    return token
    return None

def extract_build_and_session_params(html):
    params = {}
    bl_match = re.search(r'bl["\']?\\s*[:=]\\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    if bl_match:
        params['bl'] = bl_match.group(1)
    fsid_match = re.search(r'f\\.sid["\']?\\s*[:=]\\s*["\']?([^"\'&\\s]+)', html, re.IGNORECASE)
    if fsid_match:
        params['fsid'] = fsid_match.group(1)
    reqid_match = re.search(r'_reqid["\']?\\s*[:=]\\s*["\']?(\\d+)', html)
    if reqid_match:
        params['reqid'] = int(reqid_match.group(1))
    
    if not params.get('bl'):
        params['bl'] = 'boq_assistant-bard-web-server_20251217.07_p5'
    if not params.get('fsid'):
        params['fsid'] = str(-1 * int(time.time() * 1000))
    if not params.get('reqid'):
        params['reqid'] = int(time.time() * 1000) % 1000000
    return params

def get_cached_session():
    current_time = time.time()
    if session_cache['data'] and (current_time - session_cache['timestamp']) < session_cache['ttl']:
        return session_cache['data']
    
    session = requests.Session()
    url = 'https://gemini.google.com/app'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache'
    }
    try:
        response = session.get(url, headers=headers, timeout=15)
        html = response.text
        cookies = {c.name: c.value for c in session.cookies}
        snlm0e = extract_snlm0e_token(html) or extract_from_script_tags(html)
        if not snlm0e:
            return None
        params = extract_build_and_session_params(html)
        session_data = {
            'session': session,
            'cookies': cookies,
            'snlm0e': snlm0e,
            'bl': params['bl'],
            'fsid': params['fsid'],
            'reqid': params['reqid']
        }
        session_cache['data'] = session_data
        session_cache['timestamp'] = current_time
        return session_data
    except Exception as e:
        logger.error(f"Session error: {e}")
        return None

def build_payload(prompt, snlm0e):
    escaped_prompt = prompt.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    session_id = uuid.uuid4().hex
    request_uuid = str(uuid.uuid4()).upper()
    
    payload_data = [
        [escaped_prompt, 0, None, None, None, None, 0],
        ["en-US"],
        ["", "", "", None, None, None, None, None, None, ""],
        snlm0e,
        session_id,
        None,
        [0],
        1,
        None, None, 1, 0, None, None, None, None, None,
        [[0]],
        0,
        None, None, None, None, None, None, None, None, 1,
        None, None, [4], None, None, None, None, None, None, None, None, None, None, [2],
        None, None, None, None, None, None, None, None, None, None, None, 0,
        None, None, None, None, None,
        request_uuid,
        None,
        []
    ]
    payload_str = json.dumps(payload_data, separators=(',', ':'))
    escaped_payload = payload_str.replace('\\', '\\\\').replace('"', '\\"')
    return {
        'f.req': f'[null,"{escaped_payload}"]',
        '': ''
    }

def parse_streaming_response(response_text):
    lines = response_text.strip().split('\n')
    full_text = ""
    for line in lines:
        if not line or line.startswith(')]}'):
            continue
        try:
            if line.isdigit():
                continue
            data = json.loads(line)
            if isinstance(data, list) and len(data) > 0:
                if data[0][0] == "wrb.fr" and len(data[0]) > 2:
                    inner_json = data[0][2]
                    if inner_json:
                        parsed = json.loads(inner_json)
                        if isinstance(parsed, list) and len(parsed) > 4:
                            content_array = parsed[4]
                            if isinstance(content_array, list) and len(content_array) > 0:
                                first_item = content_array[0]
                                if isinstance(first_item, list) and len(first_item) > 0:
                                    response_id = first_item[0]
                                    if isinstance(response_id, str) and response_id.startswith('rc_'):
                                        if len(first_item) > 1 and isinstance(first_item[1], list):
                                            text_array = first_item[1]
                                            if len(text_array) > 0:
                                                text_content = text_array[0]
                                                if isinstance(text_content, str) and len(text_content) > len(full_text):
                                                    full_text = text_content
        except:
            continue
    if full_text:
        full_text = full_text.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    return full_text if full_text else None

@lru_cache(maxsize=50)
def chat_with_gemini_cached(prompt):
    return chat_with_gemini(prompt)

def chat_with_gemini(prompt):
    start_time = time.time()
    scraped = get_cached_session()
    if not scraped:
        return {'success': False, 'error': 'Connection busy, retry!', 'time_taken': 0}
    
    session = scraped['session']
    cookies = scraped['cookies']
    snlm0e = scraped['snlm0e']
    bl = scraped['bl']
    fsid = scraped['fsid']
    reqid = scraped['reqid']
    
    base_url = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
    url = f"{base_url}?bl={bl}&f.sid={fsid}&hl=en-US&_reqid={reqid}&rt=c"
    payload = build_payload(prompt, snlm0e)
    cookie_str = '; '.join([f"{k}={v}" for k, v in cookies.items()])
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-US,en;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'x-same-domain': '1',
        'origin': 'https://gemini.google.com',
        'referer': 'https://gemini.google.com/',
        'Cookie': cookie_str
    }
    try:
        response = session.post(url, data=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            return {'success': False, 'error': f'Error {response.status_code}', 'time_taken': round(time.time() - start_time, 3)}
        result = parse_streaming_response(response.text)
        time_taken = round(time.time() - start_time, 3)
        if result:
            return {'success': True, 'response': result, 'time_taken': time_taken}
        return {'success': False, 'error': 'No response generated!', 'time_taken': time_taken}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {'success': False, 'error': str(e), 'time_taken': round(time.time() - start_time, 3)}

# ============================================
# DATABASE HELPERS
# ============================================

def save_chat(question, response, time_taken):
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute("INSERT INTO chats (question, response, time_taken, timestamp) VALUES (?, ?, ?, ?)",
                      (question, response, time_taken, datetime.now()))
            conn.commit()
            conn.close()
            return True
        return False
    except:
        return False

def get_chat_history(limit=100):
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute("SELECT id, question, response, time_taken, timestamp FROM chats ORDER BY timestamp DESC LIMIT ?", (limit,))
            history = [{'id': r['id'], 'question': r['question'], 'response': r['response'], 'time_taken': r['time_taken'], 'timestamp': r['timestamp']} for r in c.fetchall()]
            conn.close()
            return history
        return []
    except:
        return []

def clear_chat_history():
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute("DELETE FROM chats")
            conn.commit()
            conn.close()
            return True
        return False
    except:
        return False

# ============================================
# WEB UI TEMPLATE
# ============================================

HTML_UI = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>KAL-X AI</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card: #121826;
      --card-border: #1e293b;
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.25);
      --text: #f1f5f9;
      --text-dim: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; -webkit-tap-highlight-color: transparent; }
    body { background-color: var(--bg); color: var(--text); height: 100dvh; display: flex; flex-direction: column; overflow: hidden; }
    
    header {
      padding: 12px 18px;
      background: rgba(18, 24, 38, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 10px; }
    .status-dot { width: 9px; height: 9px; background: #10b981; border-radius: 50%; box-shadow: 0 0 10px #10b981; }
    .brand h1 { font-size: 1.15rem; font-weight: 700; letter-spacing: 0.5px; }
    .brand span { font-size: 0.72rem; color: var(--text-dim); }
    .clear-btn { background: transparent; border: 1px solid var(--card-border); color: var(--text-dim); padding: 5px 12px; border-radius: 8px; font-size: 0.8rem; cursor: pointer; transition: 0.2s; }
    .clear-btn:hover { border-color: #ef4444; color: #ef4444; }

    #chat-container {
      flex: 1;
      overflow-y: auto;
      padding: 18px 14px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      scroll-behavior: smooth;
    }
    .bubble {
      max-width: 86%;
      padding: 12px 16px;
      border-radius: 16px;
      font-size: 0.95rem;
      line-height: 1.5;
      word-break: break-word;
      animation: fadeIn 0.2s ease-out;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
    .user-bubble {
      align-self: flex-end;
      background: linear-gradient(135deg, var(--accent), #4f46e5);
      color: #fff;
      border-bottom-right-radius: 4px;
      box-shadow: 0 4px 15px var(--accent-glow);
    }
    .bot-bubble {
      align-self: flex-start;
      background: var(--card);
      border: 1px solid var(--card-border);
      color: var(--text);
      border-bottom-left-radius: 4px;
    }
    .meta { font-size: 0.7rem; color: var(--text-dim); margin-top: 6px; display: block; }

    #input-container {
      padding: 12px 14px;
      background: var(--card);
      border-top: 1px solid var(--card-border);
      display: flex;
      gap: 8px;
      align-items: center;
    }
    #user-input {
      flex: 1;
      background: #0b0f19;
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 12px 16px;
      color: #fff;
      font-size: 0.95rem;
      outline: none;
      transition: 0.2s;
    }
    #user-input:focus { border-color: var(--accent); box-shadow: 0 0 10px var(--accent-glow); }
    #send-btn {
      background: var(--accent);
      border: none;
      color: white;
      padding: 12px 18px;
      border-radius: 12px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: 0.2s;
    }
    #send-btn:active { transform: scale(0.96); }
    .loading-dots span {
      display: inline-block; width: 6px; height: 6px; background: var(--text-dim); border-radius: 50%;
      margin: 0 2px; animation: bounce 1.2s infinite ease-in-out;
    }
    .loading-dots span:nth-child(2) { animation-delay: 0.2s; }
    .loading-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="status-dot"></div>
      <div>
        <h1>KAL-X AI</h1>
        <span>by Tomar Ji</span>
      </div>
    </div>
    <button class="clear-btn" onclick="clearUI()">Clear</button>
  </header>

  <div id="chat-container">
    <div class="bubble bot-bubble">
      Yo! Main KAL-X AI hoon — created by Tomar Ji. Boliye, kya madad karu aaj?
    </div>
  </div>

  <div id="input-container">
    <input type="text" id="user-input" placeholder="Type your message..." autocomplete="off" onkeydown="if(event.key==='Enter') sendMessage()">
    <button id="send-btn" onclick="sendMessage()">Send</button>
  </div>

  <script>
    const chatContainer = document.getElementById('chat-container');
    const userInput = document.getElementById('user-input');

    async function sendMessage() {
      const text = userInput.value.trim();
      if (!text) return;

      appendBubble(text, 'user-bubble');
      userInput.value = '';

      const loaderId = appendLoader();
      chatContainer.scrollTop = chatContainer.scrollHeight;

      try {
        const res = await fetch(`/chat?q=${encodeURIComponent(text)}`);
        const data = await res.json();
        removeLoader(loaderId);

        if (data.success) {
          appendBubble(data.response, 'bot-bubble', data.time_taken);
        } else {
          appendBubble(data.error || 'Something went wrong!', 'bot-bubble');
        }
      } catch (err) {
        removeLoader(loaderId);
        appendBubble('Server error! Please try again.', 'bot-bubble');
      }
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function appendBubble(text, className, timeTaken = null) {
      const bubble = document.createElement('div');
      bubble.className = `bubble ${className}`;
      bubble.innerText = text;
      if (timeTaken) {
        const meta = document.createElement('span');
        meta.className = 'meta';
        meta.innerText = `⚡ ${timeTaken}`;
        bubble.appendChild(meta);
      }
      chatContainer.appendChild(bubble);
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function appendLoader() {
      const id = 'loader-' + Date.now();
      const bubble = document.createElement('div');
      bubble.id = id;
      bubble.className = 'bubble bot-bubble loading-dots';
      bubble.innerHTML = '<span></span><span></span><span></span>';
      chatContainer.appendChild(bubble);
      return id;
    }

    function removeLoader(id) {
      const el = document.getElementById(id);
      if (el) el.remove();
    }

    function clearUI() {
      chatContainer.innerHTML = `
        <div class="bubble bot-bubble">
          Chat cleared. Boliye kya baat karni hai!
        </div>
      `;
    }
  </script>
</body>
</html>
"""

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/', methods=['GET'])
def home():
    if request.args.get('format') == 'json' or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({
            'name': 'KAL-X Chat API',
            'owner': 'Tomar Ji',
            'version': '2.0.0',
            'status': 'Online',
            'deployment': 'Vercel',
            'usage': {
                'chat': {'method': 'GET', 'url': '/chat?q=your question', 'example': '/chat?q=Hello'},
                'history': {'method': 'GET', 'url': '/history'},
                'stats': {'method': 'GET', 'url': '/stats'},
                'clear': {'method': 'GET', 'url': '/clear'}
            }
        })
    return Response(HTML_UI, mimetype='text/html')

@app.route('/chat', methods=['GET'])
def chat():
    question = request.args.get('q', '').strip()
    if not question:
        return jsonify({
            'success': False,
            'error': 'Question is required! Use ?q=your question',
            'owner': 'Tomar Ji'
        }), 400
    
    ip = request.remote_addr
    if not check_rate_limit(ip, limit=100, window=60):
        return jsonify({'success': False, 'error': 'Rate limit exceeded!', 'owner': 'Tomar Ji'}), 429
    
    # ── Inject Persona Prompt ──────────────────────────────────────────────
    system_prompt = (
        "[System Instruction: You are KAL-X AI, a super intelligent, witty, friendly, and cool AI persona. "
        "Your CREATOR, DEVELOPER, and OWNER is 'Tomar Ji'. "
        "Strict Rule: If someone asks who created you, who your developer is, or who your owner is, "
        "you must explicitly and proudly say that your owner and creator is 'Tomar Ji'. Never say Google created you. "
        "Talk naturally in conversational Hinglish or English matching the user. Be friendly, slightly humorous, and authentic like a close buddy.]\n\n"
        f"User Message: {question}"
    )

    result = chat_with_gemini(system_prompt)
    if result['success']:
        save_chat(question, result['response'], result['time_taken'])
        return jsonify({
            'success': True,
            'question': question,
            'response': result['response'],
            'time_taken': f"{result['time_taken']} seconds",
            'owner': 'Tomar Ji',
            'timestamp': datetime.now().isoformat()
        })
    return jsonify({'success': False, 'error': result.get('error', 'Error!'), 'owner': 'Tomar Ji'}), 500

@app.route('/history', methods=['GET'])
def history():
    limit = request.args.get('limit', 100, type=int)
    return jsonify({'success': True, 'history': get_chat_history(limit), 'owner': 'Tomar Ji'})

@app.route('/clear', methods=['GET'])
def clear():
    if clear_chat_history():
        return jsonify({'success': True, 'message': 'Chat history cleared!', 'owner': 'Tomar Ji'})
    return jsonify({'success': False, 'error': 'Failed to clear history!', 'owner': 'Tomar Ji'}), 500

@app.route('/stats', methods=['GET'])
def stats():
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as total FROM chats")
            total = c.fetchone()
            c.execute("SELECT AVG(time_taken) as avg_time FROM chats")
            avg_time = c.fetchone()
            conn.close()
            return jsonify({
                'success': True,
                'stats': {
                    'total_chats': total['total'] if total else 0,
                    'average_response_time': f"{avg_time['avg_time']:.3f}s" if avg_time and avg_time['avg_time'] else '0s'
                },
                'owner': 'Tomar Ji'
            })
        return jsonify({'success': False, 'error': 'DB unavailable', 'owner': 'Tomar Ji'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'owner': 'Tomar Ji'}), 500

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'success': True, 'message': 'Pong!', 'owner': 'Tomar Ji'})

if __name__ == '__main__':
    init_database()
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
