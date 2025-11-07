# A propos du projet:
Ce projet porte sur le creation d'une application de gestion de ticket de bus d'une ville. Elle a été developpé avec les langages et technologie suivants: Vscode, Flask, Python,  HTML, CSS, MongoDB, Javascript, Bootstrap, les templates jinja2, docker, docker compose, stripe et MQTT(scanner).

# Fonctionnalités:
**0- MongoDB** pour le stockage des données.
**1- Inscription et de connexion d'un utilisateur**:
- Authentification / sessions via Flask-Login (login requis sur les vues sensibles).
- Sécurité CSRF via Flask-WTF.
**2- Achat et validation de tickets(QR code):**
    Pour accéder à ces pages, un utilisateur doit etre connecté.
    - Achat de tickets (/tickets/buy) et liste des titres (/tickets/).
      2 modes d'achat d'un ticket:
      * Payement sans carte bancaire
      * payement avec carte via stripe
    - Détail d'un ticket avec QR code (/tickets/<id>, /tickets/<id>/qrcode.png)
    - Validation d'un ticket en deux étapes (start/confirm).

**3- Un dashboard:** representant les statistiques sur les tickets ( actifs, expiré, en cours de valitaion)
**4- Page Carte (/stops/map) avec :**
***Sélecteur de villes:*** 
- Affichage des marqueurs d'arrêts (nom, code, lien Détails).
- Page Détails (/stops/<id>) d’un arrêt sélectionné.

***API internes :***
- GET /stops/cities --> liste des villes
- GET /stops/by_city?city=<nom> --> arrêts d'une ville

***Import des arrêts :***
un fichier JSON data/arrets.json avec toutes les villes et leurs arrêts.

**5- Intégration MQTT** pour la validation côté bornes/scanners

# Recommandations
Pour visualiser toutes les fonctionnalités et exécuter ce projet, vous aurez besoin de:
1. Installer Docker Desktop 
2. Installer docker sur votre machine
3. installer WSL Le Sous-système Windows pour Linux car il n'est pas installé pour exécuter l'image Linux "mongo" et pour demarrer le moteur docker (car je possède un pc Windowns).
4. Avoir un compte stripe pour recupérer la clé Api publique


##   Commandes pour l'execution du projet
0. Cloner la repository puis accéder au dossier du projet:
    git clone https://
    cd Bus_City_App
    []créer un fichier .env : 
        cp app/.env.example app/.env
    Et remplacer les clé stripe test par les votre.
1. lancer le projet avec:
    pip3 install -r requirements.txt
    docker compose up --build
2.  Via votre navigateur, saissisez http://127.0.0.1:5000 pour acceder à l'application et explorer les différentes fonctionalités.
3. Pour charger la liste de ville et arrets contenus dans le fichier json, saisissez:
    docker compose run --rm --entrypoint python importer `-m app.liste_ville.import_all_stop `/app/data/arrets.json `--clear

4. Allez sur "http://127.0.0.1:5000/stops/cities" pour voir la liste json.

5. ensuite pour ramener dans la base :

    docker compose exec -T mongo mongosh --quiet --eval "db.getSiblingDB('bus_city').stops.aggregate([{`$group:{ _id:'`$city', n:{`$sum:1}}},{`$sort:{ _id:1}}]).toArray()"

6. Ouvrez la page /stops/map et choisisez une ville pour voir les marquers.


