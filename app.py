import os
import threading
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
# Avoid external flask_cors dependency to keep runtime simple.


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pos_stock.db")
RESERVATION_TTL_SECONDS = 600
SEED_ON_START = True

app = Flask(__name__)
# Restrict allowed origin to the frontend host and ensure preflight OPTIONS
# requests are handled correctly. Do not use '*' with credentials enabled.
ALLOWED_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]

def _add_cors_headers(resp):
    origin = request.headers.get("Origin")
    if origin and origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Vary"] = "Origin"
    return resp


@app.after_request
def add_cors_after_request(response):
    return _add_cors_headers(response)


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        from flask import make_response
        resp = make_response("")
        resp.status_code = 200
        return _add_cors_headers(resp)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class Article(db.Model):
    __tablename__ = "articles"
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self, include_reserved=False):
        reserved = compute_reserved_for_article(self.id) if include_reserved else 0
        return {
            "id": self.id,
            "sku": self.sku,
            "name": self.name,
            "price": self.price,
            "quantity": self.quantity,
            "reserved_qty": reserved
        }

class Reservation(db.Model):
    __tablename__ = "reservations"
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.String(64), nullable=False, index=True)
    article_id = db.Column(db.Integer, db.ForeignKey("articles.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)
    article = db.relationship("Article")

def now_utc():
    return datetime.now(timezone.utc)

def compute_reserved_for_article(article_id):
    total = db.session.query(func.sum(Reservation.qty)).filter(
        Reservation.article_id == article_id,
        Reservation.active == 1,
        Reservation.expires_at > now_utc()
    ).scalar()
    return int(total or 0)

def cleanup_loop():
    while True:
        with app.app_context():
            expired = Reservation.query.filter(
                Reservation.active == 1,
                Reservation.expires_at <= now_utc()
            ).all()
            for r in expired:
                r.active = 0
            db.session.commit()
        time.sleep(30)

threading.Thread(target=cleanup_loop, daemon=True).start()

def seed_sample():
    if Article.query.count() == 0:
        sample = [
            {"sku": "SKU1", "name": "T-shirt Bleu", "price": 25, "quantity": 40},
            {"sku": "SKU2", "name": "Chemise Blanche", "price": 45, "quantity": 20},
            {"sku": "SKU3", "name": "Casquette", "price": 15, "quantity": 10},
        ]
        for s in sample:
            db.session.add(Article(**s))
        db.session.commit()

with app.app_context():
    db.create_all()
    if SEED_ON_START:
        seed_sample()

@app.route("/articles", methods=["GET"])
def get_articles():
    return jsonify([a.to_dict(include_reserved=True) for a in Article.query.all()])

@app.route("/cart/add", methods=["POST"])
def cart_add():
    data = request.get_json() or {}
    cart_id = str(data.get("cart_id"))
    article_id = data.get("article_id")
    qty = int(data.get("qty", 1))
    if not article_id or not cart_id:
        return jsonify({"error": "missing_params"}), 400
    article = Article.query.get(article_id)
    if not article:
        return jsonify({"error": "not_found"}), 404
    reserved = compute_reserved_for_article(article_id)
    if qty > article.quantity - reserved:
        return jsonify({"error": "stock_insufficient"}), 409
    expires = now_utc() + timedelta(seconds=RESERVATION_TTL_SECONDS)
    r = Reservation(cart_id=cart_id, article_id=article_id, qty=qty, active=1, expires_at=expires)
    db.session.add(r)
    db.session.commit()
    return jsonify({"result": "reserved", "reservation_id": r.id}), 201

@app.route("/cart/<cart_id>", methods=["GET"])
def get_cart(cart_id):
    res = Reservation.query.filter(
        Reservation.cart_id == str(cart_id),
        Reservation.active == 1,
        Reservation.expires_at > now_utc()
    ).all()
    items = [{
        "reservation_id": r.id,
        "article_id": r.article_id,
        "name": r.article.name,
        "price": r.article.price,
        "qty": r.qty
    } for r in res]
    return jsonify({"items": items})

@app.route("/cart/remove/<int:res_id>", methods=["DELETE", "OPTIONS"])
def remove_item(res_id):
    r = Reservation.query.get(res_id)
    if not r:
        return jsonify({"error": "not_found"}), 404
    r.active = 0
    db.session.commit()
    return jsonify({"result": "released"}), 200

@app.route("/checkout/<cart_id>", methods=["POST"])
def checkout(cart_id):
    res = Reservation.query.filter(
        Reservation.cart_id == str(cart_id),
        Reservation.active == 1
    ).all()
    if not res:
        return jsonify({"error": "empty"}), 400
    for r in res:
        art = Article.query.get(r.article_id)
        art.quantity -= r.qty
        r.active = 0
    db.session.commit()
    return jsonify({"result": "checkout_success"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
