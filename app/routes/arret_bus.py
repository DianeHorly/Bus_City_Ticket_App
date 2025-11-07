# app/routes/arret_bus.py
# -----------------------------------------------------------------------------
# Blueprint "Arrêts de bus"
# - Liste/recherche d'arrêts
# - Détail d'un arrêt
# - Recherche des arrêts proches (JSON)
#
# NOTE:
#   - On s'aligne sur le champ géospatial "location" (Point GeoJSON) pour TOUT :
#     - l'index GEOSPHERE est créé sur "location" (voir. dataBase.ensure_minimum_indexes)
#     - la route /stops/near interroge aussi "location"
#   - Les templates attendus : app/templates/arret_bus/index.html et detail.html
# -----------------------------------------------------------------------------

import re  # utilisé pour l'échappement dans la recherche regex
from flask import Blueprint, render_template, request, current_app, abort, jsonify, redirect, url_for
from flask_login import login_required
from bson.objectid import ObjectId
from pymongo.errors import OperationFailure 

bp = Blueprint("arret_bus", __name__, url_prefix="/stops")


# ----------------------------------------------------------------------------- 
# LISTE + RECHERCHE (plein-texte si index dispo, sinon regex)
# GET /stops/?q=... 
# -----------------------------------------------------------------------------
@bp.route("/", methods=["GET"])
@login_required
def index():
    db = current_app.db
    # on récupère la query utilisateur proprement
    q = (request.args.get("q") or "").strip()

    # Ce qu'on renvoie au template (projection = champs utiles seulement)
    proj = {"name": 1, "code": 1, "city": 1, "lines": 1, "location": 1}
    sort = [("name", 1)]  # tri alpha de base

    rows = []

    if q:
        # recherche plein-texte (rapide et pertinente)
        #  Nécessite l'index texte "stops_text" (créé au boot)
        try:
            rows = list(
                db.stops.find(
                    {"$text": {"$search": q}},
                    {**proj, "score": {"$meta": "textScore"}}
                ).sort([("score", {"$meta": "textScore"}), ("name", 1)])
            )
        except Exception:
            # Si l'index texte n'existe pas encore (ou autre souci), on tombera en regex
            rows = []

        # fallback regex (moins performant mais fonctionne partout)
        if not rows:
            # On découpe "gare centre" => tokens ["gare","centre"]
            # et on fabrique une regex tolérante "gare.*centre" (ordre conservé)
            tokens = [re.escape(t) for t in q.split() if t]
            if tokens:
                rx = ".*".join(tokens)
                rows = list(
                    db.stops.find(
                        {"$or": [
                            {"name": {"$regex": rx, "$options": "i"}},
                            {"code": {"$regex": rx, "$options": "i"}},
                            {"city": {"$regex": rx, "$options": "i"}},
                        ]},
                        proj
                    ).sort(sort)
                )
    else:
        # Aucun filtre : on liste 
        rows = list(db.stops.find({}, proj).sort(sort))

    # On a choisi ici "arret_bus/index.html" pour rester cohérent avec le blueprint
    return render_template("arret_bus/index.html", stops=rows, q=q)


# ----------------------------------------------------------------------------- 
# DÉTAIL d'un arrêt
# GET /stops/<stop_id>
# -----------------------------------------------------------------------------
@bp.route("/<stop_id>", methods=["GET"])
def detail(stop_id):
    """Détail d'un arrêt (mini carte et infos)."""
    db = current_app.db
    #try:
    #    oid = ObjectId(stop_id)
    #except Exception:
    #    abort(404)

    #s = db.stops.find_one({"_id": oid})
    #if not s:
    #    abort(404)

    #return render_template("arret_bus/detail.html", s=s)
     # Accepte ObjectId ou string simple
    query = {"_id": stop_id}
    try:
        query = {"_id": ObjectId(stop_id)}
    except Exception:
        pass

    s = db.stops.find_one(query, {
        "name": 1, "code": 1, "city": 1, "lines": 1, "location": 1
    })
    if not s:
        abort(404)

    # Rendre lat/lng faciles pour le template
    lat = None; lng = None
    coords = (s.get("location") or {}).get("coordinates")
    if isinstance(coords, list) and len(coords) == 2:
        lng, lat = coords  # GeoJSON = [lng, lat]

    return render_template(
        "arret_bus/detail_stop.html",
        s=s, lat=lat, lng=lng
    )

