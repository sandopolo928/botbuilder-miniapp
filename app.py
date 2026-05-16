import os, json, hashlib, hmac, time, uuid, re, base64 as b64mod
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, request, jsonify, send_from_directory
import psycopg2, psycopg2.extras
import requests as req
import yaml as pyyaml

app = Flask(__name__, static_folder='static')
VERSION = '3.0.0'
BOTBUILDER_TOKEN = os.environ.get('BOTBUILDER_TOKEN', '')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
RAILWAY_URL = os.environ.get('RAILWAY_URL', '')

SUPPORTED_ON_INPUT = {
    'call_ai', 'call_openai', 'call_anthropic',
    'call_ai_vision', 'call_openai_vision', 'call_anthropic_vision',
    'reply', 'show_menu', 'next_flow', 'inline_buttons',
    'vision_prompt', 'loading_text'
}

TEMPLATES = [
    {
        'id': 'ai_chat', 'name': 'AI Chat Assistant', 'emoji': chr(0x1f916),
        'description': 'General AI assistant that answers any questions',
        'requires': 'ai_key',
        'yaml': """bot:
  name: AI Assistant
  platform: telegram
  welcome: "\U0001f44b Hello! I am your AI assistant. Ask me anything!"
  default_reply: Type a question or use the menu.
  menu:
    - text: "\U0001f4ac Ask AI"
      flow: ask_ai
    - text: "\U0001f504 New Topic"
      flow: new_topic
    - text: "\u2753 Help"
      flow: help
  flows:
    ask_ai:
      ask: What would you like to know?
      on_input:
        call_ai:
          system: You are a helpful and friendly AI assistant. Give clear, concise answers.
          prompt: "{{input}}"
        reply: "{{ai_result}}"
        show_menu: true
    new_topic:
      reply: "\U0001f504 Ready for a new topic! What would you like to know?"
      show_menu: true
    help:
      reply: "\U0001f4a1 Just type any question and I will answer using AI!"
      show_menu: true"""
    },
    {
        'id': 'translator', 'name': 'Translator Bot', 'emoji': chr(0x1f30f),
        'description': 'Translate text and photos from any language to Russian',
        'requires': 'ai_key',
        'yaml': """bot:
  name: Translator
  platform: telegram
  welcome: "\U0001f30f Welcome! I can translate text and photos to Russian."
  default_reply: Use the menu to start translating.
  menu:
    - text: "\u270d\ufe0f Translate Text"
      flow: translate_text
    - text: "\U0001f4f7 Translate Photo"
      flow: translate_photo
    - text: "\u2753 Help"
      flow: help
  flows:
    translate_text:
      ask: "\u270d\ufe0f Send text to translate:"
      on_input:
        call_ai:
          system: You are a professional translator. Translate the given text to Russian. Return ONLY the translation, no explanations.
          prompt: "{{input}}"
        reply: "\U0001f1f7\U0001f1fa Translation:\n{{ai_result}}"
        show_menu: true
    translate_photo:
      ask: "\U0001f4f7 Send a photo with text to translate:"
      on_input:
        call_ai_vision:
          prompt: Extract ALL text from this image. Then translate it to Russian. Format your answer as: ORIGINAL TEXT:\n[original]\n\nRUSSIAN TRANSLATION:\n[translation]
        reply: "{{ai_result}}"
        show_menu: true
    help:
      reply: "\U0001f4a1 Use menu buttons to translate text or photos. Supports any language!"
      show_menu: true"""
    },
    {
        'id': 'faq', 'name': 'FAQ / Info Bot', 'emoji': chr(0x1f4cb),
        'description': 'Information bot with FAQ, contacts and working hours. No API needed.',
        'requires': 'none',
        'yaml': """bot:
  name: FAQ Bot
  platform: telegram
  welcome: "\U0001f44b Welcome! How can I help you?"
  default_reply: Please use the menu to find information.
  menu:
    - text: "\u2139\ufe0f About Us"
      flow: about
    - text: "\U0001f4bc Services"
      flow: services
    - text: "\u23f0 Working Hours"
      flow: hours
    - text: "\U0001f4de Contacts"
      flow: contacts
  flows:
    about:
      reply: "\u2139\ufe0f We are a company that provides quality services.\n\nEdit this text in the Mini App after creating the bot."
      show_menu: true
    services:
      reply: "\U0001f4bc Our services:\n\n\u2022 Service 1\n\u2022 Service 2\n\u2022 Service 3\n\nContact us for details!"
      show_menu: true
    hours:
      reply: "\u23f0 Working hours:\nMon-Fri: 9:00 - 18:00\nSat: 10:00 - 15:00\nSun: Closed"
      show_menu: true
    contacts:
      reply: "\U0001f4de Contact us:\n\U0001f4f1 Phone: +7 (xxx) xxx-xx-xx\n\U0001f4e7 Email: info@example.com\n\U0001f4cd Address: Your address here"
      show_menu: true"""
    },
    {
        'id': 'support', 'name': 'Customer Support', 'emoji': chr(0x1f91d),
        'description': 'Collect feedback, questions and support requests. No API needed.',
        'requires': 'none',
        'yaml': """bot:
  name: Support Bot
  platform: telegram
  welcome: "\U0001f91d Hello! We are here to help. Choose an option:"
  default_reply: Please use the menu below.
  menu:
    - text: "\u2b50 Leave Feedback"
      flow: feedback
    - text: "\u2753 Ask a Question"
      flow: ask_question
    - text: "\U0001f6a8 Report a Problem"
      flow: report
    - text: "\U0001f4de Contacts"
      flow: contacts
  flows:
    feedback:
      ask: "\u2b50 Please share your feedback:"
      on_input:
        reply: "\u2705 Thank you for your feedback! We appreciate it and will review your message."
        show_menu: true
    ask_question:
      ask: "\u2753 What is your question?"
      on_input:
        reply: "\U0001f4e8 Your question has been received! We will respond within 24 hours."
        show_menu: true
    report:
      ask: "\U0001f6a8 Please describe the problem:"
      on_input:
        reply: "\u2705 Problem reported! Our team will look into it as soon as possible."
        show_menu: true
    contacts:
      reply: "\U0001f4de Reach us directly:\n@your_username\ninfo@example.com"
      show_menu: true"""
    },
    {
        'id': 'vision', 'name': 'Photo Analyzer', 'emoji': chr(0x1f4f8),
        'description': 'Analyze photos, extract text, identify objects using AI vision.',
        'requires': 'ai_key',
        'yaml': """bot:
  name: Photo Analyzer
  platform: telegram
  welcome: "\U0001f4f8 Send me a photo and I will analyze it!"
  default_reply: Send a photo or choose what to do with it from the menu.
  photo_flow: auto_analyze
  menu:
    - text: "\U0001f50d Analyze Photo"
      flow: analyze_prompt
    - text: "\U0001f4dd Extract Text"
      flow: extract_text
    - text: "\U0001f50e Identify Object"
      flow: identify
  flows:
    auto_analyze:
      handle_photo: true
      call_ai_vision:
        prompt: Describe this image in detail. What do you see? If there is any text, extract it.
      reply: "\U0001f50d Analysis:\n{{ai_result}}"
    analyze_prompt:
      ask: "\U0001f50d Send a photo to analyze:"
      on_input:
        call_ai_vision:
          prompt: Describe this image in detail. What objects, people, text or scenes do you see?
        reply: "\U0001f50d Result:\n{{ai_result}}"
        show_menu: true
    extract_text:
      ask: "\U0001f4dd Send a photo to extract text from:"
      on_input:
        call_ai_vision:
          prompt: Extract ALL text visible in this image. Return only the text, preserving its structure.
        reply: "\U0001f4dd Extracted text:\n{{ai_result}}"
        show_menu: true
    identify:
      ask: "\U0001f50e Send a photo to identify the object:"
      on_input:
        call_ai_vision:
          prompt: What is the main object or subject in this photo? Identify it precisely with details.
        reply: "\U0001f50e Identified:\n{{ai_result}}"
        show_menu: true"""
    },
    {
        'id': 'catalog', 'name': 'Product Catalog', 'emoji': chr(0x1f6cd),
        'description': 'Present products/services, prices and ordering info. No API needed.',
        'requires': 'none',
        'yaml': """bot:
  name: Shop Bot
  platform: telegram
  welcome: "\U0001f6cd Welcome to our shop! Browse our catalog:"
  default_reply: Use the menu to explore our catalog.
  menu:
    - text: "\U0001f4e6 Products"
      flow: products
    - text: "\U0001f4b0 Pricing"
      flow: pricing
    - text: "\U0001f69a Delivery"
      flow: delivery
    - text: "\U0001f6d2 How to Order"
      flow: order
    - text: "\U0001f4de Contacts"
      flow: contacts
  flows:
    products:
      reply: "\U0001f4e6 Our products:\n\n1. Product Name - Description\n2. Product Name - Description\n3. Product Name - Description\n\nEdit this list after creating the bot."
      show_menu: true
    pricing:
      reply: "\U0001f4b0 Prices:\n\n\u2022 Basic: $X\n\u2022 Standard: $Y\n\u2022 Premium: $Z\n\nAll prices include VAT."
      show_menu: true
    delivery:
      reply: "\U0001f69a Delivery info:\n\u2022 Standard: 3-5 days\n\u2022 Express: 1-2 days\n\u2022 Free shipping on orders over $50"
      show_menu: true
    order:
      ask: "\U0001f6d2 Tell us what you want to order:"
      on_input:
        reply: "\u2705 Order received! We will contact you within 1 hour to confirm."
        show_menu: true
    contacts:
      reply: "\U0001f4de Contact us:\n\U0001f4f1 +7 (xxx) xxx-xx-xx\n\U0001f4e7 shop@example.com"
      show_menu: true"""
    }
]


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY, username TEXT DEFAULT '',
                first_name TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY, user_id BIGINT REFERENCES users(telegram_id),
                name TEXT NOT NULL, description TEXT DEFAULT '',
                yaml_definition TEXT DEFAULT '', bot_token TEXT, bot_token_hash TEXT UNIQUE,
                bot_username TEXT DEFAULT '', ai_api_key TEXT DEFAULT '',
                ai_provider TEXT DEFAULT 'anthropic', status TEXT DEFAULT 'inactive',
                created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())""")
            for col, defn in [
                ('bot_username', "TEXT DEFAULT ''"),
                ('ai_api_key', "TEXT DEFAULT ''"),
                ('ai_provider', "TEXT DEFAULT 'anthropic'")
            ]:
                try:
                    cur.execute(f'ALTER TABLE bots ADD COLUMN IF NOT EXISTS {col} {defn}')
                except Exception:
                    pass
            cur.execute("""CREATE TABLE IF NOT EXISTS bot_states (
                bot_id TEXT, chat_id TEXT, state_key TEXT, state_value TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (bot_id, chat_id, state_key))""")
        conn.commit()
        print(f'[OK] DB v{VERSION} ready')
    except Exception as e:
        print(f'[DB] {e}'); conn.rollback()
    finally:
        conn.close()


def _sanitize_yaml(yaml_str):
    """Remove unsupported DSL directives. Returns (clean_yaml, warnings)."""
    UNSUPPORTED = {'call_api', 'db_insert', 'db_query', 'db_update',
                   'user_var_set', 'store_as', 'send_photo', 'reply_after',
                   'if_empty_reply', 'schedule', 'conditions'}
    warnings = []
    try:
        cfg = pyyaml.safe_load(yaml_str)
        if not cfg:
            return yaml_str, ['Empty YAML']
        bc = cfg.get('bot', cfg)
        flows = bc.get('flows', {})
        for fkey, flow in flows.items():
            if not isinstance(flow, dict):
                continue
            oi = flow.get('on_input', {})
            if isinstance(oi, dict):
                removed = [k for k in list(oi.keys()) if k in UNSUPPORTED]
                for k in removed:
                    del oi[k]
                if removed:
                    warnings.append(f"Flow '{fkey}': removed unsupported: {', '.join(removed)}")
                for field in ['reply']:
                    v = str(oi.get(field, ''))
                    v2 = re.sub(r'\{\{user_var:\w+\}\}', '[value]', v)
                    v2 = re.sub(r'\{\{recall:[\w.]+\}\}', '[data]', v2)
                    if v2 != v:
                        oi[field] = v2
                        warnings.append(f"Flow '{fkey}': replaced unsupported vars")
                if oi is not None and len(oi) == 0:
                    flow['on_input'] = {'reply': chr(0x2705) + ' Got it!', 'show_menu': True}
                    warnings.append(f"Flow '{fkey}': added fallback reply (on_input was empty)")
            for field in ['reply']:
                v = str(flow.get(field, ''))
                v2 = re.sub(r'\{\{user_var:\w+\}\}', '[value]', v)
                v2 = re.sub(r'\{\{recall:[\w.]+\}\}', '[data]', v2)
                if v2 != v:
                    flow[field] = v2
        clean = pyyaml.dump(cfg, allow_unicode=True, default_flow_style=False, indent=2)
        return clean, warnings
    except Exception as e:
        return yaml_str, [f'Sanitize failed: {e}']


def validate_init_data(init_data):
    if not init_data or not BOTBUILDER_TOKEN:
        return None
    try:
        parsed = {}
        for part in init_data.split('&'):
            if '=' in part:
                k, v = part.split('=', 1)
                parsed[k] = unquote(v)
        hash_val = parsed.pop('hash', '')
        data_check = '\n'.join(f'{k}={v}' for k, v in sorted(parsed.items()))
        secret = hmac.new(b'WebAppData', BOTBUILDER_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if computed != hash_val or time.time() - int(parsed.get('auth_date', 0)) > 86400:
            return None
        return json.loads(parsed.get('user', '{}'))
    except Exception:
        return None


@app.route('/')
@app.route('/app')
def serve_app():
    return send_from_directory('static', 'index.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': VERSION})


@app.route('/api/templates', methods=['GET'])
def get_templates():
    return jsonify({'ok': True, 'templates': [
        {k: v for k, v in t.items() if k != 'yaml'} for t in TEMPLATES
    ]})


@app.route('/api/template/<tmpl_id>', methods=['GET'])
def get_template(tmpl_id):
    for t in TEMPLATES:
        if t['id'] == tmpl_id:
            return jsonify({'ok': True, 'template': t})
    return jsonify({'error': 'Template not found'}), 404


@app.route('/api/validate_yaml', methods=['POST'])
def validate_yaml_ep():
    data = request.json or {}
    yaml_str = data.get('yaml', '')
    clean, warnings = _sanitize_yaml(yaml_str)
    return jsonify({'ok': True, 'yaml': clean, 'warnings': warnings})


@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json or {}
    user_data = validate_init_data(data.get('initData', ''))
    if not user_data:
        if os.environ.get('DEV_MODE') == '1':
            user_data = {'id': 12345, 'first_name': 'Dev', 'username': 'dev'}
        else:
            return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO users (telegram_id, username, first_name)
                VALUES (%s,%s,%s) ON CONFLICT (telegram_id) DO UPDATE
                SET username=EXCLUDED.username, first_name=EXCLUDED.first_name
                RETURNING telegram_id, username, first_name""",
                (user_data['id'], user_data.get('username', ''), user_data.get('first_name', '')))
            user = dict(cur.fetchone())
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'user': user})


