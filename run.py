# run.py
from dotenv import load_dotenv
from app import create_app

load_dotenv()  # charge .env en dev/docker-compose

app = create_app()

if __name__ == "__main__":
    # IMPORTANT : pas de reloader en conteneur pour éviter les doubles lancements
    app.run(host="0.0.0.0", port=5000, debug=True)
