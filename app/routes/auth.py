# app/routes/auth.py

# Les vues d'authentification. On y manipule :
# - la DB (création et recherche d'utilisateur)
# - les sessions Flask-Login via login_user() / logout_user()

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.forms.auth_forms import RegisterForm, LoginForm
from app.models.user import MongoUser
from datetime import datetime
from urllib.parse import urlparse, urljoin

bp = Blueprint("auth", __name__)

# -- permet d'éviter les redirections externes (pour la securité)
def is_safe_url(target: str) -> bool:
    """
    On n'autorise que des redirections vers NOTRE domaine.
    Ça évite qu'un lien malicieux t'envoie vers ailleurs.
    """
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc
    )

def _clean_next(value: str | None) -> str | None:
    """Évite les cas 'None', 'null', 'undefined' -> None"""
    if not value:
        return None
    if value.strip().lower() in {"none", "null", "undefined"}:
        return None
    return value

# ---------------------------
#   INSCRIPTION /register
# ---------------------------
@bp.route("/register", methods=["GET", "POST"])
def register():
    # Si déjà connectée, se diriger vers dashboard.
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        db = current_app.db

        # On récupère gentillement les champs du formulaire
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        # Verification côté serveur (même si le HTML a "required")
        if not name or not email or not password:
            flash("Merci de remplir tous les champs.", "warning")
            return render_template("auth/register.html"), 400

        # Email unique, toujours en lowercase
        if db.users.find_one({"email": email}):
            flash("Cet email est déjà utilisé.", "warning")
            return render_template("auth/register.html"), 409

        # JAMAIS stocker le mot de passe en clair : on hache
        doc = {
            "name": name,
            "email": email,
            "password_hash": generate_password_hash(password),
            "created_at": datetime.utcnow(),
        }
        res = db.users.insert_one(doc)

        # On connecte directement l'utilisateur fraîchement créé
        login_user(MongoUser({**doc, "_id": res.inserted_id}), remember=True)
        flash("Bienvenue ! Votre compte a été créé.", "success")

        # Si on venait d'une page protégée, on y retourne
        next_url = _clean_next(request.form.get("next") or request.args.get("next"))
        return redirect(next_url) if is_safe_url(next_url) else redirect(url_for("dashboard.index"))

    # GET : juste afficher le formulaire
    return render_template("auth/register.html")


# ----------------------
#   CONNEXION /login
# ----------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    # Déjà connecté·e ? Direction le dashboard.
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        db = current_app.db

        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("Email et mot de passe sont requis.", "warning")
            return render_template("auth/login.html"), 400

        # On va chercher l'utilisateur
        user = db.users.find_one({"email": email})

        # Vérification du mot de passe (hash en base vs mot de passe saisi)
        if not user or not check_password_hash(user.get("password_hash", ""), password):
            flash("Identifiants invalides.", "danger")
            return render_template("auth/login.html"), 401

        # on ouvre la session
        login_user(MongoUser(user), remember=True)
        flash("Connexion réussie.", "success")

        # On respecte le "next" s'il est sûr ; sinon -> dashboard
        raw_next = request.form.get("next") or request.args.get("next")
        next_url = _clean_next(raw_next)
        return redirect(next_url) if is_safe_url(next_url) else redirect(url_for("dashboard.index"))

    # affiche le formulaire
    return render_template("auth/login.html")


# ------------------------
#   DÉCONNEXION /logout
# ------------------------
@bp.get("/logout")
def logout():
    # On ferme proprement la session si besoin
    if current_user.is_authenticated:
        logout_user()
        flash("Vous êtes déconnecté.", "info")
    # Retour à l'accueil (non protégé)
    return redirect(url_for("accueil.index"))