@app.route('/api/bots', methods=['GET'])
def list_bots():
    uid = request.args.get('user_id')
    if not uid:
        return jsonify({'error': 'user_id required'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, user_id, name, description, status, bot_username,
                ai_provider, (ai_api_key != '' AND ai_api_key IS NOT NULL) as has_ai_key,
                created_at FROM bots WHERE user_id=%s ORDER BY created_at DESC""", (uid,))
            bots = [{**dict(r), 'created_at': str(r['created_at'])} for r in cur.fetchall()]
    finally:
        conn.close()
    return jsonify({'bots': bots})


@app.route('/api/bots', methods=['POST'])
def create_bot():
    data = request.json or {}
    uid = data.get('user_id'); bt = data.get('bot_token', '')
    if not uid or not bt:
        return jsonify({'error': 'user_id and bot_token required'}), 400
    try:
        r = req.get(f'https://api.telegram.org/bot{bt}/getMe', timeout=10)
        if not r.ok or not r.json().get('ok'):
            return jsonify({'error': 'Invalid bot token'}), 400
        info = r.json()['result']
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    name = data.get('name') or info.get('first_name', 'My Bot')
    yaml_def = data.get('yaml_definition', '')
    if yaml_def:
        yaml_def, _ = _sanitize_yaml(yaml_def)
    th = hashlib.sha256(bt.encode()).hexdigest()[:32]
    bid = str(uuid.uuid4())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO bots
                (id,user_id,name,description,yaml_definition,bot_token,bot_token_hash,
                 bot_username,ai_api_key,ai_provider,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'inactive')
                RETURNING id,user_id,name,description,status,bot_username,created_at""",
                (bid, uid, name, data.get('description', ''), yaml_def, bt, th,
                 info.get('username', ''), data.get('ai_api_key', ''),
                 data.get('ai_provider', 'anthropic')))
            bot = dict(cur.fetchone())
            bot['created_at'] = str(bot.get('created_at', ''))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500
    finally:
        try: conn.close()
        except: pass
    return jsonify({'ok': True, 'bot': bot, 'bot_id': bid})


@app.route('/api/bots/<bot_id>/ai_key', methods=['PUT'])
def update_ai_key(bot_id):
    data = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE bots SET ai_api_key=%s, ai_provider=%s, updated_at=NOW() WHERE id=%s',
                (data.get('ai_api_key', ''), data.get('ai_provider', 'anthropic'), bot_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


@app.route('/api/bots/<bot_id>/yaml', methods=['PUT'])
def update_yaml(bot_id):
    data = request.json or {}
    yaml_def = data.get('yaml_definition', '')
    if yaml_def:
        yaml_def, warnings = _sanitize_yaml(yaml_def)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE bots SET yaml_definition=%s, updated_at=NOW() WHERE id=%s',
                (yaml_def, bot_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'warnings': warnings if yaml_def else []})


@app.route('/api/bots/<bot_id>/activate', methods=['POST'])
def activate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({'error': 'Bot not found'}), 404
    bot = dict(bot)
    if not RAILWAY_URL:
        return jsonify({'error': 'RAILWAY_URL not set'}), 500
    wh = f'{RAILWAY_URL}/bot/{bot["bot_token_hash"]}'
    r = req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/setWebhook',
        json={'url': wh, 'drop_pending_updates': True}, timeout=10)
    if r.ok and r.json().get('ok'):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE bots SET status='active', updated_at=NOW() WHERE id=%s", (bot_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'ok': True, 'webhook_url': wh})
    return jsonify({'error': 'Webhook failed', 'detail': r.json()}), 500


