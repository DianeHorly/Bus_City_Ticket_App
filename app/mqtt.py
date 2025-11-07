# app/mqtt.py
"""
MQTT manager pour Bus City.

Points clés :
- Variables d'env acceptées :
    * MQTT_URL                -> ex: mqtt://mosquitto:1883, ws://mosquitto:9001, wss://...
    * MQTT_HOST / MQTT_PORT   -> ex: MQTT_HOST=mosquitto, MQTT_PORT=1883
    * MQTT_BROKER_URL / MQTT_BROKER_PORT -> compat ancien code (peut être host OU URL)
    * MQTT_USERNAME / MQTT_PASSWORD
    * MQTT_TRANSPORT          -> "tcp" (défaut) ou "websockets"
    * MQTT_TLS                -> "1"/"true" pour activer TLS (si URL mqtts:// ou wss:// c'est auto)
    * START_MQTT              -> "0"/"false" pour désactiver MQTT proprement

- Connexion asynchrone (connect_async + loop_start) : l'app Flask démarre même si le broker n'est pas dispo.
- Reconnexion automatique (backoff 1..30s) + LWT "online"/"offline".
- Souscription au topic de scan et réponse par device_id.
"""

import os
import json
import uuid
from urllib.parse import urlparse
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from flask import current_app
from bson.objectid import ObjectId

# --- Topics (convention)
SCAN_REQ_TOPIC = "bc/tickets/scan/req"                         # demandes de scan
SCAN_RESP_TOPIC = "bc/tickets/scan/resp/{device_id}"           # réponses par device
EVENT_TOPIC = "bc/users/{user_id}/tickets/{ticket_id}/events"  # événements émis par l'app


def _truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def _load_cfg(app):
    """
    Résout la configuration MQTT depuis ENV et app.config.

    Priorité :
      1) MQTT_URL / MQTT_BROKER_URL (si contient "://", traité comme URL complète)
      2) Paires host/port (MQTT_HOST/MQTT_PORT puis MQTT_BROKER_URL/MQTT_BROKER_PORT comme fallback host/port)
      3) Valeurs par défaut : host="mosquitto" (nom du service Docker), port=1883, transport="tcp"
    TLS est auto-activé si schéma mqtts:// ou wss://, ou si MQTT_TLS=1/true.
    """
    # 1) URL complète éventuelle
    url = (
        os.getenv("MQTT_URL")
        or os.getenv("MQTT_BROKER_URL")
        or app.config.get("MQTT_URL")
        or app.config.get("MQTT_BROKER_URL")
    )
    host = None
    port = None
    transport = "tcp"
    use_tls = False

    if url:
        if "://" in url:  # URL complète
            u = urlparse(url)
            host = u.hostname
            port = u.port
            if u.scheme in ("ws", "wss"):
                transport = "websockets"
            if u.scheme in ("wss", "mqtts", "ssl", "tls"):
                use_tls = True
            if port is None:  # ports par défaut
                port = 9001 if transport == "websockets" else (8883 if use_tls else 1883)
        else:
            # Ce n'est pas une URL, probablement un hostname laissé dans MQTT_BROKER_URL
            host = url

    # 2) Host/port explicites (écrasent au besoin)
    host = (
        os.getenv("MQTT_HOST")
        or app.config.get("MQTT_HOST")
        or host
        or os.getenv("MQTT_BROKER_URL")  # si juste un host ici
        or app.config.get("MQTT_BROKER_URL")
        or "mosquitto"  # réseau compose : utiliser le nom de service
    )
    port = int(
        os.getenv("MQTT_PORT")
        or (app.config.get("MQTT_PORT") if app.config.get("MQTT_PORT") is not None else 0)
        or os.getenv("MQTT_BROKER_PORT")
        or 0
    ) or (port or 1883)

    user = os.getenv("MQTT_USERNAME") or app.config.get("MQTT_USERNAME")
    pwd = os.getenv("MQTT_PASSWORD") or app.config.get("MQTT_PASSWORD")

    # Forçages facultatifs
    transport = os.getenv("MQTT_TRANSPORT") or app.config.get("MQTT_TRANSPORT") or transport  # "tcp"|"websockets"
    use_tls = _truthy(os.getenv("MQTT_TLS") or app.config.get("MQTT_TLS") or use_tls)

    return host, port, transport, use_tls, user, pwd


