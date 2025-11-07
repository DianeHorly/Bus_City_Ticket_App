// app/static/js/ticket_timer.js
// -----------------------------------------------------------
// Minuteur "Temps restant" côté client, qui se synchronise
// sur l'heure SERVEUR pour éviter les décalages de fuseau
// ou d'horloge utilisateur.
// 1) Localiser les dates <time class="dt" data-dt="ISO">
// 2) Minuteur "Temps restant" synchronisé sur l'heure SERVEUR
// -----------------------------------------------------------
(function () {
  // --- [1] Localisation des dates ---
  const LOCALE =
    document.documentElement.getAttribute("lang") || "fr-FR";
  const dateFmt = new Intl.DateTimeFormat(LOCALE, {
    dateStyle: "short",
    timeStyle: "short",
  });

  function localizeTimeElement(el) {
    // On accepte data-dt ( affichage.HTML) ou l'attribut datetime
    const iso =
      el.getAttribute("data-dt") || el.getAttribute("datetime");
    if (!iso) return;

    const d = new Date(iso); // Parse l'UTC -> convertit automatiquement en local
    if (isNaN(d)) return;

    el.textContent = dateFmt.format(d);
    el.setAttribute("title", d.toString());
  }

  function localizeAllTimes(selector = "time.dt") {
    document.querySelectorAll(selector).forEach(localizeTimeElement);
  }

  // --- [2] Minuteur ---
  function pad(n) {
    n = Math.floor(Math.abs(n));
    return n < 10 ? "0" + n : String(n);
  }

  function formatDuration(ms) {
    if (ms <= 0) return "00:00:00";
    const totalSec = Math.floor(ms / 1000);
    const days = Math.floor(totalSec / 86400);
    const hours = Math.floor((totalSec % 86400) / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secs = totalSec % 60;

    if (days > 0) return `${days}j ${pad(hours)}:${pad(mins)}:${pad(secs)}`;
    return `${pad(hours)}:${pad(mins)}:${pad(secs)}`;
  }

  function initCountdown(el, opts) {
    if (!el) return;

    const expiresIso = el.getAttribute("data-expires-at");
    const serverNowIso = el.getAttribute("data-server-now");
    if (!expiresIso || !serverNowIso) return;

    const expiresAtMs = Date.parse(expiresIso);
    const serverNowMs = Date.parse(serverNowIso);
    if (isNaN(expiresAtMs) || isNaN(serverNowMs)) return;

    // Décalage entre l'horloge serveur et celle du client
    const offsetMs = serverNowMs - Date.now();
    let timerId = null;

    function tick() {
      const nowByServerMs = Date.now() + offsetMs;
      const remaining = expiresAtMs - nowByServerMs;

      if (remaining <= 0) {
        el.textContent = "Expiré";
        el.classList.remove("text-warning");
        el.classList.add("text-danger");
        if (timerId) clearInterval(timerId);
        if (opts && opts.autoReloadOnExpire) {
          setTimeout(() => window.location.reload(), 800);
        }
        return;
      }

      if (remaining <= 5 * 60 * 1000) {
        el.classList.add("text-warning");
      } else {
        el.classList.remove("text-warning");
      }

      el.textContent = formatDuration(remaining);
      el.setAttribute("aria-label", `Temps restant ${el.textContent}`);
    }

    tick(); // MAJ immédiate
    timerId = setInterval(tick, 1000);

    // Nettoyage si l'élément disparaît
    const obs = new MutationObserver(() => {
      if (!document.body.contains(el)) {
        clearInterval(timerId);
        obs.disconnect();
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  // API publique
  window.TicketTimer = {
    /**
     * Initialise un minuteur.
     * @param {string|Element} target - sélecteur CSS ou élément
     * @param {object} options - { autoReloadOnExpire?: boolean }
     */
    init(target, options) {
      const opts = options || {};
      const el =
        typeof target === "string" ? document.querySelector(target) : target;
      initCountdown(el, opts);
    },

    /** Force la localisation de tous les <time class="dt"> */
    localize() {
      localizeAllTimes();
    },
  };

  // Localise immédiatement toutes les dates présentes sur la page
  // (Ce script est inclus après le HTML (affichage.html)=> DOM déjà prêt)
  localizeAllTimes();
})();