@app.route('/api/bots/<bot_id>/deactivate', methods=['POST'])
def deactivate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT bot_token FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({'error': 'Bot not found'}), 404
    try:
        req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/deleteWebhook',
            json={'drop_pending_updates': True}, timeout=10)
    except Exception:
        pass
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE bots SET status='inactive', updated_at=NOW() WHERE id=%s", (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


@app.route('/api/bots/<bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT bot_token FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
            if bot and bot['bot_token']:
                try:
                    req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/deleteWebhook',
                        timeout=5)
                except Exception:
                    pass
            cur.execute('DELETE FROM bot_states WHERE bot_id=%s', (bot_id,))
            cur.execute('DELETE FROM bots WHERE id=%s', (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


@app.route('/api/generate', methods=['POST'])
def generate_yaml():
    data = request.json or {}
    desc = (data.get('description') or '').strip()
    api_key = (data.get('api_key') or '').strip()
    provider = data.get('ai_provider', 'anthropic')
    bot_name = (data.get('bot_name') or 'My Bot').strip()
    tmpl_base = (data.get('template_yaml') or '').strip()
    if not desc:
        return jsonify({'error': 'description required'}), 400
    has_ai = bool(data.get('ai_api_key') or api_key)
    if not api_key:
        tmpl = _make_simple_template(bot_name, desc, has_ai)
        return jsonify({'ok': True, 'yaml': tmpl, 'source': 'template', 'warnings': []})
    if tmpl_base:
        prompt = (
            f'Adapt this Telegram bot YAML template based on this customization request: "{desc}"\n\n'
            f'BASE TEMPLATE:\n{tmpl_base}\n\n'
            'RULES: Keep same structure. Only use supported directives: ask, reply, show_menu, '
            'next_flow, call_ai (system+prompt), call_ai_vision (prompt). '
            'Max 5 flows. reply uses {{input}} or {{ai_result}}. '
            'Return ONLY valid YAML, no markdown, no explanation.'
        )
    else:
        prompt = (
            f'Create a Telegram bot YAML for: "{desc}"\n\n'
            'STRICT RULES:\n'
            '- Maximum 4 content flows + 1 help flow = 5 total\n'
            '- Menu buttons must match flows exactly\n'
            '- ONLY use these directives: ask, reply, show_menu, next_flow, call_ai, call_ai_vision\n'
            '- call_ai format: {system: "...", prompt: "{{input}}"}\n'
            '- call_ai_vision format: {prompt: "..."}\n'
            '- reply: "{{ai_result}}" shows AI response\n'
            '- reply: "{{input}}" echoes user text (no AI needed)\n'
            '- DO NOT USE: call_api, db_insert, db_query, schedule, user_var_set, conditions, store_as\n'
            '- For photo flows: ask + on_input.call_ai_vision\n\n'
            'EXACT FORMAT TO USE:\nbot:\n  name: "BotName"\n  platform: telegram\n'
            '  welcome: "Welcome message"\n  default_reply: "Use the menu."\n'
            '  menu:\n    - text: "Button"\n      flow: flow_name\n'
            '  flows:\n    flow_name:\n      ask: "Question:"\n      on_input:\n'
            '        call_ai:\n          system: "You are X."\n          prompt: "{{input}}"\n'
            '        reply: "{{ai_result}}"\n        show_menu: true\n\n'
            'Return ONLY valid YAML. No markdown. No explanation.'
        )
    try:
        if provider == 'openai':
            r = req.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': 'gpt-4o-mini', 'max_tokens': 2000,
                      'messages': [{'role': 'user', 'content': prompt}]}, timeout=30)
            content = r.json()['choices'][0]['message']['content'] if r.ok else None
        else:
            r = req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5', 'max_tokens': 2000,
                      'messages': [{'role': 'user', 'content': prompt}]}, timeout=30)
            content = r.json()['content'][0]['text'] if r.ok else None
        if not content:
            tmpl = _make_simple_template(bot_name, desc, has_ai)
            return jsonify({'ok': True, 'yaml': tmpl, 'source': 'template', 'warnings': ['AI generation failed, used template']})
        m = re.search(r'```(?:yaml)?\n(.*?)\n```', content, re.DOTALL)
        yaml_text = m.group(1) if m else content.strip()
        if yaml_text.startswith('```'):
            yaml_text = re.sub(r'^```\w*\n?', '', yaml_text).rstrip('`').strip()
        pyyaml.safe_load(yaml_text)
        clean, warnings = _sanitize_yaml(yaml_text)
        return jsonify({'ok': True, 'yaml': clean, 'source': 'ai', 'warnings': warnings})
    except Exception as e:
        tmpl = _make_simple_template(bot_name, desc, has_ai)
        return jsonify({'ok': True, 'yaml': tmpl, 'source': 'template',
                        'warnings': [f'AI error: {e}']})


