
import os, json, hashlib, hmac, time, uuid, base64 as b64mod
from urllib.parse import unquote
from flask import Flask, request, jsonify, send_from_directory
import psycopg2, psycopg2.extras
import requests as req
import yaml as pyyaml

app = Flask(__name__, static_folder="static")
BOTBUILDER_TOKEN = os.environ.get("BOTBUILDER_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
RAILWAY_URL = os.environ.get("RAILWAY_URL", "")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS users (telegram_id BIGINT PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW())")
            cur.execute("CREATE TABLE IF NOT EXISTS bots (id TEXT PRIMARY KEY, user_id BIGINT REFERENCES users(telegram_id), name TEXT NOT NULL, description TEXT DEFAULT '', yaml_definition TEXT DEFAULT '', bot_token TEXT, bot_token_hash TEXT UNIQUE, bot_username TEXT DEFAULT '', ai_api_key TEXT DEFAULT '', ai_provider TEXT DEFAULT 'anthropic', status TEXT DEFAULT 'inactive', created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())")
            for col, defn in [("bot_username","TEXT DEFAULT ''"),("ai_api_key","TEXT DEFAULT ''"),("ai_provider","TEXT DEFAULT 'anthropic'")]:
                try: cur.execute(f"ALTER TABLE bots ADD COLUMN IF NOT EXISTS {col} {defn}")
                except: pass
            cur.execute("CREATE TABLE IF NOT EXISTS bot_states (bot_id TEXT, chat_id TEXT, state_key TEXT, state_value TEXT, updated_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (bot_id, chat_id, state_key))")
        conn.commit(); print("[OK] DB v2.0 ready")
    except Exception as e: print(f"[DB] {e}"); conn.rollback()
    finally: conn.close()

def validate_init_data(init_data):
    if not init_data or not BOTBUILDER_TOKEN: return None
    try:
        parsed = {}
        for part in init_data.split("&"):
            if "=" in part:
                k, v = part.split("=", 1); parsed[k] = unquote(v)
        hash_val = parsed.pop("hash", "")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOTBUILDER_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if computed != hash_val or time.time() - int(parsed.get("auth_date", 0)) > 86400: return None
        return json.loads(parsed.get("user", "{}"))
    except: return None

@app.route("/")
@app.route("/app")
def serve_app(): return send_from_directory("static", "index.html")

@app.route("/health")
def health(): return jsonify({"status": "ok", "version": "2.0.0"})

@app.route("/api/auth", methods=["POST"])
def auth():
    data = request.json or {}
    user_data = validate_init_data(data.get("initData", ""))
    if not user_data:
        if os.environ.get("DEV_MODE") == "1": user_data = {"id": 12345, "first_name": "Dev", "username": "dev"}
        else: return jsonify({"error": "Unauthorized"}), 401
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (telegram_id, username, first_name) VALUES (%s,%s,%s) ON CONFLICT (telegram_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name RETURNING telegram_id, username, first_name",
                (user_data["id"], user_data.get("username",""), user_data.get("first_name","")))
            user = dict(cur.fetchone())
        conn.commit()
    finally: conn.close()
    return jsonify({"ok": True, "user": user})

@app.route("/api/bots", methods=["GET"])
def list_bots():
    uid = request.args.get("user_id")
    if not uid: return jsonify({"error": "user_id required"}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, user_id, name, description, status, bot_username, ai_provider, (ai_api_key != '') as has_ai_key, created_at FROM bots WHERE user_id=%s ORDER BY created_at DESC", (uid,))
            bots = [{**dict(r), "created_at": str(r["created_at"])} for r in cur.fetchall()]
    finally: conn.close()
    return jsonify({"bots": bots})

@app.route("/api/bots", methods=["POST"])
def create_bot():
    data = request.json or {}
    uid = data.get("user_id"); bt = data.get("bot_token","")
    if not uid or not bt: return jsonify({"error": "user_id and bot_token required"}), 400
    try:
        r = req.get(f"https://api.telegram.org/bot{bt}/getMe", timeout=10)
        if not r.ok or not r.json().get("ok"): return jsonify({"error": "Invalid bot token"}), 400
        info = r.json()["result"]
    except Exception as e: return jsonify({"error": str(e)}), 400
    name = data.get("name") or info.get("first_name","My Bot")
    th = hashlib.sha256(bt.encode()).hexdigest()[:32]; bid = str(uuid.uuid4())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO bots (id,user_id,name,description,yaml_definition,bot_token,bot_token_hash,bot_username,ai_api_key,ai_provider,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'inactive') RETURNING id,user_id,name,description,status,bot_username,created_at",
                (bid,uid,name,data.get("description",""),data.get("yaml_definition",""),bt,th,info.get("username",""),data.get("ai_api_key",""),data.get("ai_provider","anthropic")))
            bot = dict(cur.fetchone()); bot["created_at"] = str(bot.get("created_at",""))
        conn.commit()
    except Exception as e: conn.rollback(); conn.close(); return jsonify({"error": str(e)}), 500
    finally:
        try: conn.close()
        except: pass
    return jsonify({"ok": True, "bot": bot, "bot_id": bid})

@app.route("/api/bots/<bot_id>/ai_key", methods=["PUT"])
def update_ai_key(bot_id):
    data = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE bots SET ai_api_key=%s, ai_provider=%s, updated_at=NOW() WHERE id=%s",
                (data.get("ai_api_key",""), data.get("ai_provider","anthropic"), bot_id))
        conn.commit()
    finally: conn.close()
    return jsonify({"ok": True})

