// app/static/js/paiements.js

/* ============================================================================
 * paiements.js – Montage Stripe Elements + PaymentIntent + confirmation
 * ----------------------------------------------------------------------------
 * - Monte les 3 Elements (numéro, expiry, CVC) DANS la carte visuelle.
 * - Style lisible (texte noir). 
 * - Crée un PaymentIntent côté serveur, puis le confirme côté client.
 * - Gère les erreurs réseau/Stripe proprement + bouton en état "loading".
 * ========================================================================== */

(function () {
  // Sélecteurs utilisés par le template
  const ROOT_ID = 'payments-root';
  const NUMBER_SLOT = '#el-card-number';
  const EXPIRY_SLOT = '#el-card-expiry';
  const CVC_SLOT = '#el-card-cvc';

  const PAY_BTN_ID = 'card-pay';
  const TYPE_ID = 'card-type';
  const QTY_ID = 'card-qty';
  const NAME_ID = 'cardholder-name';
  const ERR_ID = 'card-errors';

  // Prix de démonstration (en centimes) — adapte à ta logique/DB si besoin.
  const PRICES = {
    single: 150,   // 1,50 €
    day:    500,   // 5,00 €
    week:  1500,   // 15,00 €
    month: 4500    // 45,00 €
  };

  // Récupère le conteneur racine (présent uniquement dans l'onglet "Carte intégrée")
  const root = document.getElementById(ROOT_ID);
  if (!root) return; // Rien à faire sur les autres pages/onglets

  // URLs injectées via data-*
  const CONFIG_URL   = root.dataset.configUrl || '/payments/config';
  const CREATE_PI_URL = root.dataset.createIntentUrl || '/payments/create-payment-intent';
  const FINALIZE_URL   = '/tickets/api/after-payment';      // endpoint qui crée les tickets après succès du paiement
  const CSRF_TOKEN    = root.dataset.csrf || ''; // utile si on veut garder CSRF (sinon, @csrf.exempt)

  // Widgets / états
  const payBtn = document.getElementById(PAY_BTN_ID);
  const typeSel = document.getElementById(TYPE_ID);
  const qtyInput = document.getElementById(QTY_ID);
  const nameInput = document.getElementById(NAME_ID);
  const errBox = document.getElementById(ERR_ID);

  /*
  let stripe = null;
  let elements = null;
  let cardNumber = null;
  let cardExpiry = null;
  let cardCvc    = null;
  */
  let stripe, elements, cardNumber, cardExpiry, cardCvc;


  // --------- Helpers UI ---------
  function setPayLoading(yes) {
    if (!payBtn) return;
    payBtn.disabled = !!yes;
    payBtn.innerText = yes ? 'Traitement…' : 'Payer';
  }
  function showError(msg) {
    if (errBox) {
      errBox.textContent = msg || '';
    } else {
      alert(msg);
    }
  }
  function computeAmountCents() {
    const type = (typeSel && typeSel.value) || 'single';
    const unit = PRICES[type] || PRICES.single;
    const qty  = Math.max(1, parseInt(qtyInput && qtyInput.value, 10) || 1);
    return { amount: unit * qty, type, qty };
  }

  // --------- Initialisation Stripe ---------
  async function initStripe() {
    try {
      if (!window.Stripe) {
        showError("Stripe JS est bloqué (adblock / Brave). Autorisez js.stripe.com et rechargez.");
        if (payBtn) payBtn.disabled = true;
        return;
      }

      //  Récupère la clé publique
      const r = await fetch(CONFIG_URL, { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status} sur /payments/config`);
      const cfg = await r.json();
      if (!cfg.publishableKey || !cfg.publishableKey.startsWith('pk_')) {
        throw new Error('Clé publique invalide ou absente.');
      }

      //  Initialise Stripe et Elements (theme "flat" = sobre)
      stripe = Stripe(cfg.publishableKey);
      /*
      const appearance = {
        theme: 'flat',
        variables: {
          colorText: '#111111',
          colorTextPlaceholder: '#666666',
          colorIcon: '#111111',
          colorBackground: '#ffffff',
          fontSizeBase: '16px',
        },
        rules: {
          '.Input': { backgroundColor: '#ffffff', color: '#111111' },
          '.Input::placeholder': { color: '#666666' },
          //Tab, .Block': { backgroundColor: '#ffffff' },
        },
      }; 
      elements = stripe.elements({ appearance }); */

      //  Styles internes aux iframes (lisibles)
      const elementStyle = {
        style: {
          base: {
            color: '#111111',
            //iconColor: '#111',
            caretColor: '#111111',
            backgroundColor: '#ffffff',      // fond blanc dans l'iframe
            fontSize: '16px',
            fontSmoothing: 'antialiased',
            fontFamily: 'ui-sans-serif, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif',

            lineHeight: '24px',
            '::placeholder': { color: '#111111', opacity: 0.6 },
            ':-webkit-autofill': { color: '#111111' }
          },
          invalid: { color: '#d32f2f' }
        }
      };

      elements = stripe.elements({ appearance: { theme: 'flat' } });

      // Monte les Elements DANS la carte (déjà dans la carte visuelle)
      cardNumber = elements.create('cardNumber', elementStyle);
      cardExpiry = elements.create('cardExpiry', elementStyle);
      cardCvc    = elements.create('cardCvc',    elementStyle);

      cardNumber.mount(NUMBER_SLOT);
      cardExpiry.mount(EXPIRY_SLOT);
      cardCvc.mount(CVC_SLOT);

      // pour charger les iframes dans le bloqueur 
      cardNumber.on('ready', () => {
        console.log('Stripe Element: cardNumber ready');
        try { cardNumber.focus(); } catch {}
      });

      cardExpiry.on('ready',  () => console.log('Stripe Element: cardExpiry ready'));
      cardCvc.on('ready',     () => console.log('Stripe Element: cardCvc ready'));

      // Efface les erreurs à la focus/saisie
      [cardNumber, cardExpiry, cardCvc].forEach(el => {
        el.on('ready',  () => console.log('Stripe Element ready'));
        el.on('change', ev => ev.error ? showError(ev.error.message) : showError(''));
      });

      // Donne le focus automatiquement pour voir le curseur
      setTimeout(() => cardNumber && cardNumber.focus(), 200);

      // Clique sur le bouton "Payer"
      if (payBtn) {
        payBtn.addEventListener('click', onPayClicked);
      }
    } catch (e) {
      console.error('[Stripe init] ', e);
      showError("Impossible de charger la configuration Stripe.");
      if (payBtn) 
        payBtn.disabled = true;
    }
  }

  // --------- Click "Payer" ---------
  async function onPayClicked(e) {
    e.preventDefault();
    showError('');
    setPayLoading(true);

    try {
      // Calcule le montant
      const { amount, type, qty } = computeAmountCents();
      //const amount_cents = computeAmountCents();

      // Demande un PaymentIntent au serveur (on envoie type/qty pour validation serveur)
      const headers = { 'Content-Type': 'application/json' };
      if (CSRF_TOKEN) headers['X-CSRFToken'] = CSRF_TOKEN; // si on n'a pas exempté CSRF

      // Crée le PaymentIntent
      const resp = await fetch(CREATE_PI_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        body: JSON.stringify({ amount_cents: amount, type, qty}),
      });

      // Si le backend renvoie du HTML (erreur 400/500), on évite "Unexpected token '<'"
      const txt = await resp.text();
      let data = {};
      try { data = JSON.parse(txt); } catch { /* pas JSON -> HTML d'erreur */ }

      if (!resp.ok) {
        const msg = (data && (data.error || data.message)) || txt || 'Erreur lors de la création du paiement.';
        throw new Error(msg);
      }

      const clientSecret = data.client_secret;
      if (!clientSecret) throw new Error('client_secret manquant');

      // Confirme le paiement côté client
      const cardHolder = (nameInput && nameInput.value) ? nameInput.value.trim() : 'Client';
      const { error, paymentIntent } = await stripe.confirmCardPayment(clientSecret, {
        payment_method: {
          card: cardNumber,
          billing_details: { name: cardHolder }
        },
      });

      if (error) {
        throw new Error(error.message || 'Le paiement a été refusé.');
      }

      // Succès : Crée les tickets côté serveur, puis on le redirige
      if (paymentIntent && paymentIntent.status === 'succeeded') {
        // On appelle le serveur pour créer les tickets
        const headers = { 'Content-Type': 'application/json' };
        if (CSRF_TOKEN) headers['X-CSRFToken'] = CSRF_TOKEN; 

        const fin = await fetch(FINALIZE_URL, {
          method: 'POST',
          credentials: 'same-origin',
          headers,
          body: JSON.stringify({ pi_id: paymentIntent.id, type, qty }),
        });

        if (!fin.ok) {
          const txt = await fin.text();
          throw new Error(`Création des tickets échouée: ${txt}`);
        }

        // si Succès -> on redirige
        window.location.href = '/tickets/'; // ou '/dashboard/'
        return;
      }

    showError('Paiement en attente ou à vérifier.');
    } catch (err) {
      console.error('[Pay error]', err);
      showError(String(err.message || err));
    } finally {
      setPayLoading(false);
    }
  }

  // Lance l’init quand le DOM est prêt (defer = déjà prêt, mais on sécurise)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStripe);
  } else {
    initStripe();
  }
})();
