# app/routes/accueil.py
from flask import Blueprint, render_template
#from app import csrf

bp = Blueprint("accueil", __name__)

@bp.get("/")
def index():
    # Page d’accueil: tout le monde peut y accéder, connecté ou non
    return render_template("accueil.html")

@bp.get("/healthz")
def healthz():
    # Pour Docker/K8s: simple check
    return {"status": "ok"}, 200