@app.route("/api/bots/<bot_id>/activate", methods=["POST"])
def activate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bots WHERE id=%s", (bot_id,)); bot = cur.fetchone()
    finally: conn.close()
    if not bot: return jsonify({"error": "Bot not found"}), 404
    bot = dict(bot)
    if not RAILWAY_URL: return jsonify({"error": "RAILWAY_URL not set"}), 500
    wh = f"{RAILWAY_URL}/bot/{bot['bot_token_hash']}"
    r = req.post(f"https://api.telegram.org/bot{bot['bot_token']}/setWebhook", json={"url": wh, "drop_pending_updates": True}, timeout=10)
    if r.ok and r.json().get("ok"):
        conn = get_db()
        try:
            with conn.cursor() as cur: cur.execute("UPDATE bots SET status='active', updated_at=NOW() WHERE id=%s", (bot_id,))
            conn.commit()
        finally: conn.close()
        return jsonify({"ok": True, "webhook_url": wh})
    return jsonify({"error": "Webhook failed", "detail": r.json()}), 500

@app.route("/api/bots/<bot_id>/deactivate", methods=["POST"])
def deactivate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur: cur.execute("SELECT bot_token FROM bots WHERE id=%s", (bot_id,)); bot = cur.fetchone()
    finally: conn.close()
    if not bot: return jsonify({"error": "Bot not found"}), 404
    try: req.post(f"https://api.telegram.org/bot{bot['bot_token']}/deleteWebhook", json={"drop_pending_updates": True}, timeout=10)
    except: pass
    conn = get_db()
    try:
        with conn.cursor() as cur: cur.execute("UPDATE bots SET status='inactive', updated_at=NOW() WHERE id=%s", (bot_id,))
        conn.commit()
    finally: conn.close()
    return jsonify({"ok": True})

@app.route("/api/bots/<bot_id>", methods=["DELETE"])
def delete_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bot_token FROM bots WHERE id=%s", (bot_id,)); bot = cur.fetchone()
            if bot and bot["bot_token"]:
                try: req.post(f"https://api.telegram.org/bot{bot['bot_token']}/deleteWebhook", timeout=5)
                except: pass
            cur.execute("DELETE FROM bot_states WHERE bot_id=%s", (bot_id,))
            cur.execute("DELETE FROM bots WHERE id=%s", (bot_id,))
        conn.commit()
    finally: conn.close()
    return jsonify({"ok": True})

