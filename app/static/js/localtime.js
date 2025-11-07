
/*  app/static/js/localtime.js               */

// Convertit toutes les <time class="js-localtime"> en heure locale
(function () {
  function fmt(d) {
    return d.toLocaleString(undefined, {
      year:'numeric', month:'2-digit', day:'2-digit',
      hour:'2-digit', minute:'2-digit', hour12:false
    });
  }
  function convert(el) {
    const iso = el.getAttribute('datetime') || el.dataset.dt || el.textContent.trim();
    if (!iso) return;
    const d = new Date(iso); // '...Z' => interprété comme UTC
    if (!isNaN(d)) el.textContent = fmt(d);
  }
  function run() {
    document.querySelectorAll('time.js-localtime, .js-localtime').forEach(convert);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();


