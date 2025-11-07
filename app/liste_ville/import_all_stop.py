# app/liste_ville/import_all_json.py
# Usage:
#   python -m app.liste_ville.import_all_json /app/data/arrets.json --clear
#
# - Normalise en {name, code, city, lines:[], location:{type:"Point", coordinates:[lng,lat]}}
# - Crée les index (texte + 2dsphere)
# - --clear : purge chaque ville avant insertion (ou flag "clear" par ville en A)

import os, json, argparse
from collections import defaultdict
from typing import List, Dict, Any

from pymongo import MongoClient, TEXT
from pymongo.errors import OperationFailure

# ---------- DB ----------
def get_db():
    """
    Retourne un handle Database.
    - Si MONGO_URI contient un nom de base (ex: mongodb://mongo:27017/bus_city),
      on l'utilise via get_default_database().
    - Sinon on retombe sur MONGO_DBNAME ou 'bus_city'.
    """
    uri = os.getenv("MONGO_URI") or "mongodb://mongo:27017/bus_city"
    client = MongoClient(uri, tz_aware=True)

    try:
        db = client.get_default_database()  # seulement si la DB est dans l'URI
    except Exception:
        db = None

    if db is None:  
        dbname = os.getenv("MONGO_DBNAME") or "bus_city"
        db = client[dbname]

    return db

def ensure_indexes(db):
    try:
        db.stops.create_index(
            [("name", TEXT), ("code", TEXT), ("city", TEXT)],
            name="stops_text", default_language="french",
        )
    except OperationFailure:
        pass
    try:
        db.stops.create_index([("location", "2dsphere")], name="stops_geo")
    except OperationFailure:
        pass

# ---------- Normalisation ----------
def norm_stop(s: Dict[str, Any], city: str) -> Dict[str, Any]:
    # tolère lat/lng en str
    lat = float(s["lat"])
    lng = float(s["lng"])
    return {
        "name": s["name"].strip(),
        "code": (s.get("code") or None),
        "city": city,
        "lines": [],
        "location": {"type": "Point", "coordinates": [lng, lat]},
    }

def normalize_from_format_a(doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Retourne { cityName: [docs normalisés...] }
    """
    out = {}
    for c in doc.get("cities", []):
        city = c.get("city") or c.get("name")
        if not city:
            continue
        stops = c.get("stops") or []
        docs = []
        for s in stops:
            if not all(k in s for k in ("name", "lat", "lng")):
                continue
            docs.append(norm_stop(s, city))
        out[city] = docs
    return out

def normalize_from_format_b(lst: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped = defaultdict(list)
    for s in lst:
        if not all(k in s for k in ("city", "name", "lat", "lng")):
            continue
        grouped[s["city"]].append(norm_stop(s, s["city"]))
    return dict(grouped)

# ---------- Import ----------
def import_by_city(db, data_by_city: Dict[str, List[Dict[str, Any]]], clear_all: bool, per_city_clear: Dict[str, bool]):
    ensure_indexes(db)
    for city, docs in data_by_city.items():
        if not docs:
            continue
        if clear_all or per_city_clear.get(city, False):
            deleted = db.stops.delete_many({"city": city}).deleted_count
            print(f"[{city}] purge: {deleted} documents supprimés")
        try:
            res = db.stops.insert_many(docs, ordered=False)
            print(f"[{city}] import: +{len(res.inserted_ids)}")
        except Exception as e:
            print(f"[{city}] avertissement insert_many: {e}")
        total = db.stops.count_documents({"city": city})
        print(f"[{city}] total en base: {total}")

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Import multi-villes depuis un JSON unique")
    ap.add_argument("json_path", help="Chemin du JSON (/app/data/arrets.json)")
    ap.add_argument("--clear", action="store_true", help="Purger chaque ville avant import")
    args = ap.parse_args()

    with open(args.json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    per_city_clear = {}
    if isinstance(raw, dict) and "cities" in raw:
        # format A
        data_by_city = normalize_from_format_a(raw)
        # récupère les flags clear par ville si fournis
        for c in raw.get("cities", []):
            city = c.get("city") or c.get("name")
            if city and "clear" in c:
                per_city_clear[city] = bool(c["clear"])
    elif isinstance(raw, list):
        # format B
        data_by_city = normalize_from_format_b(raw)
    else:
        raise SystemExit("JSON invalide: attendu un objet {'cities': [...]} ou une liste de stops.")

    if not data_by_city:
        print("Aucune donnée exploitable dans le JSON.")
        return

    db = get_db()
    import_by_city(db, data_by_city, clear_all=args.clear, per_city_clear=per_city_clear)

if __name__ == "__main__":
    main()