def _simple_template(name, description, has_ai=False):
    q = chr(34); n = str(name or "Bot").replace(chr(34), chr(39)); d = str(description or "")[:80].replace(chr(34), chr(39))
    if has_ai:
        lines = ["bot:", "  name: "+q+n+q, "  platform: telegram",
            "  default_reply: "+q+"Send a message or use the menu."+q,
            "  menu:",
            "    - text: "+q+chr(0x1f4ac)+" Chat AI"+q, "      flow: ai_chat",
            "    - text: "+q+chr(0x1f4f7)+" Send Photo"+q, "      flow: photo_analyze",
            "    - text: "+q+chr(0x2753)+" Help"+q, "      flow: help",
            "  flows:",
            "    ai_chat:",
            "      ask: "+q+"What would you like to know?"+q,
            "      on_input:",
            "        call_ai:",
            "          system: "+q+"You are a helpful assistant. "+d+q,
            "          prompt: "+q+"{{input}}"+q,
            "        reply: "+q+"{{ai_result}}"+q,
            "        show_menu: true",
            "    photo_analyze:",
            "      handle_photo: true",
            "      call_ai_vision:",
            "        prompt: "+q+"Describe the image, extract and translate any text."+q,
            "      reply: "+q+"{{ai_result}}"+q,
            "    help:",
            "      reply: "+q+"I am "+n+". "+d+" Use menu to interact."+q,
            "      show_menu: true"]
    else:
        lines = ["bot:", "  name: "+q+n+q, "  platform: telegram",
            "  default_reply: "+q+"Please use the menu below."+q,
            "  menu:",
            "    - text: "+q+chr(0x2139)+chr(0xfe0f)+" About"+q, "      flow: about",
            "    - text: "+q+chr(0x1f4de)+" Contact"+q, "      flow: contact",
            "    - text: "+q+chr(0x2753)+" Help"+q, "      flow: help",
            "  flows:",
            "    about:", "      reply: "+q+"Welcome! "+d+q, "      show_menu: true",
            "    contact:", "      ask: "+q+"Send your message:"+q,
            "      on_input:", "        reply: "+q+chr(0x2705)+" Received: {{input}}"+q,
            "        show_menu: true",
            "    help:", "      reply: "+q+"Use the menu buttons to navigate."+q, "      show_menu: true"]
    return chr(10).join(lines)

@app.route("/api/generate", methods=["POST"])
def generate_yaml():
    data = request.json or {}
    desc = (data.get("description") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    provider = data.get("ai_provider", "anthropic")
    bot_name = (data.get("bot_name") or "My Bot").strip()
    if not desc: return jsonify({"error": "description required"}), 400
    if not api_key: return jsonify({"ok": True, "yaml": _simple_template(bot_name, desc, False), "source": "template"})
    prompt = (
        'Create a Telegram bot YAML for: "' + desc + '"\n\n'
        'Rules: use call_ai for text AI flows, call_ai_vision for photo flows.\n'
        'Example structure:\n'
        'bot:\n  name: "BotName"\n  platform: telegram\n  default_reply: "Use menu."\n'
        '  menu:\n    - text: "Text flow"\n      flow: text_flow\n'
        '    - text: "Photo flow"\n      flow: photo_flow\n'
        '  flows:\n    text_flow:\n      ask: "Send text:"\n      on_input:\n'
        '        call_ai:\n          system: "You are expert in X."\n'
        '          prompt: "{{input}}"\n        reply: "{{ai_result}}"\n        show_menu: true\n'
        '    photo_flow:\n      handle_photo: true\n      call_ai_vision:\n'
        '        prompt: "Extract text, translate to Russian."\n      reply: "{{ai_result}}"\n\n'
        'Create 3-5 practical flows. Language: same as description. Return ONLY YAML.'
    )
    try:
        if provider == "openai":
            r = req.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "max_tokens": 2000, "messages": [{"role":"user","content":prompt}]}, timeout=30)
            content = r.json()["choices"][0]["message"]["content"] if r.ok else None
        else:
            r = req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5", "max_tokens": 2000, "messages": [{"role":"user","content":prompt}]}, timeout=30)
            content = r.json()["content"][0]["text"] if r.ok else None
        if not content: return jsonify({"ok": True, "yaml": _simple_template(bot_name, desc, True), "source": "template"})
        import re
        m = re.search(r"```yaml\n(.*?)\n```", content, re.DOTALL)
        yaml_text = m.group(1) if m else content.strip()
        pyyaml.safe_load(yaml_text)
        return jsonify({"ok": True, "yaml": yaml_text, "source": "ai"})
    except Exception as e:
        return jsonify({"ok": True, "yaml": _simple_template(bot_name, desc, True), "source": "template", "note": str(e)})

def _tg_send(token, chat_id, text, markup=None):
    d = {"chat_id": chat_id, "text": text or ".", "parse_mode": "HTML"}
    if markup: d["reply_markup"] = markup
    try: req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=d, timeout=10)
    except: pass

def _build_keyboard(menu):
    if not menu: return None
    rows, row = [], []
    for item in menu:
        row.append({"text": item.get("text","")})
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    return {"keyboard": rows, "resize_keyboard": True}

def _send_with_menu(token, chat_id, text, menu):
    kb = _build_keyboard(menu)
    d = {"chat_id": chat_id, "text": text or ".", "parse_mode": "HTML"}
    if kb: d["reply_markup"] = kb
    try: req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=d, timeout=10)
    except: pass

