# app/extensions.py
# Un endroit central pour déclarer les extensions Flask,
# afin d'éviter les imports circulaires entre modules.

from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager

# Instances "globales" (non liées à une app pour l’instant)
csrf = CSRFProtect()
login_manager = LoginManager()