# ---------------------------------------------------------------------------
# PROCHES DE MOI (JSON)
# /stops/near?lat=..&lng=..&r=1000
# ---------------------------------------------------------------------------
@bp.route("/near", methods=["GET"])
@login_required
def near():
    db = current_app.db
    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
        r = int(request.args.get("r", "1000"))
    except Exception:
        return jsonify({"error": "Paramètres lat/lng/r invalides"}), 400

    q = {
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": r
            }
        }
    }
    rows = list(db.stops.find(q).limit(20))
    data = [{
        "id": str(x["_id"]),
        "name": x.get("name"),
        "code": x.get("code"),
        "zone": x.get("zone"),
        "lat": (x.get("location", {}) or {}).get("coordinates", [None, None])[1],
        "lng": (x.get("location", {}) or {}).get("coordinates", [None, None])[0],
    } for x in rows]
    return jsonify({"items": data})


# ---------------------------------------------------------------------------
# PAGE CARTE (ville -> marqueurs)
# ---------------------------------------------------------------------------
@bp.route("/map", methods=["GET"])
@login_required
def map_by_city():
    # La page charge la carte et le <select>, le JS appelle /stops/cities puis /stops/by_city
    return render_template("arret_bus/map_stops.html")


# ---------------------------------------------------------------------------
# API CITIES (JSON) – sans $coalesce (compat vieux Mongo)
# ---------------------------------------------------------------------------
@bp.route("/cities", methods=["GET"])
def cities_list():
    """Liste des villes disponibles."""
    db = current_app.db
    pipeline = [
        {"$project": {
            "city_raw": {"$ifNull": ["$city", {"$ifNull": ["$ville", "$town"]}]}
        }},
        {"$match": {"city_raw": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": {"$toLower": "$city_raw"}}},
        {"$sort": {"_id": 1}},
    ]
    #rows = list(db.stops.aggregate(pipeline))
    #cities = [r["_id"] for r in rows if r["_id"]]
    #return jsonify(cities)
    try:
        rows = list(db.stops.aggregate(pipeline))
        cities = [r["_id"] for r in rows]
    except Exception as e:
        current_app.logger.warning("cities_list: fallback python (%s)", e)
        seen = set()
        for d in db.stops.find({}, {"city": 1, "ville": 1, "town": 1}):
            raw = d.get("city") or d.get("ville") or d.get("town")
            if isinstance(raw, str):
                raw = raw.strip().lower()
                if raw:
                    seen.add(raw)
        cities = sorted(seen)
    return jsonify({"cities": cities})

# ---------------------------------------------------------------------------
# API STOPS BY CITY (JSON)
# ---------------------------------------------------------------------------
@bp.route("/by_city", methods=["GET"])
def stops_by_city():
    """
    Renvoie les arrêts pour la ville choisie (match sur city/ville/town, insensible à la casse).
    """
    db = current_app.db

    city = (request.args.get("city") or "").strip()
    if not city:
        return jsonify({"items": []})

    # insensible à la casse sur plusieurs champs (city/ville/town)
    regex = {"$regex": f"^{re.escape(city)}$", "$options": "i"}
    query = {"$or": [{"city": regex}, {"ville": regex}, {"town": regex}]}

    # récupère seulement ce qu'il faut
    rows = db.stops.find(query, {"name":1, "code":1, "location":1, "lat":1, "lng":1})

    items = []
    for r in rows:
        # supporte location.coordinates ou lat/lng
        coords = (r.get("location") or {}).get("coordinates") or []
        if len(coords) == 2:
            lng, lat = coords
        else:
            lat = r.get("lat"); lng = r.get("lng")

        items.append({
            "id": str(r["_id"]),
            "name": r.get("name"),
            "code": r.get("code"),
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
        })
    return jsonify({"items": items})

# ---------------------------------------------------------------------------
# SEED DEV (facultatif) – insère 3 arrêts de test si tu n’as pas de données
# ---------------------------------------------------------------------------
@bp.route("/dev/seed", methods=["GET"])
@login_required
def seed_dev():
    db = current_app.db
    sample = [
        {"name": "Gare Centre", "code": "RMS-GC", "city": "Reims",
         "location": {"type": "Point", "coordinates": [4.0317, 49.2583]}},
        {"name": "Hôtel de Ville", "code": "PAR-HV", "city": "Paris",
         "location": {"type": "Point", "coordinates": [2.3522, 48.8566]}},
        {"name": "Lille Flandres", "code": "LIL-LF", "city": "Lille",
         "location": {"type": "Point", "coordinates": [3.0700, 50.6369]}},
    ]
    # évite les doublons grossiers
    for s in sample:
        if not db.stops.find_one({"code": s["code"]}):
            db.stops.insert_one(s)
    return redirect(url_for("arret_bus.map_by_city"))