def _get_state(bot_id, chat_id, key):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state_value FROM bot_states WHERE bot_id=%s AND chat_id=%s AND state_key=%s", (bot_id, str(chat_id), key))
            row = cur.fetchone(); return row["state_value"] if row else ""
    except: return ""
    finally: conn.close()

def _set_state(bot_id, chat_id, key, value):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO bot_states (bot_id,chat_id,state_key,state_value) VALUES (%s,%s,%s,%s) ON CONFLICT (bot_id,chat_id,state_key) DO UPDATE SET state_value=EXCLUDED.state_value, updated_at=NOW()", (bot_id, str(chat_id), key, value))
        conn.commit()
    except Exception as e: print(f"[state] {e}")
    finally: conn.close()

def _get_photo_url(token, file_id):
    try:
        r = req.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}, timeout=10)
        if r.ok: return f"https://api.telegram.org/file/bot{token}/{r.json()['result']['file_path']}"
    except: pass
    return None

def _ai_text(api_key, provider, system, user_msg):
    try:
        if provider == "openai":
            r = req.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "max_tokens": 2000, "messages": [{"role":"system","content":system},{"role":"user","content":user_msg}]}, timeout=45)
            return r.json()["choices"][0]["message"]["content"] if r.ok else f"AI error {r.status_code}"
        else:
            r = req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5", "max_tokens": 2000, "system": system, "messages": [{"role":"user","content":user_msg}]}, timeout=45)
            return r.json()["content"][0]["text"] if r.ok else f"AI error {r.status_code}"
    except Exception as e: return f"AI error: {e}"

def _ai_vision(api_key, provider, prompt, img_url):
    try:
        if provider == "openai":
            r = req.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "max_tokens": 2000, "messages": [{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":img_url,"detail":"high"}}]}]}, timeout=60)
            return r.json()["choices"][0]["message"]["content"] if r.ok else f"Vision error {r.status_code}"
        else:
            img_r = req.get(img_url, timeout=30)
            if not img_r.ok: return "Could not download image"
            img_b64 = b64mod.b64encode(img_r.content).decode()
            mt = img_r.headers.get("content-type","image/jpeg").split(";")[0]
            r = req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5", "max_tokens": 2000, "messages": [{"role":"user","content":[
                    {"type":"image","source":{"type":"base64","media_type":mt,"data":img_b64}},
                    {"type":"text","text":prompt}]}]}, timeout=90)
            return r.json()["content"][0]["text"] if r.ok else f"Vision error {r.status_code}"
    except Exception as e: return f"Vision error: {e}"

def _exec_on_input(token, on_input, chat_id, ai_key, ai_prov, user_text=None, photo_fid=None):
    ai_result = None
    has_ai_call = any(k in on_input for k in ["call_ai","call_openai","call_anthropic","call_ai_vision","call_openai_vision","call_anthropic_vision"])
    if has_ai_call and ai_key: _tg_send(token, chat_id, chr(0x23f3)+" Processing...")
    if user_text is not None:
        if "call_ai" in on_input:
            c = on_input["call_ai"] if isinstance(on_input["call_ai"],dict) else {}
            ai_result = _ai_text(ai_key,ai_prov,c.get("system","You are a helpful assistant."),str(c.get("prompt","{{input}}")).replace("{{input}}",user_text)) if ai_key else chr(0x26a0)+" No AI key. Add it in bot settings."
        elif "call_openai" in on_input:
            c = on_input["call_openai"] if isinstance(on_input["call_openai"],dict) else {}
            ai_result = _ai_text(ai_key,"openai",c.get("system","You are a helpful assistant."),str(c.get("prompt","{{input}}")).replace("{{input}}",user_text)) if ai_key else chr(0x26a0)+" No API key."
        elif "call_anthropic" in on_input:
            c = on_input["call_anthropic"] if isinstance(on_input["call_anthropic"],dict) else {}
            ai_result = _ai_text(ai_key,"anthropic",c.get("system","You are a helpful assistant."),str(c.get("prompt","{{input}}")).replace("{{input}}",user_text)) if ai_key else chr(0x26a0)+" No API key."
        elif ai_key and "{{ai_result}}" in on_input.get("reply",""):
            ai_result = _ai_text(ai_key, ai_prov, "You are a helpful assistant.", user_text)
    if photo_fid is not None:
        img_url = _get_photo_url(token, photo_fid)
        found_vision = False
        for key, prov in [("call_ai_vision",ai_prov),("call_openai_vision","openai"),("call_anthropic_vision","anthropic")]:
            if key in on_input:
                c = on_input[key] if isinstance(on_input[key],dict) else {}
                ai_result = _ai_vision(ai_key,prov,c.get("prompt","Extract and describe all text."),img_url) if (ai_key and img_url) else chr(0x26a0)+" Cannot process image: add AI key in bot settings."
                found_vision = True; break
        if not found_vision and ai_key and img_url:
            vp = on_input.get("vision_prompt","Extract and translate all text in this image to Russian.")
            ai_result = _ai_vision(ai_key, ai_prov, vp, img_url)
    tpl = on_input.get("reply","")
    if tpl:
        reply = tpl
        if ai_result: reply = reply.replace("{{ai_result}}",ai_result).replace("{{result}}",ai_result)
        if user_text: reply = reply.replace("{{input}}",user_text)
        return reply, on_input.get("show_menu",False), on_input.get("next_flow","")
    elif ai_result:
        return ai_result, on_input.get("show_menu",False), on_input.get("next_flow","")
    return None, False, ""

