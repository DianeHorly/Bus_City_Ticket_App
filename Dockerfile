# Dockerfile pour le (service Flask)

FROM python:3.12-slim

# Régler l’env de Python pour du logging propre
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Installer les deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Exposer le port Flask
EXPOSE 5000

# Démarrer l'app
CMD ["python", "run.py"]
