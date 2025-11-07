// app/static/js/arret_bus.js
(() => {
  "use strict";

  function ready(fn){ document.readyState==="loading" ? document.addEventListener("DOMContentLoaded", fn) : fn(); }

  ready(() => {
    const btn = document.getElementById("btn-near");
    if (!btn) return;

    btn.addEventListener("click", () => {
      if (!navigator.geolocation) {
        alert("La géolocalisation n'est pas disponible.");
        return;
      }
      btn.disabled = true;
      btn.textContent = "Recherche…";
      navigator.geolocation.getCurrentPosition(async (pos) => {
        try {
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          const url = `/stops/near?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}&r=1200`;
          const res = await fetch(url, {headers: {"Accept": "application/json"}});
          const data = await res.json();
          renderNear(data.items || []);
        } catch (e) {
          console.error(e);
          alert("Erreur pendant la recherche.");
        } finally {
          btn.disabled = false;
          btn.textContent = "Autour de moi";
        }
      }, (err) => {
        alert("Géolocalisation refusée ou impossible.");
        btn.disabled = false;
        btn.textContent = "Autour de moi";
      }, {enableHighAccuracy: true, timeout: 8000});
    });

    function renderNear(items) {
      const box  = document.getElementById("near-results");
      const list = document.getElementById("near-list");
      if (!box || !list) return;
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = "<li class='text-muted'>Aucun arrêt proche.</li>";
      } else {
        for (const it of items) {
          const li = document.createElement("li");
          li.className = "my-1";
          li.innerHTML = `
            <a href="/stops/${it.id}">${it.name}</a>
            <small class="text-muted ms-1"><code>${it.code || ""}</code></small>
          `;
          list.appendChild(li);
        }
      }
      box.classList.remove("d-none");
      box.scrollIntoView({behavior: "smooth", block: "nearest"});
    }
  });
})();