def _run_flow(bot, token, chat_id, flows, flow_key, menu, ai_key, ai_prov, user_text=None, photo_fid=None):
    flow = flows.get(flow_key)
    if not flow: return
    bot_id = bot["id"]
    if photo_fid is not None and flow.get("handle_photo"):
        img_url = _get_photo_url(token, photo_fid)
        if ai_key and img_url:
            _tg_send(token, chat_id, chr(0x23f3)+" Analyzing image...")
            c = flow.get("call_ai_vision",{})
            prompt = c.get("prompt","Describe the image, extract and translate any text to Russian.") if isinstance(c,dict) else "Describe the image, extract and translate any text to Russian."
            ai_result = _ai_vision(ai_key, ai_prov, prompt, img_url)
        else:
            ai_result = chr(0x26a0)+" AI key not configured. Add it in bot settings via Mini App."
        reply = str(flow.get("reply","{{ai_result}}"))
        reply = reply.replace("{{ai_result}}",ai_result).replace("{{result}}",ai_result) if ai_result else reply
        if "{{" not in reply:
            if flow.get("show_menu"): _send_with_menu(token, chat_id, reply, menu)
            else: _tg_send(token, chat_id, reply)
        elif ai_result: _tg_send(token, chat_id, ai_result)
        return
    if "ask" in flow and user_text is None and photo_fid is None:
        _tg_send(token, chat_id, flow["ask"])
        if "on_input" in flow: _set_state(bot_id, str(chat_id), f"oi_{flow_key}", json.dumps(flow["on_input"]))
        _set_state(bot_id, str(chat_id), "waiting", flow_key)
        return
    if "reply" in flow:
        reply = str(flow["reply"])
        if user_text: reply = reply.replace("{{input}}", user_text)
        if flow.get("show_menu"): _send_with_menu(token, chat_id, reply, menu)
        else: _tg_send(token, chat_id, reply)
    if "inline_buttons" in flow:
        btns = [[{"text":b["text"],"callback_data":b.get("flow",b["text"])} for b in flow["inline_buttons"]]]
        try: req.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat_id,"text":flow.get("ask","Choose:"),"reply_markup":{"inline_keyboard":btns}}, timeout=10)
        except: pass
    if "next_flow" in flow and flow["next_flow"] in flows:
        _run_flow(bot, token, chat_id, flows, flow["next_flow"], menu, ai_key, ai_prov)

