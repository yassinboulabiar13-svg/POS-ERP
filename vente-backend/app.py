# app.py - Vente en Magasin (Flask + SQLAlchemy)
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, request, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
import os
import random
import json

# Config
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///pos_vente.db')
TAX_RATE = Decimal(os.getenv('TAX_RATE', '0.19'))  # 19% by default
REMISE_MANAGER_THRESHOLD_PERCENT = Decimal(os.getenv('REMISE_MANAGER_THRESHOLD_PERCENT', '0.10'))  # 10%
REMISE_MANAGER_THRESHOLD_AMOUNT = Decimal(os.getenv('REMISE_MANAGER_THRESHOLD_AMOUNT', '50.0'))

app = Flask(__name__)
from flask_cors import CORS
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------- Models ----------
class Setting(db.Model):
    __tablename__ = 'settings'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(200), nullable=False)

class Article(db.Model):
    __tablename__ = 'articles'
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Numeric(12,2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    reserved = db.Column(db.Integer, nullable=False, default=0)
    vat = db.Column(db.Numeric(6,4), nullable=False, default=TAX_RATE)

class Cart(db.Model):
    __tablename__ = 'carts'
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(30), nullable=False, default='OPEN')  # OPEN, CHECKOUT_PENDING, PAID, CANCELLED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CartItem(db.Model):
    __tablename__ = 'cart_items'
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('carts.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('articles.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(12,2), nullable=False)
    discount = db.Column(db.Numeric(12,2), nullable=False, default=0.0)
    article = db.relationship('Article')

class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('carts.id'), nullable=False)
    total_ht = db.Column(db.Numeric(12,2), nullable=False)
    total_tax = db.Column(db.Numeric(12,2), nullable=False)
    total_ttc = db.Column(db.Numeric(12,2), nullable=False)
    payment_method = db.Column(db.String(50))
    payment_status = db.Column(db.String(30), default='PENDING')  # PENDING, AUTHORIZED, FAILED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(200), nullable=False)
    payload = db.Column(db.Text)
    actor = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------- Helpers ----------
def decimal(v):
    return Decimal(v).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def row_article(a: Article):
    return {
        "id": a.id,
        "sku": a.sku,
        "name": a.name,
        "price": float(a.price),
        "stock": a.stock,
        "reserved": a.reserved,
        "vat": float(a.vat)
    }

def log_event(event, payload=None, actor=None):
    db.session.add(AuditLog(event=event, payload=json.dumps(payload, default=str) if payload else None, actor=actor))
    db.session.commit()

def get_setting(key, default=None):
    s = Setting.query.get(key)
    return s.value if s else default

# ---------- Init / Seed ----------
def seed_defaults():
    # settings
    Setting.query.filter_by(key='TAX_RATE').delete()
    db.session.merge(Setting(key='TAX_RATE', value=str(TAX_RATE)))
    db.session.merge(Setting(key='REMISE_MANAGER_THRESHOLD_PERCENT', value=str(REMISE_MANAGER_THRESHOLD_PERCENT)))
    db.session.merge(Setting(key='REMISE_MANAGER_THRESHOLD_AMOUNT', value=str(REMISE_MANAGER_THRESHOLD_AMOUNT)))
    # sample articles
    if Article.query.count() == 0:
        sample = [
            {"sku":"SKU-001","name":"Chemise Bleu","price":Decimal('70.00'),"stock":10},
            {"sku":"SKU-002","name":"Jeans Slim","price":Decimal('120.00'),"stock":5},
            {"sku":"SKU-003","name":"Chaussures Sport","price":Decimal('200.00'),"stock":4},
            {"sku":"SKU-004","name":"Ceinture Cuir","price":Decimal('35.00'),"stock":15},
        ]
        for s in sample:
            db.session.add(Article(sku=s['sku'], name=s['name'], price=s['price'], stock=s['stock'], reserved=0, vat=TAX_RATE))
    db.session.commit()

# ---------- Endpoints ----------
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status":"ok","time":datetime.utcnow().isoformat()+"Z"})

@app.route('/articles', methods=['GET'])
def list_articles():
    articles = Article.query.all()
    return jsonify({"articles":[row_article(a) for a in articles]})

@app.route('/articles/<int:article_id>', methods=['GET'])
def get_article(article_id):
    a = Article.query.get(article_id)
    if not a:
        abort(404, "Article not found")
    return jsonify(row_article(a))

