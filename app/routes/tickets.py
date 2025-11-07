# app/routes/tickets.py

# Cette page est inaccessible sans être connecté: @login_required

# imports
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort, send_file, jsonify
from flask_login import login_required, current_user
from bson.objectid import ObjectId
from datetime import datetime, timedelta, timezone
from io import BytesIO                     # <<< nécessaire pour /qrcode.png
import os, json, qrcode 
import stripe as s                 # Stripe pour vérifier le PaymentIntent côté serveur
from app.extensions import csrf

from app.mqtt import mqtt_manager   # MQTT


bp = Blueprint("tickets", __name__, url_prefix="/tickets")

######### ------------------ Utilitaires  ----------------#########
VALID_TYPES = {"single", "day", "week", "month"}
ALIASES = {
    "horaires": "single", 
    "horaire": "single",
    "jour": "day",
    "semaine": "week",
    "weekly": "week",
    "mois": "month", 
    "mensuel": "month", 
    "monthly": "month",
}

def normalize_type(raw: str) -> str:
    t = (raw or "").strip().lower()
    t = ALIASES.get(t, t)
    return t if t in VALID_TYPES else "single"

def compute_expires(ttype: str, start: datetime | None = None) -> datetime:
    """Retourne l'heure d'expiration en fonction du type de ticket."""
    TICKET_TYPES = {
        # (label, durée de validité)
        "single": ("Horaires", timedelta(hours=2)),
        "day":    ("Jour",      timedelta(days=1)),
        "week":   ("Semaine",   timedelta(weeks=1)),
        "month":  ("Mois",      timedelta(days=30)),
    }

    ttype = normalize_type(ttype)
    start = start or datetime.now(timezone.utc)  # évite None et garantit un datetime "aware"
    _, duration = TICKET_TYPES.get(ttype, ("Par défaut", timedelta(days=1)))
    return start + duration

def _price_cents_for_type(ttype: str) -> int:
    """Prix en centimes: il doit matcher PRICES côté front (paiements.js)."""
    price = {
        "single": 150,    # 1,50 €
        "day":    500,    # 5,00 €
        "week":  1500,    # 15,00 €
        "month": 4500,    # 45,00 €
    }
    return price.get((ttype or "single").lower(), 150)

def _insert_tickets(db, user_id: str, ttype: str, qty: int) -> list[str]:
    """
    Crée 'qty' tickets pour l'utilisateur, génère les QR et publie MQTT.
    Retourne la liste des IDs créés.
    """
    now = datetime.now(timezone.utc)
    qr_dir = os.path.join(current_app.static_folder, "qrcodes")
    os.makedirs(qr_dir, exist_ok=True)

    mm = mqtt_manager()  # peut être None si MQTT désactivé
    created_ids: list[str] = []

    for _ in range(max(1, int(qty or 1))):
        doc = {
            "user_id": user_id,
            "type": normalize_type(ttype),
            "status": "active",          # acheté mais pas encore "validé"
            "purchased_at": now,
            "validated_at": None,
            "validation_status": None,   # None | "pending" | "validated"
            "expires_at": None,          # fixé plus tard lors de la validation
        }
        res = db.tickets.insert_one(doc)
        ticket_id = str(res.inserted_id)
        created_ids.append(ticket_id)

        payload = {
            "ticket_id": ticket_id,
            "user_id": user_id,
            "type": doc["type"],
            "issued_at": now.isoformat().replace("+00:00", "Z"),
        }

        img = qrcode.make(json.dumps(payload, separators=(",", ":")))
        img_path = os.path.join(qr_dir, f"{ticket_id}.png")
        img.save(img_path)

        db.tickets.update_one(
            {"_id": res.inserted_id},
            {"$set": {"qr_path": f"/static/qrcodes/{ticket_id}.png", "qr_payload": payload}}
        )

        if mm:
            try:
                mm.publish_event(
                    user_id=user_id,
                    ticket_id=ticket_id,
                    payload={"event": "ticket_bought", "type": doc["type"], "ts": now.isoformat().replace("+00:00","Z")},
                    qos=1, retain=False
                )
            except Exception as e:
                current_app.logger.warning(f"[MQTT] publish ticket_bought ignoré: {e}")

    return created_ids

#############################################
#               Routes                      #
#############################################

##### -------------------- LISTE --------------------     ##############
@bp.get("/")
@login_required
def liste():
    db = current_app.db
    user_id = str(current_user.id)           #  unifie le type
    now = datetime.now(timezone.utc)

    # Ne marquer expiré QUE si une date d'expiration existe et est dépassée
    db.tickets.update_many(
        {"user_id": user_id, "expires_at": {"$ne": None, "$lt": now}, "status": {"$ne": "expired"}},
        {"$set": {"status": "expired", "expired_at": now, "validation_status": None}}
    )

    rows = list(db.tickets.find({"user_id": user_id}).sort("_id", -1))
    return render_template("tickets/liste_ticket.html", tickets=rows)