def _handle_yaml_bot(bot, update):
    bot_id = bot["id"]; token = bot["bot_token"]
    ai_key = bot.get("ai_api_key","") or ""; ai_prov = bot.get("ai_provider","anthropic") or "anthropic"
    try:
        cfg = pyyaml.safe_load(bot.get("yaml_definition","") or "")
        if not cfg: return
        bc = cfg.get("bot", cfg)
    except Exception as e: print(f"[yaml] {e}"); return
    flows = bc.get("flows",{}); menu = bc.get("menu",[]); default_reply = bc.get("default_reply","Please use the menu.")
    if "callback_query" in update:
        cq = update["callback_query"]; cid = str(cq["message"]["chat"]["id"]); fk = cq.get("data","")
        try: req.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id":cq["id"]}, timeout=5)
        except: pass
        if fk in flows: _run_flow(bot, token, cid, flows, fk, menu, ai_key, ai_prov)
        return
    msg = update.get("message",{})
    if not msg: return
    cid = str(msg["chat"]["id"]); text = msg.get("text",""); photo = msg.get("photo")
    if text == "/start":
        welcome = bc.get("welcome","Welcome! I am "+bc.get("name","Bot")+" "+chr(0x1f916))
        _set_state(bot_id, cid, "waiting", "")
        kb = _build_keyboard(menu)
        d = {"chat_id":cid,"text":welcome,"parse_mode":"HTML"}
        if kb: d["reply_markup"] = kb
        try: req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=d, timeout=10)
        except: pass
        return
    if photo:
        pfid = photo[-1]["file_id"]
        waiting = _get_state(bot_id, cid, "waiting")
        if waiting:
            oi_str = _get_state(bot_id, cid, f"oi_{waiting}")
            if oi_str:
                try:
                    on_input = json.loads(oi_str)
                    reply, sm, nf = _exec_on_input(token, on_input, cid, ai_key, ai_prov, user_text=None, photo_fid=pfid)
                    _set_state(bot_id, cid, "waiting", "")
                    if reply:
                        if sm: _send_with_menu(token, cid, reply, menu)
                        else: _tg_send(token, cid, reply)
                    if nf and nf in flows: _run_flow(bot, token, cid, flows, nf, menu, ai_key, ai_prov)
                    return
                except Exception as e: print(f"[photo_input] {e}"); _set_state(bot_id, cid, "waiting", "")
        pfk = bc.get("photo_flow","")
        if not pfk:
            for fk,fv in flows.items():
                if isinstance(fv,dict) and fv.get("handle_photo"): pfk = fk; break
        if pfk and pfk in flows:
            _run_flow(bot, token, cid, flows, pfk, menu, ai_key, ai_prov, photo_fid=pfid); return
        if ai_key:
            img_url = _get_photo_url(token, pfid)
            if img_url:
                _tg_send(token, cid, chr(0x23f3)+" Analyzing image...")
                result = _ai_vision(ai_key, ai_prov, "Describe the image. Extract and translate any text to Russian.", img_url)
                _tg_send(token, cid, result); return
        _send_with_menu(token, cid, default_reply, menu); return
    if not text: return
    for item in menu:
        if item.get("text") == text:
            fk = item.get("flow","")
            if fk in flows:
                _set_state(bot_id, cid, "waiting", "")
                _run_flow(bot, token, cid, flows, fk, menu, ai_key, ai_prov); return
    waiting = _get_state(bot_id, cid, "waiting")
    if waiting:
        oi_str = _get_state(bot_id, cid, f"oi_{waiting}")
        _set_state(bot_id, cid, "waiting", "")
        if oi_str:
            try:
                on_input = json.loads(oi_str)
                reply, sm, nf = _exec_on_input(token, on_input, cid, ai_key, ai_prov, user_text=text)
                if reply:
                    if sm: _send_with_menu(token, cid, reply, menu)
                    else: _tg_send(token, cid, reply)
                if nf and nf in flows: _run_flow(bot, token, cid, flows, nf, menu, ai_key, ai_prov)
                return
            except Exception as e: print(f"[text_input] {e}")
    _send_with_menu(token, cid, default_reply, menu)

@app.route("/webhook", methods=["POST"])
def botbuilder_webhook():
    if not BOTBUILDER_TOKEN: return "ok"
    update = request.json or {}
    try:
        msg = update.get("message",{}); cid = msg.get("chat",{}).get("id")
        if not cid: return "ok"
        mu = f"{RAILWAY_URL}/app" if RAILWAY_URL else ""
        if mu:
            _tg_send(BOTBUILDER_TOKEN, cid, chr(0x1f44b)+" Welcome to <b>BotBuilder</b>!\n\nCreate bots without code. Tap below:", {"inline_keyboard":[[{"text":chr(0x1f916)+" Open BotBuilder","web_app":{"url":mu}}]]})
        else:
            _tg_send(BOTBUILDER_TOKEN, cid, chr(0x1f44b)+" Welcome to BotBuilder!")
    except Exception as e: print(f"[bb] {e}")
    return "ok"

@app.route("/bot/<token_hash>", methods=["POST"])
def user_bot_webhook(token_hash):
    update = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bots WHERE bot_token_hash=%s AND status='active'", (token_hash,)); bot = cur.fetchone()
    finally: conn.close()
    if not bot: return "ok"
    try: _handle_yaml_bot(dict(bot), update)
    except Exception as e: print(f"[bot] {e}")
    return "ok"

try:
    if DATABASE_URL: init_db()
except Exception as e: print(f"[startup] {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