def _make_simple_template(name, desc, has_ai=False):
    q = chr(34); n = str(name or 'Bot').replace(chr(34), chr(39))
    d = str(desc or '')[:80].replace(chr(34), chr(39))
    if has_ai:
        lines = [
            'bot:', f'  name: {q}{n}{q}', '  platform: telegram',
            f'  welcome: {q}' + chr(0x1f44b) + f' Hello! I am {n}.{q}',
            f'  default_reply: {q}Send a message or use the menu.{q}',
            '  menu:',
            f'    - text: {q}' + chr(0x1f4ac) + f' Chat{q}', '      flow: ai_chat',
            f'    - text: {q}' + chr(0x1f4f7) + f' Send Photo{q}', '      flow: photo',
            f'    - text: {q}' + chr(0x2753) + f' Help{q}', '      flow: help',
            '  flows:',
            '    ai_chat:',
            f'      ask: {q}What would you like to know?{q}',
            '      on_input:',
            '        call_ai:',
            f'          system: {q}You are a helpful assistant. Context: {d}{q}',
            f'          prompt: {q}' + '{{input}}' + f'{q}',
            f'        reply: {q}' + '{{ai_result}}' + f'{q}',
            '        show_menu: true',
            '    photo:',
            f'      ask: {q}Send a photo:{q}',
            '      on_input:',
            '        call_ai_vision:',
            f'          prompt: {q}Describe and analyze this image.{q}',
            f'        reply: {q}' + '{{ai_result}}' + f'{q}',
            '        show_menu: true',
            '    help:',
            f'      reply: {q}' + chr(0x1f4a1) + f' I am {n}. {d} Use the menu to get started.{q}',
            '      show_menu: true'
        ]
    else:
        lines = [
            'bot:', f'  name: {q}{n}{q}', '  platform: telegram',
            f'  welcome: {q}' + chr(0x1f44b) + f' Welcome! I am {n}.{q}',
            f'  default_reply: {q}Please use the menu below.{q}',
            '  menu:',
            f'    - text: {q}' + chr(0x2139) + chr(0xfe0f) + f' About{q}', '      flow: about',
            f'    - text: {q}' + chr(0x1f4de) + f' Contact{q}', '      flow: contact',
            f'    - text: {q}' + chr(0x2753) + f' Help{q}', '      flow: help',
            '  flows:',
            '    about:',
            f'      reply: {q}' + chr(0x2139) + chr(0xfe0f) + f' {d}{q}',
            '      show_menu: true',
            '    contact:',
            f'      ask: {q}' + chr(0x1f4de) + f' Send your message:{q}',
            '      on_input:',
            f'        reply: {q}' + chr(0x2705) + ' Received: {{input}}' + f'{q}',
            '        show_menu: true',
            '    help:',
            f'      reply: {q}' + chr(0x2753) + f' Use menu buttons to navigate. I am {n}.{q}',
            '      show_menu: true'
        ]
    return chr(10).join(lines)


