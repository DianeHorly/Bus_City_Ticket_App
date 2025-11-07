# app/paiements.py
# -*- coding: utf-8 -*-
"""
Blueprint 'payments' : endpoints Stripe
- /payments/config                  -> expose la clé publique (pk_*)
- /payments/create-payment-intent   -> crée un PaymentIntent pour Elements
- /payments/finalize                -> crée les tickets après paiement réussi
"""

#######------- BIBLIOTHEQUE NECESSAIRE -----------  #########
from flask import Blueprint, current_app, jsonify, request, url_for, render_template
from flask_login import login_required, current_user
import os
import stripe as s
from app.extensions import csrf
from datetime import datetime
from bson import ObjectId 

bp = Blueprint("payments", __name__, url_prefix="/payments")

# Barème côté serveur 
PRICES = {
    "single": 150, 
    "day": 500, 
    "week": 1500, 
    "month": 4500
}

# Pour exempter TOUT le blueprint des vérifications CSRF
csrf.exempt(bp)

def _setup_stripe_from_env():
    """
    Détermine les clés à partir de app.config puis .env (fallback).
    Ne lève pas de KeyError et logge l'état.
    """
    pub = current_app.config.get("STRIPE_PUBLISHABLE_KEY") or os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    sec = current_app.config.get("STRIPE_SECRET_KEY")      or os.getenv("STRIPE_SECRET_KEY", "")

    s.api_key = sec or None

    if pub.startswith("pk_"):
        current_app.logger.info("[Stripe] Publishable OK.")
    else:
        current_app.logger.warning("[Stripe] Publishable manquante/invalide.")

    if sec.startswith("sk_"):
        current_app.logger.info(f"[Stripe] Secret présent (prefix={sec[:7]}...).")
    else:
        current_app.logger.warning("[Stripe] Secret manquante/invalide.")

    return pub, sec


@bp.get("/config")
def config():
    """Renvoyer la clé publique pour Stripe.js"""
    pub, _ = _setup_stripe_from_env()
    if not pub.startswith("pk_"):
        # Le front saura afficher un message propre
        return jsonify({"error": "No publishable key"}), 500
    return jsonify({"publishableKey": pub})


@bp.get("/elements-test")
def elements_test():
    # réutilise ton helper, et passe la clé publique au template
    pub, _ = _setup_stripe_from_env()
    return render_template("payments/elements_test.html", publishable_key=pub)


@bp.post("/create-payment-intent")
@csrf.exempt
@login_required
def create_payment_intent():
    """
    Crée un PaymentIntent pour le flux 'Carte intégrée'.
    Body JSON attendu: { amount_cents: int, type: 'single|day|week|month', qty: int }
    le montant est recalculé côté serveur 
    """
    _setup_stripe_from_env()
    try:
        data = request.get_json(force=True, silent=True) or {}
        type = (data.get("type") or "single").strip()
        qty  = max(1, int(data.get("qty") or 1))

        # On recalcule le montant côté serveur (source de vérité)
        amount_cents = PRICES.get(type, PRICES["single"]) * qty
        currency = current_app.config.get("STRIPE_CURRENCY", "eur") or "eur"

        intent = s.PaymentIntent.create(
            amount=amount_cents,
            currency=currency,
            automatic_payment_methods={"enabled": True},
            metadata={
                "type": type,
                "qty": str(qty),
                "user_id": str(getattr(current_user, "id", "")),
            },
        )
        return jsonify({"client_secret": intent.client_secret})

    except Exception as e:
        # Quand la clé est invalide, Stripe renvoie une page HTML -> on renvoie JSON propre
        msg = str(e)
        current_app.logger.error(f"[Stripe] create PI failed: {msg}")
        status = 401 if "Invalid API Key" in msg else 400
        return jsonify({"error": msg}), status


@bp.post("/finalize")
@csrf.exempt
@login_required
def finalize_from_client():
    """
    Appelée par le front APRES confirmCardPayment() pour créer les tickets.
    Body JSON: { pi_id: str, type: str, qty: int }
    """
    _setup_stripe_from_env()

    try:
        data = request.get_json(force=True, silent=True) or {}
        pi_id = (data.get("pi_id") or "").strip()
        kind  = (data.get("type") or "single").strip()
        qty   = max(1, int(data.get("qty") or 1))

        if not pi_id:
            return jsonify({"error": "pi_id manquant"}), 400

        # On récupère le PI pour vérifier le statut et le montant payé
        pi = s.PaymentIntent.retrieve(pi_id)
        if pi.status != "succeeded":
            return jsonify({"error": "Paiement non confirmé"}), 400

        expected = PRICES.get(kind, PRICES["single"]) * qty
        amount_received = int(pi.get("amount_received") or 0)
        if amount_received < expected:
            return jsonify({"error": "Montant incohérent"}), 400

        # -- Création des tickets en DB --
        created_ids = []
        uid = getattr(current_user, "id", None)
        for _ in range(qty):
            doc = {
                "user_id": ObjectId(uid) if uid and ObjectId.is_valid(uid) else uid,
                "type": kind,
                "status": "paid",            # adapte au vocabulaire de ton app
                "source": "stripe",
                "pi_id": pi.id,
                "amount_cents": expected // qty,
                "created_at": datetime.utcnow(),
            }
            res = current_app.db.tickets.insert_one(doc)
            created_ids.append(str(res.inserted_id))

        return jsonify({"ok": True, "ticket_ids": created_ids})

    except Exception as e:
        msg = str(e)
        current_app.logger.error(f"[Stripe] finalize failed: {msg}")
        return jsonify({"error": msg}), 400

@bp.post("/create-checkout-session")
@csrf.exempt
def create_checkout_session():
    """Démarre une session Stripe Checkout (redirigée Stripe)"""
    _setup_stripe_from_env()
    try:
        data = request.get_json(force=True, silent=True) or {}
        amount_cents = max(50, int(data.get("amount_cents") or 100))
        qty = max(1, int(data.get("quantity") or 1))
        label = (data.get("label") or "Tickets Bus City").strip()

        base = request.host_url.rstrip("/")
        success_url = f"{base}{url_for('tickets.liste')}"
        cancel_url  = f"{base}{url_for('tickets.buy')}"

        session = s.checkout.Session.create(
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[{
                "price_data": {
                    "currency": os.getenv("STRIPE_CURRENCY", "eur"),
                    "unit_amount": amount_cents,
                    "product_data": {"name": label},
                },
                "quantity": qty,
            }],
            allow_promotion_codes=True,
            ui_mode="hosted",
        )
        return jsonify({"url": session.url})
    except Exception as e:
        msg = str(e)
        current_app.logger.error(f"[Stripe] checkout create failed: {msg}")
        status = 401 if "Invalid API Key" in msg else 400
        return jsonify({"error": msg}), status


