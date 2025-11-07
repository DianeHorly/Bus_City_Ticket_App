# app/models/user.py
# Adaptateur léger pour utiliser un document Mongo comme "User" avec Flask-Login.

from flask_login import UserMixin

class MongoUser(UserMixin):
    """
    UserMixin fournit :
      - is_authenticated / is_active / is_anonymous
      - get_id() -> ici on expose 'id'
    Flask-Login stocke l'ID utilisateur dans la session (cookie signé).
    """
    def __init__(self, doc):
        self.id = str(doc["_id"])          # Flask-Login attend une str
        self.email = doc["email"]
        self.name = doc.get("name", "")
