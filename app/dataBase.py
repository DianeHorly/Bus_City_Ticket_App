# app/dataBase.py
# -----------------------------------------------------------------------------
# Connexion MongoDB centralisée et création des index indispensables.
#
# Points clés :
#   - Le client PyMongo est tz-aware (UTC) -> toutes les datetimes sont "aware".
#   - Les index sont créés au démarrage (idempotent).
#   - Cohérence géospatiale : on utilise le champ "location" (Point GeoJSON)
#     PARTOUT (index et requêtes).
# -----------------------------------------------------------------------------

import os
import atexit
from pymongo import MongoClient, ASCENDING, TEXT, GEOSPHERE
from pymongo.errors import OperationFailure
from bson.tz_util import utc           # tzinfo UTC → datetimes "aware"
from flask import current_app


def init_db(app):
    """
    Initialise Mongo et attache :
      - app.mongo_client : le MongoClient partagé
      - app.db           : la Database (par défaut 'bus_city')

    On retourne aussi la DB pour pouvoir faire : app.db = init_db(app)
    """
    # Si Déjà initialisé ? -> on réutilise
    if getattr(app, "mongo_client", None) and getattr(app, "db", None):
        return app.db

    # En Docker, l'hôte Mongo est souvent le nom de service 'mongo'
    uri = app.config.get("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://mongo:27017/bus_city"

    # Client tz-aware (UTC) + timeout court pour "fail fast" si souci réseau
    client = MongoClient(uri, tz_aware=True, tzinfo=utc, serverSelectionTimeoutMS=3000)

    # DB depuis l'URI si présente (/bus_city) sinon fallback sur variable/envrion
    try:
        db = client.get_default_database()
    except Exception:
        db = None
    if db is None:
        dbname = app.config.get("MONGO_DBNAME") or os.getenv("MONGO_DBNAME") or "bus_city"
        db = client[dbname]

    # Attache au contexte Flask
    app.mongo_client = client
    app.db = db

    # Fermer proprement le client à l'arrêt du process (utile hors Docker aussi)
    atexit.register(lambda: client.close())

    # Indispensables pour les perfs et certaines fonctionnalités
    ensure_minimum_indexes(db)
    return db


def ensure_minimum_indexes(db):
    """
    Crée les index critiques au démarrage.
    Idempotent : si l'index existe déjà avec d'autres options, on corrige.
    """
    if db is None:
        raise RuntimeError("Database non initialisée (db=None)")

    # --- USERS ---
    # Unicité email (classique)
    db.users.create_index([("email", ASCENDING)], unique=True, name="uniq_email")

    # --- TICKETS ---
    db.tickets.create_index([("user_id", ASCENDING)],  name="idx_ticket_user")
    db.tickets.create_index([("status",  ASCENDING)],  name="idx_ticket_status")
    db.tickets.create_index([("expires_at", ASCENDING)], name="idx_ticket_expires_at")
    # Si on veut que Mongo purge auto les tickets arrivés à expires_at,
    # db.tickets.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at")

    # --- STOPS (ARRÊTS de bus) -------------------------------------------
    # 1) Index texte (recherche par nom/code/ville)
    #    On essaie de créer un index texte nommé "stops_text".
    #    S'il existe déjà avec d'autres options (langue, poids…), on le remplace.
    try:
        db.stops.create_index(
            [("name", "text"), ("code", "text"), ("city", "text")],
            name="stops_text",
            default_language="french",
            language_override="language",
            weights={"name": 1, "code": 1, "city": 1},
        )
    except OperationFailure as e:
        # Cas où l'index existe avec des options différentes -> on le recrée proprement.
        if e.code == 85:  # IndexOptionsConflict
            try:
                db.stops.drop_index("stops_text")
                db.stops.create_index(
                    [("name", "text"), ("code", "text"), ("city", "text")],
                    name="stops_text",
                    default_language="french",
                    language_override="language",
                    weights={"name": 1, "code": 1, "city": 1},
                )
            except Exception:
                pass  # on ne bloque pas l'appli si l'index texte résiste

    # Index géospatial 2dsphere sur 'location'- idempotent (pas de crash si déjà présent)
    try:
        infos = db.stops.index_information()
        has_geo = any(tuple(k) in [(("location", "2dsphere"),)]
                      or any(isinstance(t, tuple) and t[0] == "location" and t[1] == "2dsphere"
                             for t in info.get("key", []))
                      for info in infos.values())
    except Exception:
        has_geo = False

    if not has_geo:
        try:
            db.stops.create_index([("location", GEOSPHERE)], name="stops_geo")
        except OperationFailure as e:
            # si l'Index existe dejà avec un nom different
            if e.code != 85:
                raise

def get_db():
    """ Helper quand on est dans une requête Flask: current_app.db """
    return current_app.db
