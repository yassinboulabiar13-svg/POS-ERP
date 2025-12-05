# -*- coding: utf-8 -*-
"""
Created on Fri Dec  5 11:12:24 2025

@author: Acer
"""

"""
payments-backend/app.py

Backend pour "Paiements & Encaissements" (Processus 4).
- SQLite via SQLAlchemy
- Endpoints: initier, authoriser (simulé), confirmer, receipts, list payments, ERP sync
- DB file: pos_payments.db
- Business rules: manager approval threshold, simple card/mobile validation, idempotence via client_payment_id
"""

import os
import threading
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pos_payments.db")
MANAGER_APPROVAL_THRESHOLD = float(os.environ.get("MANAGER_APPROVAL_THRESHOLD", "1000.0"))  # ex: 1000 DT
ERP_RETRY_LIMIT = int(os.environ.get("ERP_RETRY_LIMIT", "3"))

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# -----------------------
# Models
# -----------------------
class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    client_payment_id = db.Column(db.String(128), unique=True, nullable=False)  # id fourni côté client pour idempotence
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="TND")
    mode = db.Column(db.String(32), nullable=False)  # cash, card, mobile, cheque, voucher
    status = db.Column(db.String(32), nullable=False, default="initiated")  # initiated, authorized, confirmed, failed
    detail = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    manager_approved = db.Column(db.Integer, nullable=False, default=0)  # 1 if manager approval granted
    erp_synced = db.Column(db.Integer, nullable=False, default=0)  # 1 if synced to ERP
    erp_retry = db.Column(db.Integer, nullable=False, default=0)


class PaymentAttempt(db.Model):
    __tablename__ = "payment_attempts"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    provider_response = db.Column(db.String(512), nullable=True)
    success = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    payment = db.relationship("Payment", backref="attempts")