# -------------------- DÉTAIL du ticket --------------------
@bp.get("/<ticket_id>")
@login_required
def affichage(ticket_id):
    db = current_app.db
    t = db.tickets.find_one({"_id": ObjectId(ticket_id), "user_id": str(current_user.id)})
    if not t:
        abort(404)

    # normalise: si Mongo te renvoie des datetimes naïves, on les marque UTC
    for k in ("purchased_at", "validated_at", "expires_at"):
        if t.get(k) and t[k].tzinfo is None:
            t[k] = t[k].replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    ## marque expiré si l'échéance est passée, peu importe l'ancien statut
    if t.get("expires_at") and t["expires_at"] <= now and t.get("status") != "expired":
        db.tickets.update_one(
            {"_id": t["_id"]},
            {"$set": {
                "status": "expired", 
                "expired_at": now, 
                "validation_status": None
                }
            }
        )
        t["status"] = "expired"
        t["expired_at"] = now
        t["validation_status"] = None

    # On passe l'heure serveur au template pour éviter les décalages client
    return render_template("tickets/affichage.html", t=t, server_now=now)

# -------------------- ACHAT sans CB --------------------
@bp.get("/buy")
@login_required
def buy():
    return render_template("tickets/buy.html")

@bp.post("/buy")
@login_required
def buy_post():
    db = current_app.db
    ttype = normalize_type(request.form.get("type"))
    qty = int(request.form.get("qty", 1))

    #now = datetime.now(timezone.utc)
    user_id = str(current_user.id)           #  unifie le type
    
    _insert_tickets(db, user_id, ttype, qty)

    flash(f"Achat OK : {qty} ticket(s) {ttype} (Horaire).", "success")
    return redirect(url_for("dashboard.index"))

# -------------------- Finalisation après paiement Stripe --------------------

@csrf.exempt 
@bp.post("/api/after-payment")
@login_required
def api_after_payment():
    """
    Appelé par le front après confirmCardPayment OK.
    Vérifie le PaymentIntent auprès de Stripe, contrôle le montant, crée les tickets.
    JSON attendu: { pi_id: str, type: str, qty: int }
    """
    data = request.get_json(force=True, silent=True) or {}
    pi_id = (data.get("pi_id") or "").strip()
    ttype = normalize_type(data.get("type"))
    try:
        qty = max(1, int(data.get("qty") or 1))
    except Exception:
        return jsonify({"error": "qty invalide"}), 400

    if not pi_id.startswith("pi_"):
        return jsonify({"error": "pi_id manquant ou invalide"}), 400

    # Init Stripe
    s.api_key = current_app.config.get("STRIPE_SECRET_KEY")
    if not s.api_key:
        return jsonify({"error": "Clé Stripe serveur absente"}), 500

    # Vérifie le PaymentIntent auprès de Stripe
    try:
        pi = s.PaymentIntent.retrieve(pi_id)
    except Exception as e:
        current_app.logger.error(f"[Stripe] retrieve PI failed: {e}")
        return jsonify({"error": "Impossible de retrouver le paiement Stripe"}), 400

    if getattr(pi, "status", None) != "succeeded":
        return jsonify({"error": "Le paiement n'est pas confirmé côté Stripe"}), 400

    # Vérifie le montant attendu
    prix = {"single": 150, "day": 500, "week": 1500, "month": 4500}.get(ttype, 150)
    expected = prix * qty
    if int(getattr(pi, "amount", 0) or 0) != expected or (pi.currency or "").lower() != "eur":
        return jsonify({"error": "Montant inattendu"}), 400

    # Crée les tickets
    ids = _insert_tickets(current_app.db, str(current_user.id), ttype, qty)
    return jsonify({"ok": True, "ticket_ids": ids}), 201