@app.route('/panier', methods=['POST'])
def create_cart():
    c = Cart(status='OPEN')
    db.session.add(c)
    db.session.commit()
    log_event("cart_created", {"cart_id": c.id}, actor=request.remote_addr)
    return jsonify({"cart_id": c.id}), 201

@app.route('/panier/<int:cart_id>', methods=['GET'])
def view_cart(cart_id):
    c = Cart.query.get(cart_id)
    if not c:
        abort(404, "Cart not found")
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    items_out = []
    for it in items:
        items_out.append({
            "id": it.id,
            "article_id": it.article_id,
            "sku": it.article.sku,
            "name": it.article.name,
            "qty": it.qty,
            "unit_price": float(it.unit_price),
            "discount": float(it.discount)
        })
    return jsonify({"cart": {"id": c.id, "status": c.status}, "items": items_out})

@app.route('/panier/<int:cart_id>/items', methods=['POST'])
def add_item(cart_id):
    data = request.get_json() or {}
    article_id = data.get("article_id")
    qty = int(data.get("qty", 1))
    discount = Decimal(str(data.get("discount", "0.0")))
    if not article_id or qty <= 0:
        abort(400, "article_id and qty>0 required")
    c = Cart.query.get(cart_id)
    if not c or c.status != 'OPEN':
        abort(400, "Cart not found or not open")
    a = Article.query.get(article_id)
    if not a:
        abort(404, "Article not found")
    available = a.stock - a.reserved
    if qty > available:
        abort(400, f"Stock insuffisant. disponible={available}")
    # check existing item
    existing = CartItem.query.filter_by(cart_id=cart_id, article_id=article_id).first()
    if existing:
        if existing.qty + qty > (a.stock - a.reserved):
            abort(400, "Stock insuffisant pour la quantité totale demandée")
        existing.qty = existing.qty + qty
        existing.discount = existing.discount + discount
    else:
        ci = CartItem(cart_id=cart_id, article_id=article_id, qty=qty, unit_price=a.price, discount=discount)
        db.session.add(ci)
    # reserve
    a.reserved = a.reserved + qty
    db.session.commit()
    log_event("item_added_to_cart", {"cart_id": cart_id, "article_id": article_id, "qty": qty}, actor=request.remote_addr)
    return jsonify({"message":"item_added"}), 201

@app.route('/panier/<int:cart_id>/items/<int:article_id>', methods=['DELETE'])
def remove_item(cart_id, article_id):
    c = Cart.query.get(cart_id)
    if not c:
        abort(404, "Cart not found")
    it = CartItem.query.filter_by(cart_id=cart_id, article_id=article_id).first()
    if not it:
        abort(404, "Item not in cart")
    # release reservation
    a = Article.query.get(article_id)
    if a:
        a.reserved = max(0, a.reserved - it.qty)
    db.session.delete(it)
    db.session.commit()
    log_event("item_removed", {"cart_id": cart_id, "article_id": article_id}, actor=request.remote_addr)
    return jsonify({"message":"item_removed"})

