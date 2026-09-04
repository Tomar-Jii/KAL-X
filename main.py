# ============================================
# 🚀 KAL-X - FAST CHAT API FOR VERCEL 🚀
# Developer: Tomar Ji
# Ready for Vercel Deployment
# ============================================

from flask import Flask, request, jsonify
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

# Rate limiting
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
# GEMINI API - OPTIMIZED
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
        
        cookies = {}
        for cookie in session.cookies:
            cookies[cookie.name] = cookie.value
        
        snlm0e = extract_snlm0e_token(html)
        if not snlm0e:
            snlm0e = extract_from_script_tags(html)
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
        None,
        None,
        1,
        0,
        None,
        None,
        None,
        None,
        None,
        [[0]],
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        1,
        None,
        None,
        [4],
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        [2],
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0,
        None,
        None,
        None,
        None,
        None,
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
        return {
            'success': False,
            'error': 'Failed to connect! Try again!',
            'time_taken': 0
        }
    
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
            return {
                'success': False,
                'error': f'Error {response.status_code}!',
                'time_taken': round(time.time() - start_time, 3)
            }
        
        result = parse_streaming_response(response.text)
        time_taken = round(time.time() - start_time, 3)
        
        if result:
            return {
                'success': True,
                'response': result,
                'time_taken': time_taken
            }
        else:
            return {
                'success': False,
                'error': 'No response! Try again!',
                'time_taken': time_taken
            }
            
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {
            'success': False,
            'error': str(e),
            'time_taken': round(time.time() - start_time, 3)
        }

# ============================================
# SAVE CHAT HISTORY (Vercel Compatible)
# ============================================

def save_chat(question, response, time_taken):
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO chats (question, response, time_taken, timestamp) VALUES (?, ?, ?, ?)",
                (question, response, time_taken, datetime.now())
            )
            conn.commit()
            conn.close()
            return True
        return False
    except Exception as e:
        logger.error(f"Save error: {e}")
        return False

def get_chat_history(limit=100):
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, question, response, time_taken, timestamp FROM chats ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            history = []
            for row in c.fetchall():
                history.append({
                    'id': row['id'],
                    'question': row['question'],
                    'response': row['response'],
                    'time_taken': row['time_taken'],
                    'timestamp': row['timestamp']
                })
            conn.close()
            return history
        return []
    except Exception as e:
        logger.error(f"History error: {e}")
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
    except Exception as e:
        logger.error(f"Clear error: {e}")
        return False

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/', methods=['GET'])
def home():
    """API Information"""
    return jsonify({
        'name': 'KAL-X Chat API',
        'owner': 'Tomar Ji',
        'version': '2.0.0',
        'status': 'Online',
        'deployment': 'Vercel',
        'usage': {
            'chat': {
                'method': 'GET',
                'url': '/chat?q=your question',
                'example': '/chat?q=Hello how are you?'
            },
            'history': {
                'method': 'GET',
                'url': '/history',
                'example': '/history'
            },
            'stats': {
                'method': 'GET',
                'url': '/stats',
                'example': '/stats'
            },
            'clear': {
                'method': 'GET',
                'url': '/clear',
                'example': '/clear'
            }
        }
    })

@app.route('/chat', methods=['GET'])
def chat():
    question = request.args.get('q', '').strip()
    
    if not question:
        return jsonify({
            'success': False,
            'error': 'Question is required! Use ?q=your question',
            'owner': 'Tomar Ji',
            'usage': '/chat?q=Hello how are you?'
        }), 400
    
    ip = request.remote_addr
    if not check_rate_limit(ip, limit=100, window=60):
        return jsonify({
            'success': False,
            'error': 'Rate limit exceeded! Wait a moment!',
            'owner': 'Tomar Ji'
        }), 429
    
    result = chat_with_gemini(question)
    
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
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', 'Something went wrong!'),
            'time_taken': f"{result.get('time_taken', 0)} seconds",
            'owner': 'Tomar Ji'
        }), 500

@app.route('/history', methods=['GET'])
def history():
    limit = request.args.get('limit', 100, type=int)
    history = get_chat_history(limit)
    
    return jsonify({
        'success': True,
        'count': len(history),
        'history': history,
        'owner': 'Tomar Ji'
    })

@app.route('/clear', methods=['GET'])
def clear():
    if clear_chat_history():
        return jsonify({
            'success': True,
            'message': 'Chat history cleared!',
            'owner': 'Tomar Ji'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to clear history!',
            'owner': 'Tomar Ji'
        }), 500

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
            
            c.execute("SELECT MIN(time_taken) as fastest FROM chats")
            fastest = c.fetchone()
            
            c.execute("SELECT MAX(time_taken) as slowest FROM chats")
            slowest = c.fetchone()
            conn.close()
            
            return jsonify({
                'success': True,
                'stats': {
                    'total_chats': total['total'] if total else 0,
                    'average_response_time': f"{avg_time['avg_time']:.3f} seconds" if avg_time and avg_time['avg_time'] else '0 seconds',
                    'fastest_response': f"{fastest['fastest']:.3f} seconds" if fastest and fastest['fastest'] else '0 seconds',
                    'slowest_response': f"{slowest['slowest']:.3f} seconds" if slowest and slowest['slowest'] else '0 seconds'
                },
                'owner': 'Tomar Ji'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Database not available',
                'owner': 'Tomar Ji'
            }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'owner': 'Tomar Ji'
        }), 500

@app.route('/clear-all', methods=['GET'])
def clear_all():
    try:
        conn = get_db()
        if conn:
            c = conn.cursor()
            c.execute("DROP TABLE IF EXISTS chats")
            conn.commit()
            conn.close()
            init_database()
            return jsonify({
                'success': True,
                'message': 'All data cleared! Database reset!',
                'owner': 'Tomar Ji'
            })
        return jsonify({
            'success': False,
            'error': 'Database not available',
            'owner': 'Tomar Ji'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'owner': 'Tomar Ji'
        }), 500

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({
        'success': True,
        'message': 'Pong!',
        'owner': 'Tomar Ji',
        'timestamp': datetime.now().isoformat()
    })

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found! Use /chat?q=your question',
        'owner': 'Tomar Ji',
        'available_endpoints': [
            '/',
            '/chat?q=question',
            '/history',
            '/stats',
            '/clear',
            '/ping'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error! Try again!',
        'owner': 'Tomar Ji'
    }), 500

@app.errorhandler(429)
def ratelimit_error(error):
    return jsonify({
        'success': False,
        'error': 'Too many requests! Slow down!',
        'owner': 'Tomar Ji'
    }), 429

# ============================================
# MAIN - For Local Testing
# ============================================

if __name__ == '__main__':
    init_database()
    app.run(
        debug=False,
        host='0.0.0.0',
        port=5000,
        threaded=True
    )