def _tg_send(token, chat_id, text, markup=None):
    d = {'chat_id': chat_id, 'text': str(text) or '.', 'parse_mode': 'HTML'}
    if markup:
        d['reply_markup'] = markup
    try:
        req.post(f'https://api.telegram.org/bot{token}/sendMessage', json=d, timeout=10)
    except Exception:
        pass


def _build_keyboard(menu):
    if not menu:
        return None
    rows, row = [], []
    for item in menu:
        row.append({'text': item.get('text', '')})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return {'keyboard': rows, 'resize_keyboard': True}


def _send_with_menu(token, chat_id, text, menu):
    kb = _build_keyboard(menu)
    d = {'chat_id': chat_id, 'text': str(text) or '.', 'parse_mode': 'HTML'}
    if kb:
        d['reply_markup'] = kb
    try:
        req.post(f'https://api.telegram.org/bot{token}/sendMessage', json=d, timeout=10)
    except Exception:
        pass


def _get_state(bot_id, chat_id, key):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT state_value FROM bot_states WHERE bot_id=%s AND chat_id=%s AND state_key=%s',
                (bot_id, str(chat_id), key))
            row = cur.fetchone()
            return row['state_value'] if row else ''
    except Exception:
        return ''
    finally:
        conn.close()


def _set_state(bot_id, chat_id, key, value):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO bot_states (bot_id,chat_id,state_key,state_value)
                VALUES (%s,%s,%s,%s) ON CONFLICT (bot_id,chat_id,state_key)
                DO UPDATE SET state_value=EXCLUDED.state_value, updated_at=NOW()""",
                (bot_id, str(chat_id), key, value))
        conn.commit()
    except Exception as e:
        print(f'[state] {e}')
    finally:
        conn.close()


def _get_photo_url(token, file_id):
    try:
        r = req.get(f'https://api.telegram.org/bot{token}/getFile',
            params={'file_id': file_id}, timeout=10)
        if r.ok:
            return f'https://api.telegram.org/file/bot{token}/{r.json()["result"]["file_path"]}'
    except Exception:
        pass
    return None


def _ai_text(api_key, provider, system, user_msg):
    if not api_key:
        return chr(0x26a0) + ' AI key not configured. Add it in bot settings via Mini App.'
    try:
        if provider == 'openai':
            r = req.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': 'gpt-4o-mini', 'max_tokens': 2000,
                      'messages': [{'role': 'system', 'content': system},
                                   {'role': 'user', 'content': user_msg}]}, timeout=60)
            return r.json()['choices'][0]['message']['content'] if r.ok else f'AI error {r.status_code}'
        else:
            r = req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5', 'max_tokens': 2000,
                      'system': system, 'messages': [{'role': 'user', 'content': user_msg}]},
                timeout=60)
            return r.json()['content'][0]['text'] if r.ok else f'AI error {r.status_code}'
    except Exception as e:
        return f'AI error: {e}'


def _ai_vision(api_key, provider, prompt, img_url):
    if not api_key:
        return chr(0x26a0) + ' AI key not configured. Add it in bot settings via Mini App.'
    if not img_url:
        return chr(0x26a0) + ' Could not download image from Telegram.'
    try:
        if provider == 'openai':
            r = req.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': 'gpt-4o-mini', 'max_tokens': 2000,
                      'messages': [{'role': 'user', 'content': [
                          {'type': 'text', 'text': prompt},
                          {'type': 'image_url', 'image_url': {'url': img_url, 'detail': 'high'}}
                      ]}]}, timeout=90)
            return r.json()['choices'][0]['message']['content'] if r.ok else f'Vision error {r.status_code}'
        else:
            img_r = req.get(img_url, timeout=30)
            if not img_r.ok:
                return 'Could not download image.'
            img_b64 = b64mod.b64encode(img_r.content).decode()
            mt = img_r.headers.get('content-type', 'image/jpeg').split(';')[0]
            r = req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'claude-haiku-4-5', 'max_tokens': 2000,
                      'messages': [{'role': 'user', 'content': [
                          {'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': img_b64}},
                          {'type': 'text', 'text': prompt}
                      ]}]}, timeout=90)
            return r.json()['content'][0]['text'] if r.ok else f'Vision error {r.status_code}'
    except Exception as e:
        return f'Vision error: {e}'


def _sub_vars(text, user_input=None, ai_result=None):
    """Substitute template variables in text."""
    t = str(text)
    now = datetime.now()
    t = t.replace('{{today}}', now.strftime('%d.%m.%Y'))
    t = t.replace('{{date}}', now.strftime('%d.%m.%Y'))
    t = t.replace('{{month}}', now.strftime('%B'))
    t = t.replace('{{year}}', str(now.year))
    t = t.replace('{{time}}', now.strftime('%H:%M'))
    if user_input is not None:
        t = t.replace('{{input}}', str(user_input))
    if ai_result is not None:
        t = t.replace('{{ai_result}}', str(ai_result))
        t = t.replace('{{result}}', str(ai_result))
    return t


def _exec_on_input(token, on_input, chat_id, ai_key, ai_prov, user_text=None, photo_fid=None):
    """Execute on_input directives. Returns (reply_text, show_menu, next_flow)."""
    ai_result = None
    has_ai_call = any(k in on_input for k in [
        'call_ai', 'call_openai', 'call_anthropic',
        'call_ai_vision', 'call_openai_vision', 'call_anthropic_vision'
    ])
    loading = on_input.get('loading_text', '')
    if has_ai_call and ai_key and loading:
        _tg_send(token, chat_id, loading)
    elif has_ai_call and ai_key:
        _tg_send(token, chat_id, chr(0x23f3) + ' Processing...')
    if user_text is not None:
        for call_key, prov in [('call_ai', ai_prov), ('call_openai', 'openai'), ('call_anthropic', 'anthropic')]:
            if call_key in on_input:
                c = on_input[call_key] if isinstance(on_input[call_key], dict) else {}
                sys_p = c.get('system', 'You are a helpful assistant.')
                usr_p = _sub_vars(c.get('prompt', '{{input}}'), user_input=user_text)
                ai_result = _ai_text(ai_key, prov, sys_p, usr_p)
                break
        if ai_result is None and ai_key and '{{ai_result}}' in str(on_input.get('reply', '')):
            ai_result = _ai_text(ai_key, ai_prov, 'You are a helpful assistant.', user_text)
    if photo_fid is not None:
        img_url = _get_photo_url(token, photo_fid)
        found_vision = False
        for vkey, prov in [('call_ai_vision', ai_prov), ('call_openai_vision', 'openai'), ('call_anthropic_vision', 'anthropic')]:
            if vkey in on_input:
                c = on_input[vkey] if isinstance(on_input[vkey], dict) else {}
                prompt = c.get('prompt', 'Describe this image.')
                ai_result = _ai_vision(ai_key, prov, prompt, img_url)
                found_vision = True; break
        if not found_vision and ai_key and img_url:
            vp = on_input.get('vision_prompt', 'Describe this image and extract any text.')
            ai_result = _ai_vision(ai_key, ai_prov, vp, img_url)
        elif not found_vision and not ai_key:
            ai_result = chr(0x26a0) + ' This bot needs an AI key for photo analysis. Add it in bot settings.'
    tpl = str(on_input.get('reply', ''))
    if tpl:
        if ai_result and '{{ai_result}}' not in tpl and '{{result}}' not in tpl:
            tpl = tpl + '\n' + str(ai_result)
        reply = _sub_vars(tpl, user_input=user_text, ai_result=ai_result)
        return reply, bool(on_input.get('show_menu')), str(on_input.get('next_flow', ''))
    if ai_result:
        return str(ai_result), bool(on_input.get('show_menu')), str(on_input.get('next_flow', ''))
    return None, False, ''


def _run_flow(bot, token, chat_id, flows, flow_key, menu, ai_key, ai_prov, user_text=None, photo_fid=None):
    flow = flows.get(flow_key)
    if not flow or not isinstance(flow, dict):
        return
    bot_id = bot['id']
    if photo_fid is not None and flow.get('handle_photo'):
        img_url = _get_photo_url(token, photo_fid)
        if ai_key and img_url:
            _tg_send(token, chat_id, chr(0x23f3) + ' Analyzing image...')
            c = flow.get('call_ai_vision', {})
            prompt = c.get('prompt', 'Describe this image.') if isinstance(c, dict) else 'Describe this image.'
            ai_result = _ai_vision(ai_key, ai_prov, prompt, img_url)
        else:
            ai_result = chr(0x26a0) + ' AI key not configured. Add it in bot settings via Mini App.'
        reply_tpl = str(flow.get('reply', '{{ai_result}}'))
        reply = _sub_vars(reply_tpl, ai_result=ai_result)
        if flow.get('show_menu'):
            _send_with_menu(token, chat_id, reply, menu)
        else:
            _tg_send(token, chat_id, reply)
        nf = str(flow.get('next_flow', ''))
        if nf and nf in flows:
            _run_flow(bot, token, chat_id, flows, nf, menu, ai_key, ai_prov)
        return
    if 'ask' in flow and user_text is None and photo_fid is None:
        _tg_send(token, chat_id, flow['ask'])
        if 'on_input' in flow:
            _set_state(bot_id, str(chat_id), f'oi_{flow_key}', json.dumps(flow['on_input']))
        _set_state(bot_id, str(chat_id), 'waiting', flow_key)
        return
    if 'reply' in flow:
        reply = _sub_vars(str(flow['reply']), user_input=user_text)
        if flow.get('show_menu'):
            _send_with_menu(token, chat_id, reply, menu)
        else:
            _tg_send(token, chat_id, reply)
    if 'inline_buttons' in flow:
        try:
            btns = [[{'text': b['text'], 'callback_data': b.get('flow', b['text'])}
                     for b in flow['inline_buttons']]]
            req.post(f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': flow.get('ask', 'Choose:'),
                      'reply_markup': {'inline_keyboard': btns}}, timeout=10)
        except Exception:
            pass
    nf = str(flow.get('next_flow', ''))
    if nf and nf in flows:
        _run_flow(bot, token, chat_id, flows, nf, menu, ai_key, ai_prov)


def _handle_yaml_bot(bot, update):
    bot_id = bot['id']; token = bot['bot_token']
    ai_key = str(bot.get('ai_api_key') or '')
    ai_prov = str(bot.get('ai_provider') or 'anthropic')
    try:
        cfg = pyyaml.safe_load(bot.get('yaml_definition') or '')
        if not cfg:
            return
        bc = cfg.get('bot', cfg)
    except Exception as e:
        print(f'[yaml] {e}'); return
    flows = bc.get('flows', {}); menu = bc.get('menu', [])
    default_reply = bc.get('default_reply', 'Please use the menu.')
    if 'callback_query' in update:
        cq = update['callback_query']
        cid = str(cq['message']['chat']['id'])
        fk = cq.get('data', '')
        try:
            req.post(f'https://api.telegram.org/bot{token}/answerCallbackQuery',
                json={'callback_query_id': cq['id']}, timeout=5)
        except Exception:
            pass
        if fk in flows:
            _set_state(bot_id, cid, 'waiting', '')
            _run_flow(bot, token, cid, flows, fk, menu, ai_key, ai_prov)
        return
    msg = update.get('message', {})
    if not msg:
        return
    cid = str(msg['chat']['id'])
    text = msg.get('text', '')
    photo = msg.get('photo')
    if text == '/start':
        _set_state(bot_id, cid, 'waiting', '')
        welcome = str(bc.get('welcome', 'Welcome! I am ' + str(bc.get('name', 'Bot')) + ' ' + chr(0x1f916)))
        kb = _build_keyboard(menu)
        d = {'chat_id': cid, 'text': welcome, 'parse_mode': 'HTML'}
        if kb:
            d['reply_markup'] = kb
        try:
            req.post(f'https://api.telegram.org/bot{token}/sendMessage', json=d, timeout=10)
        except Exception:
            pass
        return
    if photo:
        pfid = photo[-1]['file_id']
        waiting = _get_state(bot_id, cid, 'waiting')
        if waiting:
            oi_str = _get_state(bot_id, cid, f'oi_{waiting}')
            if oi_str:
                try:
                    on_input = json.loads(oi_str)
                    _set_state(bot_id, cid, 'waiting', '')
                    reply, sm, nf = _exec_on_input(token, on_input, cid, ai_key, ai_prov,
                        user_text=None, photo_fid=pfid)
                    if reply:
                        if sm:
                            _send_with_menu(token, cid, reply, menu)
                        else:
                            _tg_send(token, cid, reply)
                    elif not ai_key:
                        _send_with_menu(token, cid,
                            chr(0x26a0) + ' Add an AI key in bot settings to process photos.',
                            menu)
                    if nf and nf in flows:
                        _run_flow(bot, token, cid, flows, nf, menu, ai_key, ai_prov)
                    return
                except Exception as e:
                    print(f'[photo_input] {e}')
                    _set_state(bot_id, cid, 'waiting', '')
        pf_key = str(bc.get('photo_flow', ''))
        if not pf_key:
            for fk, fv in flows.items():
                if isinstance(fv, dict) and fv.get('handle_photo'):
                    pf_key = fk; break
        if pf_key and pf_key in flows:
            _run_flow(bot, token, cid, flows, pf_key, menu, ai_key, ai_prov, photo_fid=pfid)
            return
        if ai_key:
            img_url = _get_photo_url(token, pfid)
            if img_url:
                _tg_send(token, cid, chr(0x23f3) + ' Analyzing your image...')
                result = _ai_vision(ai_key, ai_prov,
                    'Describe this image in detail. If there is text, extract and translate it to Russian.',
                    img_url)
                _send_with_menu(token, cid, result, menu)
                return
        _send_with_menu(token, cid,
            chr(0x1f4f7) + ' Photo received! Add an AI key to enable photo analysis.',
            menu)
        return
    if not text:
        return
    for item in menu:
        if item.get('text') == text:
            fk = str(item.get('flow', ''))
            if fk in flows:
                _set_state(bot_id, cid, 'waiting', '')
                _run_flow(bot, token, cid, flows, fk, menu, ai_key, ai_prov)
                return
    waiting = _get_state(bot_id, cid, 'waiting')
    if waiting:
        oi_str = _get_state(bot_id, cid, f'oi_{waiting}')
        _set_state(bot_id, cid, 'waiting', '')
        if oi_str:
            try:
                on_input = json.loads(oi_str)
                reply, sm, nf = _exec_on_input(token, on_input, cid, ai_key, ai_prov, user_text=text)
                if reply:
                    if sm:
                        _send_with_menu(token, cid, reply, menu)
                    else:
                        _tg_send(token, cid, reply)
                if nf and nf in flows:
                    _run_flow(bot, token, cid, flows, nf, menu, ai_key, ai_prov)
                return
            except Exception as e:
                print(f'[text_input] {e}')
    _send_with_menu(token, cid, default_reply, menu)


@app.route('/webhook', methods=['POST'])
def botbuilder_webhook():
    if not BOTBUILDER_TOKEN:
        return 'ok'
    update = request.json or {}
    try:
        msg = update.get('message', {}); cid = msg.get('chat', {}).get('id')
        if not cid:
            return 'ok'
        mu = f'{RAILWAY_URL}/app' if RAILWAY_URL else ''
        if mu:
            _tg_send(BOTBUILDER_TOKEN, cid,
                chr(0x1f44b) + ' Welcome to <b>BotBuilder</b>!\n\nCreate Telegram bots in minutes.\nTap below to open the app:',
                {'inline_keyboard': [[{'text': chr(0x1f916) + ' Open BotBuilder', 'web_app': {'url': mu}}]]})
        else:
            _tg_send(BOTBUILDER_TOKEN, cid, chr(0x1f44b) + ' Welcome to BotBuilder!')
    except Exception as e:
        print(f'[bb] {e}')
    return 'ok'


@app.route('/bot/<token_hash>', methods=['POST'])
def user_bot_webhook(token_hash):
    update = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bots WHERE bot_token_hash=%s AND status='active'", (token_hash,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return 'ok'
    try:
        _handle_yaml_bot(dict(bot), update)
    except Exception as e:
        print(f'[bot] {e}')
    return 'ok'


try:
    if DATABASE_URL:
        init_db()
except Exception as e:
    print(f'[startup] {e}')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
