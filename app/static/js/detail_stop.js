//  app/static/js/detail_stop.js

(function () {
  const dataTag = document.getElementById("stop-data");
  const s = JSON.parse(dataTag.textContent);

  const map = L.map('map').setView([s.lat, s.lng], 16);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
  L.marker([s.lat, s.lng]).addTo(map).bindPopup(`<b>${escapeHtml(s.name)}</b>`).openPopup();

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, s => (
      { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[s]
    ));
  }
})();
