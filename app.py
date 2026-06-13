from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import threading

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor

app = Flask(__name__)

# 🔐 TELEGRAM
TELEGRAM_BOT_TOKEN = "8765876132:AAHaQxaoPYS_PTBUE7qvzJeNByi2Ol-A1c0"
TELEGRAM_CHAT_ID = "8372327811"

SIMULATION_MODE = True

# 🧠 DB
conn = sqlite3.connect("prices.db", check_same_thread=False)
cursor = conn.cursor()

db_lock = threading.Lock()

# TABLOLAR
with db_lock:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tracked_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        url TEXT,
        target_price REAL,
        current_price REAL DEFAULT 0.0,
        ai_status TEXT DEFAULT 'Veri Toplanıyor'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        price REAL,
        date TEXT
    )
    """)
    conn.commit()


# 📱 TELEGRAM
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=10)
    except:
        pass


# 🤖 AI MODEL
def predict_price_trend(product_id):
    with db_lock:
        cursor.execute("SELECT price FROM price_history WHERE product_id=? ORDER BY id ASC", (product_id,))
        data = cursor.fetchall()

    prices = [x[0] for x in data]

    if len(prices) < 5:
        return "⏳ Veri Toplanıyor", "Yeterli veri yok", None

    X = np.array(range(len(prices))).reshape(-1, 1)
    y = np.array(prices)

    rf = RandomForestRegressor(n_estimators=50, random_state=42)
    rf.fit(X, y)

    lr = LinearRegression()
    lr.fit(X, y)

    next_step = np.array([[len(prices)]])
    predicted = rf.predict(next_step)[0]
    slope = lr.coef_[0]

    last = prices[-1]
    min_price = min(prices)

    if last <= min_price and slope <= 0:
        return "🛒 ALIM FIRSATI", "En düşük seviyede", round(predicted, 2)

    elif slope < -0.1:
        return "📉 DÜŞÜŞ BEKLENİYOR", "Fiyat düşebilir", round(predicted, 2)

    elif abs(slope) <= 0.1:
        return "➖ STABİL", "Yatay seyir", round(predicted, 2)

    else:
        return "📈 YÜKSELİŞ", "Artış trendi", round(predicted, 2)


# 🕷️ SCRAPER
def check_prices():
    print("⏳ Bot çalışıyor...")

    with db_lock:
        cursor.execute("SELECT id, url, target_price, current_price, product_name FROM tracked_products")
        products = cursor.fetchall()

    for pid, url, target, old_price, name in products:

        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=10)

            soup = BeautifulSoup(r.text, "html.parser")

            title = soup.select_one("a.title")
            price = soup.select_one("h4.price")

            product_name = title.text.strip() if title else name
            current_price = float(price.text.replace("$", "").strip()) if price else old_price

            if SIMULATION_MODE and old_price > 0:
                current_price = old_price - 10

            date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with db_lock:
                cursor.execute(
                    "INSERT INTO price_history (product_id, price, date) VALUES (?, ?, ?)",
                    (pid, current_price, date)
                )
                conn.commit()

            ai_status, ai_msg, pred = predict_price_trend(pid)

            with db_lock:
                cursor.execute("""
                    UPDATE tracked_products
                    SET product_name=?, current_price=?, ai_status=?
                    WHERE id=?
                """, (product_name, current_price, ai_status, pid))
                conn.commit()

        except Exception as e:
            print("Hata:", e)


# 🌐 ROUTES
@app.route("/")
def index():
    with db_lock:
        cursor.execute("SELECT * FROM tracked_products")
        products = cursor.fetchall()
    return render_template("index.html", products=products)


@app.route("/add", methods=["POST"])
def add():
    url = request.form["url"]
    target = float(request.form["target_price"])

    with db_lock:
        cursor.execute("""
        INSERT INTO tracked_products (product_name, url, target_price, current_price)
        VALUES (?, ?, ?, ?)
        """, ("Yeni Ürün", url, target, 0))
        conn.commit()

    return redirect("/")


@app.route("/api/chart/<int:pid>")
def chart(pid):
    with db_lock:
        cursor.execute("SELECT price, date FROM price_history WHERE product_id=?", (pid,))
        data = cursor.fetchall()

    return jsonify({
        "labels": [d[1] for d in data],
        "prices": [d[0] for d in data]
    })


# ⏰ SCHEDULER
scheduler = BackgroundScheduler()
scheduler.add_job(check_prices, 'interval', minutes=2)
scheduler.start()


# 🚀 FLASK START
if __name__ == "__main__":
    print("🚀 Sistem başlatılıyor...")
    app.run(debug=True, use_reloader=False, port=5000)