# app/routes/dashboard.py

# Toute la section dashboard est protégée : il faut être connecté.
# @login_required vérifie s'il y a un user dans la session,
# sinon redirige automatiquement vers auth.login (cf login_view).

from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
from bson.objectid import ObjectId


bp= Blueprint("dashboard", __name__, url_prefix="/dashboard")

def _norm_doc_dates(doc):
    """Force tzinfo=UTC sur les champs date d'un ticket si Mongo les renvoie naïfs."""
    for k in ("purchased_at", "validated_at", "expires_at", "expired_at"):
        if doc.get(k) and getattr(doc[k], "tzinfo", None) is None:
            doc[k] = doc[k].replace(tzinfo=timezone.utc)
    return doc

@bp.get("/")
@login_required
def index():
    db = current_app.db
    user_id = str(current_user.id)
    now = datetime.now(timezone.utc)

    # Marque comme expirés pour la sécurité : on ne touche qu'aux tickets qui ont une expiration dépassée coté BD
    db.tickets.update_many(
        {
            "user_id": user_id, 
            "expires_at": {"$ne": None, "$lt": now}, 
            "status": {"$ne": "expired"}
        },
        {"$set": {"status": "expired", "expired_at": now, "validation_status": None}}
    )

    # Récupération brute des tickets utilisateur et normalisation timezone
    tickets_= list(db.tickets.find({"user_id": user_id}))
    tickets = [_norm_doc_dates(t) for t in tickets_]  # normalise tout


    # --- NORMALISATION: on force UTC "aware" pour tous les champs datetime extraits de Mongo  afin d'eviter l'erreur TypeError cote python---
    """def to_aware_utc(dt):
        if isinstance(dt, datetime) and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

        for t in tickets:
            for k in ("purchased_at", "validated_at", "expires_at", "expired_at"):
                if t.get(k):
                    t[k] = to_aware_utc(t[k])
"""
    # Comptages
    n_total     = len(tickets)
    n_active    = sum(1 for t in tickets if t.get("status") == "active" and t.get("validation_status") is None)
    n_pending   = sum(1 for t in tickets if t.get("validation_status") == "pending")
    n_validated = sum(1 for t in tickets if t.get("status") == "validated" and (not t.get("expires_at") or t["expires_at"] >= now))
    n_expired   = sum(1 for t in tickets if t.get("status") == "expired")

    # Abonnements actifs = types (weekly/monthly/yearly ) qui sont non expirés
    abon_types = {"weekly", "monthly", "yearly"}
    abonnements_actifs = []
    for t in tickets:
        ttype = (t.get("type") or "").lower()
        if ttype in abon_types and t.get("status") != "expired":
            # si expiration existe, on vérifie qu'elle n'est pas dépassée
            if t.get("expires_at") and t["expires_at"] < now:
                continue
            abonnements_actifs.append(t)

    # Derniers tickets achetés (5 plus récents) normalisé pour l'affichage
    #derniers = list(db.tickets.find({"user_id": user_id}).sort("_id", -1).limit(5))
    derniers = [
        _norm_doc_dates(x)
        for x in db.tickets.find({"user_id": user_id}).sort("_id", -1).limit(5)
    ]

    return render_template(
        "dashboard/index.html",
        now=now,  # le fichier localtime.js l'affichera en heure locale 
        n_total=n_total,
        n_active=n_active,
        n_pending=n_pending,
        n_validated=n_validated,
        n_expired=n_expired,
        abonnements_actifs=abonnements_actifs,
        derniers=derniers,
    )