class MqttManager:
    def __init__(self, app=None):
        self.client: mqtt.Client | None = None
        self.app = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        """
        Initialise le client MQTT :
          - lit la configuration,
          - configure callbacks, reconnexion, LWT,
          - démarre loop_start() et connect_async() (non bloquant).
        """
        self.app = app

        # Permet de désactiver MQTT facilement (ex.: en test local)
        start_flag = os.getenv("START_MQTT") or app.config.get("START_MQTT", "1")
        if str(start_flag).lower() in ("0", "false", "no"):
            app.logger.info("[MQTT] désactivé (START_MQTT=0)")
            return

        host, port, transport, use_tls, user, pwd = _load_cfg(app)
        app.logger.info(f"[MQTT] connexion → host={host} port={port} transport={transport} tls={use_tls}")

        # Crée le client MQTT
        cid = f"bus-city-api-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(client_id=cid, clean_session=True, transport=transport)

        # Auth si fournie
        if user and pwd:
            self.client.username_pw_set(user, pwd)

        # TLS si demandé (cert système par défaut)
        if use_tls:
            try:
                self.client.tls_set()
            except Exception as e:
                app.logger.error(f"[MQTT] tls_set error: {e}")

        # Reconnexion progressive (1..30s) + LWT (Last Will and Testament)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.will_set(
            "bc/service/bus-city-api/status", payload="offline", qos=1, retain=True
        )

        # --- Callbacks
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                app.logger.info(f"[MQTT] connecté ({host}:{port}, {transport})")
                # Annonce "online"
                client.publish(
                    "bc/service/bus-city-api/status",
                    payload="online",
                    qos=1,
                    retain=True,
                )
                # Souscription au topic de scan
                client.subscribe(SCAN_REQ_TOPIC, qos=1)
            else:
                app.logger.error(f"[MQTT] échec connection rc={rc}")

        def on_disconnect(client, userdata, rc):
            if rc != 0:
                app.logger.warning(f"[MQTT] déconnecté (rc={rc}) → tentative de reconnexion…")
            else:
                app.logger.info("[MQTT] déconnecté proprement")

        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.on_message = self._on_message

        # Démarre la boucle réseau et tente la connexion de façon NON bloquante
        self.client.loop_start()
        try:
            self.client.connect_async(host, port, keepalive=30)
        except Exception as e:
            app.logger.error(f"[MQTT] connect_async error: {e}")

        # Expose dans app.extensions
        app.extensions["mqtt"] = self

    # ---- API utilitaire ---------------------------------------------------

    def publish_event(
        self,
        user_id: str,
        ticket_id: str,
        payload: dict,
        qos: int = 1,
        retain: bool = False,
    ):
        """
        Publie un événement (achat, validation, expiration…) sur le topic par ticket.
        N'envoie rien si le client n'est pas connecté (et log un warning).
        """
        topic = EVENT_TOPIC.format(user_id=user_id, ticket_id=ticket_id)
        if not self.client or not self.client.is_connected():
            current_app.logger.warning(f"[MQTT] publish ignoré (client non connecté) → {topic}")
            return
        try:
            self.client.publish(
                topic, json.dumps(payload, separators=(",", ":")), qos=qos, retain=retain
            )
        except Exception as e:
            current_app.logger.error(f"[MQTT] publish error: {e}")

    # ---- Callbacks messages ----------------------------------------------

    def _on_message(self, client: mqtt.Client, userdata, msg):
        """
        Réception d'un message (ex.: requête de scan).
        On ouvre un app_context Flask pour accéder à current_app / DB.
        """
        # Filtre : nous n'écoutons que SCAN_REQ_TOPIC ici, mais on reste générique
        topic = msg.topic or ""
        if topic != SCAN_REQ_TOPIC:
            return

        # Contexte Flask
        with self.app.app_context():
            try:
                data = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                # payload invalide => on ignore
                return

            device_id = (data.get("device_id") or "unknown").strip()
            req_id = data.get("req_id") or uuid.uuid4().hex
            token = data.get("token")
            ticket_id_raw = data.get("ticket_id")  # fallback si pas de token signé

            # --- Vérification token/ID
            db = current_app.db
            ticket_doc = None

            # Option A : token signé (recommandé)
            payload = None
            try:
                from app.security import verify_qr_token  # si implémenté
                if token:
                    payload = verify_qr_token(token)
            except Exception:
                payload = None

            tid = None
            if payload and payload.get("tid"):
                tid = payload["tid"]
            elif ticket_id_raw:
                tid = ticket_id_raw

            resp = {"req_id": req_id, "ok": False, "reason": "invalid"}

            if tid:
                try:
                    ticket_doc = db.tickets.find_one({"_id": ObjectId(tid)})
                except Exception:
                    ticket_doc = None

            now = datetime.now(timezone.utc)

            if ticket_doc:
                # Normaliser tz de expires_at si naïf
                exp = ticket_doc.get("expires_at")
                if exp and getattr(exp, "tzinfo", None) is None:
                    exp = exp.replace(tzinfo=timezone.utc)

                status = ticket_doc.get("status") or "active"
                vstat = ticket_doc.get("validation_status")

                # Marquer expiré si nécessaire
                if exp and exp <= now and status != "expired":
                    db.tickets.update_one(
                        {"_id": ticket_doc["_id"]},
                        {"$set": {"status": "expired", "expired_at": now, "validation_status": None}},
                    )
                    status = "expired"
                    vstat = None

                remaining = int((exp - now).total_seconds()) if exp else None

                resp.update(
                    {
                        "ok": True,
                        "reason": None,
                        "ticket_id": str(ticket_doc["_id"]),
                        "type": ticket_doc.get("type"),
                        "status": status,
                        "validation_status": vstat,
                        "validated_at": ticket_doc.get("validated_at").isoformat()
                        if ticket_doc.get("validated_at")
                        else None,
                        "expires_at": exp.isoformat().replace("+00:00", "Z") if exp else None,
                        "server_now": now.isoformat().replace("+00:00", "Z"),
                        "remaining_seconds": remaining,
                    }
                )

            # Répondre sur le topic du device
            resp_topic = SCAN_RESP_TOPIC.format(device_id=device_id or "unknown")
            try:
                client.publish(resp_topic, json.dumps(resp, separators=(",", ":")), qos=1, retain=False)
            except Exception as e:
                current_app.logger.error(f"[MQTT] publish response error: {e}")


# Helper pour récupérer le manager depuis n’importe où
def mqtt_manager() -> "MqttManager | None":
    return current_app.extensions.get("mqtt")
