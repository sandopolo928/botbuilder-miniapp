import os
import json
import hashlib
import hmac
import time
import uuid
from urllib.parse import unquote

from flask import Flask, request, jsonify, send_from_directory
import psycopg2
import psycopg2.extras
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bots (
                    id TEXT PRIMARY KEY,
                    user_id BIGINT REFERENCES users(telegram_id),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    yaml_definition TEXT DEFAULT '',
                    bot_token TEXT,
                    bot_token_hash TEXT UNIQUE,
                    status TEXT DEFAULT 'inactive',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_states (
                    bot_id TEXT,
                    chat_id BIGINT,
                    state_key TEXT,
                    state_value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (bot_id, chat_id, state_key)
                )
            """)
        conn.commit()
        print("[OK] DB initialized")
    except Exception as e:
        print(f"[DB] init error: {e}")
        conn.rollback()
    finally:
        conn.close()


def validate_init_data(init_data):
    if not init_data or not BOTBUILDER_TOKEN:
        return None
    try:
        parsed = {}
        for part in init_data.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                parsed[k] = unquote(v)
        hash_val = parsed.pop("hash", "")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOTBUILDER_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if computed != hash_val:
            return None
        if time.time() - int(parsed.get("auth_date", 0)) > 86400:
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception as e:
        print(f"[AUTH] error: {e}")
        return None


@app.route("/")
@app.route("/app")
def serve_app():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "1.0.0"})


@app.route("/api/auth", methods=["POST"])
def auth():
    data = request.json or {}
    init_data = data.get("initData", "")
    user_data = validate_init_data(init_data)
    if not user_data:
        if os.environ.get("DEV_MODE") == "1":
            user_data = {"id": 12345, "first_name": "Dev", "username": "dev_user"}
        else:
            return jsonify({"error": "Unauthorized"}), 401
    telegram_id = user_data.get("id")
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (telegram_id, username, first_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE
                SET username=EXCLUDED.username, first_name=EXCLUDED.first_name
                RETURNING telegram_id, username, first_name
            """, (telegram_id, user_data.get("username", ""), user_data.get("first_name", "")))
            user = dict(cur.fetchone())
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "user": user})


@app.route("/api/bots", methods=["GET"])
def list_bots():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, name, description, status, created_at FROM bots WHERE user_id=%s ORDER BY created_at DESC",
                (user_id,)
            )
            bots = []
            for r in cur.fetchall():
                b = dict(r)
                if b.get("created_at"):
                    b["created_at"] = str(b["created_at"])
                bots.append(b)
    finally:
        conn.close()
    return jsonify({"bots": bots})


@app.route("/api/bots", methods=["POST"])
def create_bot():
    data = request.json or {}
    user_id = data.get("user_id")
    name = data.get("name", "My Bot")
    description = data.get("description", "")
    yaml_def = data.get("yaml_definition", "")
    bot_token = data.get("bot_token", "")
    if not user_id or not bot_token:
        return jsonify({"error": "user_id and bot_token required"}), 400
    try:
        r = req.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
        if not r.ok or not r.json().get("ok"):
            return jsonify({"error": "Invalid bot token"}), 400
        bot_info = r.json()["result"]
        if not name or name == "My Bot":
            name = bot_info.get("first_name", "My Bot")
    except Exception as e:
        return jsonify({"error": f"Token check failed: {e}"}), 400
    token_hash = hashlib.sha256(bot_token.encode()).hexdigest()[:32]
    bot_id = str(uuid.uuid4())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bots (id, user_id, name, description, yaml_definition, bot_token, bot_token_hash, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'inactive')
                RETURNING id, user_id, name, description, status, created_at
            """, (bot_id, user_id, name, description, yaml_def, bot_token, token_hash))
            bot = dict(cur.fetchone())
            if bot.get("created_at"):
                bot["created_at"] = str(bot["created_at"])
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            conn.close()
        except:
            pass
    return jsonify({"ok": True, "bot": bot, "bot_id": bot_id})


@app.route("/api/bots/<bot_id>/activate", methods=["POST"])
def activate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bots WHERE id=%s", (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    bot = dict(bot)
    bot_token = bot["bot_token"]
    token_hash = bot["bot_token_hash"]
    if not RAILWAY_URL:
        return jsonify({"error": "RAILWAY_URL not set on server"}), 500
    webhook_url = f"{RAILWAY_URL}/bot/{token_hash}"
    r = req.post(
        f"https://api.telegram.org/bot{bot_token}/setWebhook",
        json={"url": webhook_url, "drop_pending_updates": True},
        timeout=10
    )
    if r.ok and r.json().get("ok"):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE bots SET status='active', updated_at=NOW() WHERE id=%s", (bot_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "webhook_url": webhook_url})
    return jsonify({"error": "Webhook failed", "detail": r.json()}), 500


@app.route("/api/bots/<bot_id>/deactivate", methods=["POST"])
def deactivate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bot_token FROM bots WHERE id=%s", (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({"error": "Bot not found"}), 404
    try:
        req.post(f"https://api.telegram.org/bot{bot['bot_token']}/deleteWebhook",
                json={"drop_pending_updates": True}, timeout=10)
    except:
        pass
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE bots SET status='inactive', updated_at=NOW() WHERE id=%s", (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/bots/<bot_id>", methods=["DELETE"])
def delete_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bot_token FROM bots WHERE id=%s", (bot_id,))
            bot = cur.fetchone()
            if bot and bot["bot_token"]:
                try:
                    req.post(f"https://api.telegram.org/bot{bot['bot_token']}/deleteWebhook", timeout=5)
                except:
                    pass
            cur.execute("DELETE FROM bot_states WHERE bot_id=%s", (bot_id,))
            cur.execute("DELETE FROM bots WHERE id=%s", (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/generate", methods=["POST"])
def generate_yaml():
    data = request.json or {}
    description = data.get("description", "").strip()
    api_key = data.get("api_key", "").strip()
    bot_name = data.get("bot_name", "My Bot").strip()
    if not description:
        return jsonify({"error": "description required"}), 400
    if not api_key:
        return jsonify({"ok": True, "yaml": _simple_template(bot_name, description), "source": "template"})
    prompt = f"""Generate a Telegram bot YAML for: "{description}"