# -------------------- QR dynamique --------------------
@bp.get("/<ticket_id>/qrcode.png")
@login_required
def qrcode_png(ticket_id):
    db = current_app.db
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        abort(404)

    t = db.tickets.find_one({"_id": oid, "user_id": str(current_user.id)})
    if not t:
        abort(404)

    img = qrcode.make(str(t["_id"]))         # payload minimal
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# -------------------- VALIDATION du ticket (démarrage de la decompte du temps) --------------------
@bp.post("/validate/<ticket_id>/start")
@login_required
def validate_start(ticket_id):
    db = current_app.db
    t = db.tickets.find_one({"_id": ObjectId(ticket_id), "user_id": str(current_user.id)})
    if not t:
        abort(404)

    now = datetime.now(timezone.utc)

    # Si déjà expiré (cas où un ticket est expiré existait et a été dépassée)
    if t.get("expires_at") and t["expires_at"] <= now:
        db.tickets.update_one({"_id": t["_id"]}, {"$set": {"status": "expired", "validation_status": None}})
        flash("Ticket expiré.", "warning")
        return redirect(url_for("dashboard.index"))

    # Si déjà en attente ou déjà validé, on n'empile pas.
    if t.get("validation_status") in ("pending", "validated"):
        flash("Validation déjà engagée." if t["validation_status"] == "pending" else "Ticket déjà validé.", "info")
        return redirect(url_for("tickets.affichage", ticket_id=t["_id"]))


    # Met en attente de confirmation
    db.tickets.update_one(
        {"_id": t["_id"]},
        {"$set": {
            "status": "active",
            "validation_status": "pending",          # en attente de confirmation
            "validated_at": None,
            "expires_at": None,
            "confirmation_requested_at": now         # informatif
        }}
    )
    #flash("Validation en cours…", "info")

    # Event MQTT (optionnel)
    mm = mqtt_manager()
    if mm:
        try:
            mm.publish_event(
                user_id=str(current_user.id),
                ticket_id=str(t["_id"]),
                payload={"event": "validation_started", "ts": now.isoformat().replace("+00:00","Z")},
                qos=1, retain=False
            )
        except Exception as e:
            current_app.logger.warning(f"[MQTT] publish validation_started ignoré: {e}")

    flash("En attente de confirmation...", "info")
    #return redirect(url_for("dashboard.index"))
    return redirect(url_for("tickets.affichage", ticket_id=t["_id"]))


# -------------------- confirmation du ticket validé --------------------
@bp.post("/validate/<ticket_id>/confirm")
@login_required
def validate_confirm(ticket_id):
    db = current_app.db
    t = db.tickets.find_one({"_id": ObjectId(ticket_id), "user_id": str(current_user.id)})
    if not t:
        abort(404)

    now = datetime.now(timezone.utc)

    # Si c'est déjà validé et non expiré, inutile de relancer
    if t.get("status") == "validated" and t.get("expires_at") and t["expires_at"] > now:
        flash("Validation déjà en cours.", "info")
        return redirect(url_for("tickets.affichage", ticket_id=t["_id"]))

    # Au moment de confirmer, on fixe l'expiration à partir de 'now'
    expires = compute_expires(normalize_type(t.get("type")), now)
    
    db.tickets.update_one(
        {"_id": t["_id"]},
        {"$set": {
            "status": "validated",
            "validation_status": "validated",
            "validated_at": now,          # maintenant
            "expires_at": expires         # calculé depuis maintenant
        }}
    )
    flash("Ticket validé.", "success")

    # Evenement MQTT 
    mm = mqtt_manager()
    if mm:
        try:
            mm.publish_event(
                user_id=str(current_user.id),
                ticket_id=str(t["_id"]),
                payload={
                    "event": "ticket_validated",
                    "type": t.get("type"),
                    "validated_at": now.isoformat().replace("+00:00","Z"),
                    "expires_at": expires.isoformat().replace("+00:00","Z")
                },
                qos=1, retain=False
            )
        except Exception as e:
            current_app.logger.warning(f"[MQTT] publish ticket_validated ignoré: {e}")

    flash("Validation démarrée. Le décompte a commencé.", "success")
    return redirect(url_for("tickets.affichage", ticket_id=t["_id"]))
    #return redirect(url_for("dashboard.index"))

# -------------------- SUPPRESSION du ticket (seulement expiré) --------------------
@bp.post("/<ticket_id>/delete")
@login_required
def delete(ticket_id):
    db = current_app.db
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        abort(404)

    t = db.tickets.find_one({"_id": oid, "user_id": str(current_user.id)})
    if not t:
        abort(404)

    now = datetime.now(timezone.utc)

    # Si une expiration existe et qu'elle est dépassée mais que le statut n'a pas été mis à jour,
    # on le passe en 'expired' pour permettre la suppression.
    
    if t.get("expires_at"):
        exp = t["expires_at"]
        if getattr(exp, "tzinfo", None) is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now and t.get("status") != "expired":
            db.tickets.update_one(
                {"_id": oid},
                {"$set": {"status": "expired", "expired_at": now, "validation_status": None}}
            )
            t["status"] = "expired"
            
    if t.get("status") != "expired":
        flash("Ce ticket n'est pas encore expiré, impossible de le supprimer.", "warning")
        return redirect(url_for("tickets.affichage", ticket_id=t["_id"]))

    # Event MQTT (avant suppression
    mm = mqtt_manager()
    if mm:
        try:
            mm.publish_event(
                user_id=str(current_user.id),
                ticket_id=str(t["_id"]),
                payload={"event": "ticket_deleted", "ts": now.isoformat().replace("+00:00","Z")},
                qos=1, retain=False
            )
        except Exception as e:
            current_app.logger.warning(f"[MQTT] publish ticket_deleted ignoré: {e}")

    db.tickets.delete_one({"_id": oid, "user_id": str(current_user.id)})
    flash("Ticket supprimé.", "success")
    return redirect(url_for("tickets.liste"))
