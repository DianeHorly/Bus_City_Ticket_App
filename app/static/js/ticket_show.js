// app/static/js/ticket_show.js

(() => {
  "use strict";

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  onReady(() => {
    // --- Bouton "copier l'ID" du ticket ------
    const btnCopy = document.getElementById("btn-copy-id");
    if (btnCopy) {
      btnCopy.addEventListener("click", async () => {
        const text = btnCopy.dataset.id || "";
        try {
          await navigator.clipboard.writeText(text);
          btnCopy.innerHTML = '<i class="bi bi-clipboard-check"></i> Copié';
          setTimeout(() => {
            btnCopy.innerHTML = '<i class="bi bi-clipboard"></i> Copier';
          }, 1500);
        } catch {
          alert("Impossible de copier l'ID");
        }
      });
    }

    
    // --- Imprimer ---
    const btnPrint = document.getElementById("btn-print");
    if (btnPrint) btnPrint.addEventListener("click", () => window.print());

    // --- Compte à rebours (présent uniquement si le ticket est "validé")
    const box = document.getElementById("timing-data");
    if (!box) return; // rien à faire si la zone n'existe pas sur cette page

    const serverNowStr   = box.dataset.serverNow;
    const validatedAtStr = box.dataset.validatedAt;
    const expiresAtStr   = box.dataset.expiresAt;

    if (!expiresAtStr || !validatedAtStr) return;

    let now         = serverNowStr ? new Date(serverNowStr) : new Date();
    const validated = new Date(validatedAtStr);
    const expires   = new Date(expiresAtStr);

    const totalMs = Math.max(0, expires - validated);
    const label = document.getElementById("countdown-label"); // barre (width%)
    const bar   = document.getElementById("countdown-bar"); // barre (width%)


    function fmt(ms) {
      const s = Math.max(0, Math.floor(ms / 1000));
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const sec = s % 60;
      return (h ? h + "h " : "") +
             (m < 10 ? "0" + m : m) + "m " +
             (sec < 10 ? "0" + sec : sec) + "s";
    }

    function tick() {
      // On avance le temps côté client (ancré sur l'heure serveur au chargement)
      now = new Date(now.getTime() + 1000);
      const remaining = Math.max(0, expires - now);
      if (label) label.textContent = fmt(remaining);

      const used = Math.min(totalMs, Math.max(0, now - validated));
      const pct = totalMs ? Math.round((used / totalMs) * 100) : 100;
      if (bar) bar.style.width = pct + "%";

      if (remaining <= 0) {
        clearInterval(timer);
        if (label) label.textContent = "Expiré";
        // latence visuelle puis rechargement
        setTimeout(() => location.reload(), 1200);
      }
    }

    tick();
    const timer = setInterval(tick, 1000);
  });
})();