Return ONLY valid YAML:
```yaml
bot:
  name: "{bot_name}"
  platform: telegram
  default_reply: "Please use the menu."
  menu:
    - text: "Button 1"
      flow: flow1
  flows:
    flow1:
      reply: "Response text"
      show_menu: true
```
Create 3-5 practical flows. Use {{{{input}}}} for user input in on_input replies."""
    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-opus-4-5", "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]},
            timeout=30
        )
        if not r.ok:
            return jsonify({"ok": True, "yaml": _simple_template(bot_name, description), "source": "template"})
        content = r.json()["content"][0]["text"]
        import re
        m = re.search(r"```yaml\n(.*?)\n```", content, re.DOTALL)
        yaml_text = m.group(1) if m else content
        pyyaml.safe_load(yaml_text)
        return jsonify({"ok": True, "yaml": yaml_text, "source": "ai"})
    except Exception as e:
        return jsonify({"ok": True, "yaml": _simple_template(bot_name, description), "source": "template", "note": str(e)})




def _simple_template(name, description):
    q = chr(34)
    safe_name = str(name or "Bot").replace(chr(34), chr(39))
    safe_desc = str(description or "")[:80].replace(chr(34), chr(39))
    lines = [
        "bot:",
        "  name: " + q + safe_name + q,
        "  platform: telegram",
        "  default_reply: " + q + "Please use the menu below." + q,
        "  menu:",
        "    - text: " + q + chr(0x2139) + chr(0xfe0f) + " About" + q,
        "      flow: about",
        "    - text: " + q + chr(0x1f4de) + " Contact" + q,
        "      flow: contact",
        "    - text: " + q + chr(0x2753) + " Help" + q,
        "      flow: help",
        "  flows:",
        "    about:",
        "      reply: " + q + "Welcome! " + safe_desc + q,
        "      show_menu: true",
        "    contact:",
        "      ask: " + q + "Send your message:" + q,
        "      on_input:",
        "        reply: " + q + chr(0x2705) + " Received: {{input}}" + q,
        "        show_menu: true",
        "    help:",
        "      reply: " + q + "Use the menu buttons to navigate." + q,
        "      show_menu: true",
    ]
    return chr(10).join(lines)

def _tg_send(token, chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=data, timeout=10)
    except:
        pass


@app.route("/webhook", methods=["POST"])
def botbuilder_webhook():
    if not BOTBUILDER_TOKEN:
        return "ok"
    update = request.json or {}
    try:
        msg = update.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        if not chat_id:
            return "ok"
        mini_url = f"{RAILWAY_URL}/app" if RAILWAY_URL else ""
        kb = json.dumps({"inline_keyboard": [[{"text": "\ud83e\udd16 Open BotBuilder", "web_app": {"url": mini_url}}]]}) if mini_url else None
        _tg_send(BOTBUILDER_TOKEN, chat_id, "\ud83d\udc4b Welcome to <b>BotBuilder</b>!\n\nCreate Telegram bots without code.\n\nTap the button below to open the app:", kb)
    except Exception as e:
        print(f"[BB webhook] {e}")
    return "ok"


@app.route("/bot/<token_hash>", methods=["POST"])
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
        return "ok"
    try:
        _handle_yaml_bot(dict(bot), update)
    except Exception as e:
        print(f"[bot handler] {e}")
    return "ok"


def _get_state(bot_id, chat_id, key):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state_value FROM bot_states WHERE bot_id=%s AND chat_id=%s AND state_key=%s",
                       (bot_id, chat_id, key))
            row = cur.fetchone()
            return row["state_value"] if row else ""
    except:
        return ""
    finally:
        conn.close()


def _set_state(bot_id, chat_id, key, value):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO bot_states (bot_id, chat_id, state_key, state_value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (bot_id, chat_id, state_key)
                DO UPDATE SET state_value=EXCLUDED.state_value, updated_at=NOW()""",
                (bot_id, chat_id, key, value))
        conn.commit()
    except:
        pass
    finally:
        conn.close()