class Receipt(db.Model):
    __tablename__ = "receipts"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    receipt_number = db.Column(db.String(64), nullable=False, unique=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    payment = db.relationship("Payment", backref="receipt")


class ERPQueue(db.Model):
    __tablename__ = "erp_queue"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_try_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    payment = db.relationship("Payment", backref="erp_queue")


# -----------------------
# Helpers
# -----------------------
def now_utc():
    return datetime.now(timezone.utc)


def generate_receipt_number(payment: Payment):
    ts = int(payment.created_at.timestamp())
    return f"RCPT-{payment.id}-{ts}"


def simple_card_check(card_info: dict, amount: float):
    """
    Simulate card/mobile authorization.
    Business rules (simple simulation):
     - card_info must contain 'number' (string of digits), 'expiry' (MM/YY), 'cvv' (3 digits)
     - simulated acceptance: if last digit of card number is even -> accept; odd -> refuse
     - if amount > MANAGER_APPROVAL_THRESHOLD and manager_approved is not set -> require approval (handled outside)
    """
    number = card_info.get("number", "")
    cvv = str(card_info.get("cvv", ""))
    expiry = card_info.get("expiry", "")
    if not number.isdigit() or len(number) < 12 or len(number) > 19:
        return False, "invalid_card_number"
    if not cvv.isdigit() or not (3 <= len(cvv) <= 4):
        return False, "invalid_cvv"
    if not expiry or "/" not in expiry:
        return False, "invalid_expiry"
    # simple deterministic decision: last digit even => accepted
    try:
        last = int(number[-1])
        if last % 2 == 0:
            return True, "authorized"
        else:
            return False, "bank_decline"
    except Exception:
        return False, "processing_error"


# -----------------------
# Init DB
# -----------------------
with app.app_context():
    db.create_all()


# -----------------------
# Endpoints
# -----------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": now_utc().isoformat()}), 200


@app.route("/payments/initiate", methods=["POST"])
def initiate_payment():
    """
    Initiate a payment request (idempotent via client_payment_id)
    Body JSON:
    {
        "client_payment_id": "cart-123-pay-1",
        "amount": 120.0,
        "currency": "TND",
        "mode": "card"|"mobile"|"cash"|"cheque"|"voucher",
        "metadata": {...},   # optional, e.g. card info for immediate authorization
        "manager_approved": 0|1 (optional)
    }
    """
    data = request.get_json() or {}
    client_payment_id = data.get("client_payment_id")
    amount = float(data.get("amount", 0))
    mode = data.get("mode")
    currency = data.get("currency", "TND")
    manager_approved = int(data.get("manager_approved", 0))

    if not client_payment_id or amount <= 0 or not mode:
        return jsonify({"error": "client_payment_id, amount>0 and mode required"}), 400

    # idempotence: return existing if present
    existing = Payment.query.filter_by(client_payment_id=client_payment_id).first()
    if existing:
        return jsonify({"result": "exists", "payment_id": existing.id, "status": existing.status}), 200

    # create payment
    p = Payment(client_payment_id=client_payment_id, amount=amount, currency=currency, mode=mode,
                status="initiated", manager_approved=1 if manager_approved else 0, created_at=now_utc())
    db.session.add(p)
    db.session.commit()
    return jsonify({"result": "initiated", "payment_id": p.id}), 201


@app.route("/payments/authorize/<int:payment_id>", methods=["POST"])
def authorize_payment(payment_id):
    """
    Authorize a payment (for electronic modes). Simulates call to payment provider.
    Body JSON:
      - for card/mobile: { "card": {"number":"...","expiry":"MM/YY","cvv":"..." } }
    Rules:
      - If amount > MANAGER_APPROVAL_THRESHOLD and manager_approved=0 => require manager approval
      - Simulated acceptance logic in simple_card_check()
    """
    data = request.get_json() or {}
    p = Payment.query.get_or_404(payment_id)

    if p.mode not in ("card", "mobile"):
        return jsonify({"error": "authorization_not_required_for_mode", "mode": p.mode}), 400

    if p.status not in ("initiated", "failed"):
        return jsonify({"error": "invalid_state_for_authorization", "status": p.status}), 400

    if p.amount > MANAGER_APPROVAL_THRESHOLD and p.manager_approved == 0:
        return jsonify({"error": "manager_approval_required", "threshold": MANAGER_APPROVAL_THRESHOLD}), 403

    card = data.get("card", {})
    ok, reason = simple_card_check(card, p.amount)
    attempt = PaymentAttempt(payment_id=p.id, provider_response=reason, success=1 if ok else 0, created_at=now_utc())
    db.session.add(attempt)
    if ok:
        p.status = "authorized"
        p.detail = f"provider:{reason}"
        db.session.commit()
        return jsonify({"result": "authorized", "payment_id": p.id}), 200
    else:
        p.status = "failed"
        p.detail = f"provider:{reason}"
        db.session.commit()
        return jsonify({"result": "declined", "reason": reason}), 402


@app.route("/payments/confirm/<int:payment_id>", methods=["POST"])
def confirm_payment(payment_id):
    """
    Confirm / capture the payment (finalize).
    For cash/cheque/voucher, this records the payment directly.
    For card/mobile, it requires status 'authorized' (unless mode supports capture on confirm).
    Generates a receipt and enqueue ERP sync.
    """
    p = Payment.query.get_or_404(payment_id)
    if p.status == "confirmed":
        return jsonify({"result": "already_confirmed", "payment_id": p.id}), 200

    if p.mode in ("card", "mobile"):
        if p.status != "authorized":
            return jsonify({"error": "not_authorized"}, 400)

    # record confirmation
    try:
        p.status = "confirmed"
        p.updated_at = now_utc()
        db.session.add(p)
        # create receipt
        rn = generate_receipt_number(p)
        content = f"Receipt {rn}\nPayment ID: {p.id}\nAmount: {p.amount} {p.currency}\nMode: {p.mode}\nDate: {p.updated_at.isoformat()}"
        r = Receipt(payment_id=p.id, receipt_number=rn, content=content, created_at=now_utc())
        db.session.add(r)
        # enqueue ERP sync
        q = ERPQueue(payment_id=p.id, attempts=0, created_at=now_utc())
        db.session.add(q)
        db.session.commit()
        return jsonify({"result": "confirmed", "payment_id": p.id, "receipt_number": rn}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "confirm_failed", "detail": str(e)}), 500


