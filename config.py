# app/config.py

# Ce fichier centralise la configuration de l’appli.

import os

class Config:
    # Clé Flask sert à chiffrer les cookies de session (Flask-Login)
    # et à protéger les formulaires (CSRF).
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    # Mongo: IMPORTANT -> utilisez le nom du service docker "mongo"
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "bus_city")


    # MQTT: on utilise le service "mosquitto"
    MQTT_BROKER_URL = os.getenv("MQTT_BROKER_URL", "mosquitto")
    MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))

    # CSRF activé (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None         # token sans expiration pendant tes tests
    WTF_CSRF_SSL_STRICT = False        # on est en http en dev
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False

    # Stripe pour le paiement
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", "")  # en dev
    STRIPE_SUCCESS_URL     = os.environ.get("STRIPE_SUCCESS_URL", "http://localhost:5000/dashboard/")
    STRIPE_CANCEL_URL      = os.environ.get("STRIPE_CANCEL_URL", "http://localhost:5000/tickets/buy")
    STRIPE_CURRENCY        = os.getenv("STRIPE_CURRENCY", "eur")

    # Tarifs en centimes
    TICKET_UNIT_AMOUNTS = {
        "single": 200,   # 2.00 €
        "day":    500,
        "week":   1500,
        "month":  5000,
    }

    # On démarrera le client MQTT plus tard (si besoin)
    START_MQTT = os.getenv("START_MQTT", "0")  # "1" pour activer

class DevelopmentConfig(Config):
    DEBUG = True
    ENV = "development"
