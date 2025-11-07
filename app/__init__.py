# app/__init__.py

# Crée l'application Flask, attache la DB, configure Flask-Login (sessions),
# enregistre les blueprints (routes).

from flask import Flask, render_template, current_app
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from app.extensions import csrf, login_manager
from app.mqtt import MqttManager  # pour le scanne des tickets MQTT
import os
from config import DevelopmentConfig
#from flask_login import LoginManager
from app.dataBase import init_db, ensure_minimum_indexes
from app.routes import register_blueprints
from datetime import timezone  # pour garder le fuseau horaire peut importe où on se trouve

# --- Auth / sessions ---
#from flask_login import LoginManager
from bson.objectid import ObjectId
from app.models.user import MongoUser
from dotenv import load_dotenv # type: ignore


#csrf = CSRFProtect()
#login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    load_dotenv()
    app.config.from_object(DevelopmentConfig)

    # ====== RÉCUPÉRER LES CLÉS STRIPE DEPUIS .env ===================== #
    # On écrit explicitement dans app.config pour que le blueprint paiements
    # puisse les lire de manière fiable.
    app.config["STRIPE_PUBLISHABLE_KEY"] = os.getenv(
        "STRIPE_PUBLISHABLE_KEY",
        app.config.get("STRIPE_PUBLISHABLE_KEY", "")
    )  
    app.config["STRIPE_SECRET_KEY"] = os.getenv(
        "STRIPE_SECRET_KEY",
        app.config.get("STRIPE_SECRET_KEY", "")
    )  

    # Petit log utile
    if app.config["STRIPE_PUBLISHABLE_KEY"].startswith("pk_"):
        app.logger.info("[Stripe] Publishable OK.")
    else:
        app.logger.warning("[Stripe] Publishable manquante/invalide.")
    if app.config["STRIPE_SECRET_KEY"].startswith("sk_"):
        app.logger.info("[Stripe] Secret présent.")
    else:
        app.logger.warning("[Stripe] Secret manquante/invalide.")

    #    ==========  DB/ EXTENSIONS =================    #
    # Attache la DB sur l'objet app (pratique pour y accéder dans les routes)
    app.db = init_db(app)
    ensure_minimum_indexes(app.db)
    
    # -----  Initialisation des extentions ------ #
    csrf.init_app(app)

    # Si une vue est protégée par @login_required, on redirige ici si non connecté
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Veuillez vous connecter pour continuer."

    #init_db(app)  # initialise MongoDB
    
    # Enregistre les blueprints (routes)
    register_blueprints(app)
    #app.register_blueprint(payments_bp)          # <<<


    @app.template_filter("isoz")
    def isoz(value):
        if value is None:
            return ""
        if getattr(value, "tzinfo", None) is None:
            value = value.replace(tzinfo=timezone.utc)
        # force ISO en UTC (suffixe Z)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


    @login_manager.user_loader
    def load_user(user_id):
        """
        Flask-Login appelle cette fonction à chaque requête
        pour reconstruire l'objet utilisateur depuis l'ID stocké en session.
        L'ID provient du cookie signé (SESSION) envoyé par le navigateur.
        """
        try:
            User_data = app.db.users.find_one({"_id": ObjectId(user_id)})
        except Exception:
            User_data = None
        return MongoUser(User_data) if User_data else None
    
   
    # Permet d'appeler {{ csrf_token() }} dans n’importe quel template Jinja
    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=generate_csrf)

    #--- Les differents types d'erreurs ----
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        # Par ex. jeton manquant / invalide : on renvoie un 400 lisible
        current_app.logger.warning(f"CSRF error: {getattr(e, 'description', e)}")
        return render_template("error.html", message=e.description), 400

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("error.html", message="La page que vous cherchez est introuvable."), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        current_app.logger.error(f"Erreur 500 : {error}")
        return render_template("error.html", message="Une erreur interne est survenue."), 500

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        current_app.logger.exception("Une erreur inattendue s'est produite.")
        return render_template("error.html", message="Quelque chose s'est mal passé."), 500

    # MQTT
    MqttManager(app)

    return app
