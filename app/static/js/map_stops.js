//    app/static/js/map_stops.js
// app/static/js/map_stops.js
// Remplit la liste des villes, affiche les arrêts d'une ville sur Leaflet.

(function () {
  const citySelect = document.getElementById("citySelect");
  const emptyHint  = document.getElementById("emptyHint");

  // Carte
  const map = L.map("map").setView([46.5, 2.5], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  let markersLayer = L.layerGroup().addTo(map);

  // Utilitaires
  function clearMarkers() {
    markersLayer.clearLayers();
  }
  function fitIfAny(bounds) {
    if (bounds && bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30] });
  }

  // Charge la liste des villes
  async function loadCities() {
    try {
      const resp = await fetch("/stops/cities");
      const data = await resp.json();
      const cities = data.cities || [];

      // reset
      citySelect.innerHTML = '<option value="" selected disabled>— Choisir une ville —</option>';

      if (cities.length === 0) {
        emptyHint.classList.remove("d-none");
        return;
      }
      emptyHint.classList.add("d-none");

      for (const c of cities) {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c.charAt(0).toUpperCase() + c.slice(1);
        citySelect.appendChild(opt);
      }
    } catch (e) {
      console.error("loadCities error:", e);
    }
  }

  // Charge les arrêts d'une ville et place les marqueurs
  async function loadStopsForCity(city) {
    markersLayer.clearLayers();
    if (!city) return;

    try {
      const resp = await fetch(`/stops/by_city?city=${encodeURIComponent(city)}`);
      const data = await resp.json();

      // Accepte un array brut ou { items: [...] }
      const items = Array.isArray(data) ? data : (data.items || []);

      const bounds = L.latLngBounds();

      for (const s of items) {
      // Récupère lat/lng depuis plusieurs formats possibles
      const lat = Number(
        s.lat ??
        (s.location && Array.isArray(s.location.coordinates) ? s.location.coordinates[1] : undefined) ??
        s.latitude
      );
      const lng = Number(
        s.lng ??
        (s.location && Array.isArray(s.location.coordinates) ? s.location.coordinates[0] : undefined) ??
        s.longitude
      );

      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        // Aide au debug si un arrêt n'a pas de coord
        console.warn("Arrêt ignoré (coord manquantes):", s);
        continue;
      }

      const m = L.marker([lat, lng]).bindPopup(`
        <strong>${s.name || "Sans nom"}</strong><br/>
        Code: ${s.code || "-"}<br/>
        <a href="/stops/${s.id || s._id}">Détails</a>
      `);
      m.addTo(markersLayer);
      bounds.extend([lat, lng]);
    }

    if (items.length === 0) {
      console.warn("Aucun arrêt renvoyé pour la ville:", city, data);
    }
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30] });
  } catch (e) {
    console.error("loadStopsForCity error:", e);
  }
}

  // Evennements
  citySelect.addEventListener("change", (ev) => {
    const city = ev.target.value;
    loadStopsForCity(city);
  });

  // Go!
  loadCities();
})();
