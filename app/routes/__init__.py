# app/routes/__init__.py

# Centralise l'enregistrement des ensembles de routes (blueprints).


#from flask_wtf import CSRFProtect
#from app.paiements import bp as payments_bp


def register_blueprints(app):
    # En important les bibliothèque ici, on evite les imports circulaires
    from .accueil import bp as home_bp
    from .auth import bp as auth_bp
    from .dashboard import bp as dashboard_bp
    from .tickets import bp as tickets_bp
    from app.paiements import bp as payments_bp
    from app.routes.arret_bus import bp as stops_bp


    app.register_blueprint(home_bp)        # pages publiques (Accueil)
    app.register_blueprint(auth_bp)        # login / register / logout
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")   # dashboard (protégé)
    app.register_blueprint(tickets_bp, url_prefix="/tickets")     # achat de ticket (protégé)
    app.register_blueprint(payments_bp,  url_prefix="/payments")  # Paiement stripe
    app.register_blueprint(stops_bp)
