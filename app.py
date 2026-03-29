from flask import Flask, request, jsonify
from flask_cors import CORS
import stripe
import sqlite3
import os

app = Flask(__name__)
CORS(app)

# ── CONFIGURAZIONE ────────────────────────────────────────────────────────────
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = "price_1TGO5HDm0ibeaThgU32ILIZ0"
CONVERSIONI_GRATIS = 3

# ── DATABASE ──────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("utenti.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS utenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            conversioni INTEGER DEFAULT 0,
            abbonato INTEGER DEFAULT 0,
            stripe_customer_id TEXT
        )
    """)
    conn.commit()
    conn.close()

# Inizializza il database all'avvio (funziona anche con gunicorn)
init_db()

def get_utente(session_id):
    conn = sqlite3.connect("utenti.db")
    c = conn.cursor()
    c.execute("SELECT * FROM utenti WHERE session_id = ?", (session_id,))
    utente = c.fetchone()
    if not utente:
        c.execute("INSERT INTO utenti (session_id, conversioni, abbonato) VALUES (?, 0, 0)", (session_id,))
        conn.commit()
        c.execute("SELECT * FROM utenti WHERE session_id = ?", (session_id,))
        utente = c.fetchone()
    conn.close()
    return utente

# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "messaggio": "Backend ConvertiPDF attivo!"})

@app.route("/stato", methods=["GET"])
def stato():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"errore": "session_id mancante"}), 400

    utente = get_utente(session_id)
    conversioni = utente[2]
    abbonato = utente[3]

    return jsonify({
        "conversioni_usate": conversioni,
        "conversioni_gratis": CONVERSIONI_GRATIS,
        "abbonato": bool(abbonato),
        "puo_convertire": abbonato or conversioni < CONVERSIONI_GRATIS
    })

@app.route("/converti", methods=["POST"])
def converti():
    data = request.json
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"errore": "session_id mancante"}), 400

    utente = get_utente(session_id)
    conversioni = utente[2]
    abbonato = utente[3]

    if not abbonato and conversioni >= CONVERSIONI_GRATIS:
        return jsonify({
            "errore": "limite_raggiunto",
            "messaggio": "Hai usato tutte le conversioni gratis. Abbonati per continuare!"
        }), 403

    conn = sqlite3.connect("utenti.db")
    c = conn.cursor()
    c.execute("UPDATE utenti SET conversioni = conversioni + 1 WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "conversioni_usate": conversioni + 1})

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"errore": "session_id mancante"}), 400

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"https://convertipdf.netlify.app?success=1&session_id={session_id}",
            cancel_url=f"https://convertipdf.netlify.app?cancelled=1",
            metadata={"session_id": session_id}
        )
        return jsonify({"url": checkout_session.url})
    except Exception as e:
        return jsonify({"errore": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    event = None

    try:
        event = stripe.Event.construct_from(
            stripe.util.convert_to_stripe_object(
                stripe.util.json.loads(payload)
            ), stripe.api_key
        )
    except Exception as e:
        return jsonify({"errore": str(e)}), 400

    if event.type == "checkout.session.completed":
        session = event.data.object
        session_id = session.metadata.get("session_id")
        if session_id:
            conn = sqlite3.connect("utenti.db")
            c = conn.cursor()
            c.execute("UPDATE utenti SET abbonato = 1 WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()

    return jsonify({"ok": True})

# ── AVVIO LOCALE ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"✅ Backend ConvertiPDF avviato sulla porta {port}")
    app.run(host="0.0.0.0", port=port)