@app.route("/payments/<int:payment_id>", methods=["GET"])
def get_payment(payment_id):
    p = Payment.query.get_or_404(payment_id)
    receipt = None
    if p.receipt:
        receipt = {"receipt_number": p.receipt[0].receipt_number, "content": p.receipt[0].content}
    return jsonify({
        "id": p.id,
        "client_payment_id": p.client_payment_id,
        "amount": p.amount,
        "currency": p.currency,
        "mode": p.mode,
        "status": p.status,
        "detail": p.detail,
        "manager_approved": bool(p.manager_approved),
        "erp_synced": bool(p.erp_synced),
        "receipt": receipt,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None
    })


@app.route("/payments", methods=["GET"])
def list_payments():
    limit = int(request.args.get("limit", 100))
    q = Payment.query.order_by(Payment.created_at.desc()).limit(limit).all()
    out = []
    for p in q:
        out.append({
            "id": p.id,
            "client_payment_id": p.client_payment_id,
            "amount": p.amount,
            "mode": p.mode,
            "status": p.status,
            "erp_synced": bool(p.erp_synced),
            "created_at": p.created_at.isoformat()
        })
    return jsonify(out)


@app.route("/receipts/<string:receipt_number>", methods=["GET"])
def get_receipt(receipt_number):
    r = Receipt.query.filter_by(receipt_number=receipt_number).first_or_404()
    return jsonify({
        "receipt_number": r.receipt_number,
        "payment_id": r.payment_id,
        "content": r.content,
        "created_at": r.created_at.isoformat()
    })


# -----------------------
# Simulated ERP sync background worker
# -----------------------
def erp_sync_worker(interval=10):
    """
    Worker that tries to sync confirmed payments in ERPQueue.
    Simulation: random acceptance or simple deterministic acceptance.
    If sync succeeds -> mark payment.erp_synced = 1, delete queue entry.
    If fails -> increment attempts and schedule retry; after ERP_RETRY_LIMIT -> leave for admin.
    """
    while True:
        try:
            with app.app_context():
                pending = ERPQueue.query.order_by(ERPQueue.created_at).all()
                for q in pending:
                    p = q.payment
                    # only sync confirmed payments
                    if p.status != "confirmed":
                        # remove orphan queue entries
                        db.session.delete(q)
                        db.session.commit()
                        continue

                    # simulate sync success rule: accept if payment_id % 2 == 0 (deterministic)
                    success = (p.id % 2 == 0)
                    if success:
                        p.erp_synced = 1
                        p.erp_retry = q.attempts + 1
                        db.session.delete(q)
                        db.session.commit()
                    else:
                        q.attempts += 1
                        q.next_try_at = now_utc()
                        db.session.commit()
                        if q.attempts >= ERP_RETRY_LIMIT:
                            # stop retrying automatically, admin will handle
                            print(f"ERP sync failed for payment {p.id} after {q.attempts} attempts")
                # small pause
        except Exception as e:
            print("erp_sync_worker error:", e)
        time.sleep(interval)


erp_thread = threading.Thread(target=erp_sync_worker, daemon=True)
erp_thread.start()


@app.route("/admin/erp_queue", methods=["GET"])
def admin_list_erp_queue():
    q = ERPQueue.query.all()
    out = []
    for e in q:
        out.append({"id": e.id, "payment_id": e.payment_id, "attempts": e.attempts, "created_at": e.created_at.isoformat()})
    return jsonify(out)


@app.route("/admin/force_sync/<int:payment_id>", methods=["POST"])
def admin_force_sync(payment_id):
    """
    Admin endpoint to force sync a payment (simulate ERP manual sync).
    """
    p = Payment.query.get_or_404(payment_id)
    # simulate immediate success
    p.erp_synced = 1
    p.erp_retry = p.erp_retry + 1
    # remove any queue entries
    ERPQueue.query.filter_by(payment_id=payment_id).delete()
    db.session.commit()
    return jsonify({"result": "forced_sync", "payment_id": payment_id}), 200


# -----------------------
# Manager approval endpoint (for payments above threshold)
# -----------------------
@app.route("/admin/approve/<int:payment_id>", methods=["POST"])
def admin_approve(payment_id):
    p = Payment.query.get_or_404(payment_id)
    p.manager_approved = 1
    db.session.commit()
    return jsonify({"result": "approved", "payment_id": payment_id}), 200


# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=5003, debug=debug_mode)