def _build_keyboard(menu_items):
    if not menu_items:
        return None
    rows, row = [], []
    for item in menu_items:
        row.append({"text": item.get("text", "")})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return {"keyboard": rows, "resize_keyboard": True}


def _handle_yaml_bot(bot, update):
    bot_id = bot["id"]
    token = bot["bot_token"]
    try:
        cfg = pyyaml.safe_load(bot.get("yaml_definition", ""))
        if not cfg:
            return
        bc = cfg.get("bot", cfg)
    except:
        return
    flows = bc.get("flows", {})
    menu = bc.get("menu", [])
    default_reply = bc.get("default_reply", "I don't understand.")

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        flow_key = cq.get("data", "")
        req.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": cq["id"]}, timeout=5)
        if flow_key in flows:
            _run_flow(bot_id, token, chat_id, flows, flow_key, menu, None)
        return

    msg = update.get("message", {})
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    if text == "/start":
        welcome = bc.get("welcome", f"Welcome! I'm {bc.get('name', 'Bot')} \ud83e\udd16")
        kb = _build_keyboard(menu)
        data = {"chat_id": chat_id, "text": welcome, "parse_mode": "HTML"}
        if kb:
            data["reply_markup"] = kb
        req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=data, timeout=10)
        _set_state(bot_id, chat_id, "waiting", "")
        return

    for item in menu:
        if item.get("text") == text:
            flow_key = item.get("flow", "")
            if flow_key in flows:
                _run_flow(bot_id, token, chat_id, flows, flow_key, menu, None)
                return

    waiting = _get_state(bot_id, chat_id, "waiting")
    if waiting:
        oi_key = f"oi_{waiting}"
        oi_str = _get_state(bot_id, chat_id, oi_key)
        if oi_str:
            try:
                on_input = json.loads(oi_str)
                reply = on_input.get("reply", "")
                if reply:
                    _tg_send(token, chat_id, reply.replace("{{input}}", str(text)))
                if on_input.get("show_menu"):
                    kb = _build_keyboard(menu)
                    if kb:
                        req.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": chat_id, "text": "\ud83d\udccd Menu:", "reply_markup": kb}, timeout=10)
                if "next_flow" in on_input and on_input["next_flow"] in flows:
                    _run_flow(bot_id, token, chat_id, flows, on_input["next_flow"], menu, None)
            except:
                pass
        _set_state(bot_id, chat_id, "waiting", "")
        return

    kb = _build_keyboard(menu)
    data = {"chat_id": chat_id, "text": default_reply, "parse_mode": "HTML"}
    if kb:
        data["reply_markup"] = kb
    req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=data, timeout=10)


def _run_flow(bot_id, token, chat_id, flows, flow_key, menu, user_input):
    flow = flows.get(flow_key)
    if not flow:
        return
    if "ask" in flow and user_input is None:
        _tg_send(token, chat_id, flow["ask"])
        if "on_input" in flow:
            _set_state(bot_id, chat_id, f"oi_{flow_key}", json.dumps(flow["on_input"]))
        _set_state(bot_id, chat_id, "waiting", flow_key)
        return
    if "reply" in flow:
        reply_text = flow["reply"]
        if user_input:
            reply_text = reply_text.replace("{{input}}", str(user_input))
        if flow.get("show_menu"):
            kb = _build_keyboard(menu)
            data = {"chat_id": chat_id, "text": reply_text, "parse_mode": "HTML"}
            if kb:
                data["reply_markup"] = kb
            req.post(f"https://api.telegram.org/bot{token}/sendMessage", json=data, timeout=10)
        else:
            _tg_send(token, chat_id, reply_text)
    if "inline_buttons" in flow:
        btns = [[{"text": b["text"], "callback_data": b.get("flow", b["text"])} for b in flow["inline_buttons"]]]
        req.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": flow.get("ask", "Choose:"),
                      "reply_markup": {"inline_keyboard": btns}}, timeout=10)
    if "next_flow" in flow and flow["next_flow"] in flows:
        _run_flow(bot_id, token, chat_id, flows, flow["next_flow"], menu, None)


try:
    if DATABASE_URL:
        init_db()
except Exception as e:
    print(f"[startup] DB error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