def compute_cart_totals(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    total_ht = Decimal('0.00')
    total_tax = Decimal('0.00')
    for it in items:
        line_net = (Decimal(it.unit_price) * it.qty) - Decimal(it.discount)
        if line_net < 0:
            line_net = Decimal('0.00')
        vat = Decimal(it.article.vat) if it.article.vat is not None else TAX_RATE
        tax = (line_net * vat)
        total_ht += line_net
        total_tax += tax
    return {
        "total_ht": decimal(total_ht),
        "total_tax": decimal(total_tax),
        "total_ttc": decimal(total_ht + total_tax)
    }

def simulate_payment_gateway(method, details, amount):
    try:
        amt = float(amount)
    except:
        amt = amount
    if amt > 10000:
        return {"authorized": False, "reason": "amount exceeds limit"}
    card_num = (details or {}).get("card_number","")
    if isinstance(card_num, str) and card_num.endswith("0"):
        return {"authorized": False, "reason": "bank_decline"}
    if random.random() < 0.95:
        return {"authorized": True, "auth_code": "AUTH"+str(random.randint(100000,999999))}
    else:
        return {"authorized": False, "reason": "network_error"}

@app.route('/panier/<int:cart_id>/checkout', methods=['POST'])
def checkout(cart_id):
    data = request.get_json() or {}
    payment_method = data.get("payment_method")
    payment_details = data.get("payment_details", {})
    actor = data.get("actor", request.remote_addr)
    if not payment_method:
        abort(400, "payment_method required")
    c = Cart.query.get(cart_id)
    if not c:
        abort(404, "Cart not found")
    if c.status != 'OPEN':
        abort(400, "Cart not open")
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    if not items:
        abort(400, "Cart empty")
    # final stock check
    for it in items:
        a = it.article
        if it.qty > a.stock:
            abort(400, f"Stock insuffisant pour article {a.id}")
    totals = compute_cart_totals(cart_id)
    # simulate electronic payment
    if payment_method in ('card','mobile'):
        auth = simulate_payment_gateway(payment_method, payment_details, totals['total_ttc'])
        if not auth['authorized']:
            # release reservations
            for it in items:
                it.article.reserved = max(0, it.article.reserved - it.qty)
            db.session.commit()
            log_event('payment_failed', {'cart_id':cart_id, 'reason': auth.get('reason')}, actor=actor)
            return jsonify({'payment': 'FAILED', 'reason': auth.get('reason')}), 402
        payment_status = 'AUTHORIZED'
    else:
        payment_status = 'PENDING' if payment_method == 'cheque' else 'AUTHORIZED'
    # create invoice
    inv = Invoice(cart_id=cart_id, total_ht=totals['total_ht'], total_tax=totals['total_tax'], total_ttc=totals['total_ttc'], payment_method=payment_method, payment_status=payment_status)
    db.session.add(inv)
    # decrement stock and clear reserved
    for it in items:
        a = it.article
        a.reserved = max(0, a.reserved - it.qty)
        a.stock = max(0, a.stock - it.qty)
    c.status = 'PAID' if payment_status == 'AUTHORIZED' else 'CHECKOUT_PENDING'
    db.session.commit()
    log_event('checkout_success', {'cart_id': cart_id, 'invoice_id': inv.id, 'totals': totals}, actor=actor)
    # attempt to "sync" to ERP (simulated)
    # in real system you'd push to ERP and handle nack/ack
    return jsonify({'invoice_id': inv.id, 'totals': totals, 'payment_status': payment_status}), 201

@app.route('/factures', methods=['GET'])
def list_invoices():
    invs = Invoice.query.order_by(Invoice.created_at.desc()).all()
    out = []
    for i in invs:
        out.append({
            "id": i.id,
            "cart_id": i.cart_id,
            "total_ht": float(i.total_ht),
            "total_tax": float(i.total_tax),
            "total_ttc": float(i.total_ttc),
            "payment_method": i.payment_method,
            "payment_status": i.payment_status,
            "created_at": i.created_at.isoformat()
        })
    return jsonify({"invoices": out})

@app.route('/factures/<int:invoice_id>', methods=['GET'])
def get_invoice(invoice_id):
    i = Invoice.query.get(invoice_id)
    if not i:
        abort(404, "Invoice not found")
    items = CartItem.query.filter_by(cart_id=i.cart_id).all()
    items_out = []
    for it in items:
        items_out.append({
            "sku": it.article.sku,
            "name": it.article.name,
            "qty": it.qty,
            "unit_price": float(it.unit_price),
            "discount": float(it.discount)
        })
    return jsonify({"invoice": {
        "id": i.id,
        "cart_id": i.cart_id,
        "total_ht": float(i.total_ht),
        "total_tax": float(i.total_tax),
        "total_ttc": float(i.total_ttc),
        "payment_method": i.payment_method,
        "payment_status": i.payment_status,
        "created_at": i.created_at.isoformat()
    }, "items": items_out})

# Admin reset (dev only)
@app.route('/admin/reset-db', methods=['POST'])
def reset_db():
    if os.environ.get('ALLOW_DB_RESET','0') != '1':
        abort(403, "DB reset disabled")
    db.drop_all()
    db.create_all()
    seed_defaults()
    return jsonify({"message":"db_reset"}), 200

# ---------- Run ----------
if __name__ == '__main__':
    # ensure DB and seed inside application context to avoid context errors
    with app.app_context():
        db.create_all()
        seed_defaults()
    app.run(host='127.0.0.1', port=5001, debug=True)
