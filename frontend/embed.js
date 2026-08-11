(() => {
  const script = document.currentScript;

  // Resolve the widget against this script's own URL, not the host page's.
  // Embedded on scaio.org, a relative default would resolve to
  // scaio.org/frontend/widget.html and 404 — the widget must come from
  // whichever origin serves embed.js. `data-widget-src` still overrides.
  const widgetSrc = script.getAttribute('data-widget-src')
    || new URL('widget.html', script.src).href;

  const BTN_SIZE   = 60;
  const MARGIN     = 24;
  const W_WIDTH    = 400;
  const W_HEIGHT   = 600;

  // Floating button
  const btn = document.createElement('button');
  Object.assign(btn.style, {
    position:     'fixed',
    bottom:       MARGIN + 'px',
    right:        MARGIN + 'px',
    width:        BTN_SIZE + 'px',
    height:       BTN_SIZE + 'px',
    borderRadius: '50%',
    background:   'linear-gradient(135deg, #0b4ea2, #2f7ae5)',
    border:       'none',
    cursor:       'pointer',
    boxShadow:    '0 14px 34px rgba(10,42,84,0.28)',
    zIndex:       '999998',
    display:      'flex',
    alignItems:   'center',
    justifyContent: 'center',
    transition:   'transform 0.15s, box-shadow 0.15s',
  });
  btn.setAttribute('aria-label', 'Open SC AI Policy Navigator');
  btn.innerHTML = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
  btn.onmouseenter = () => { btn.style.transform = 'scale(1.08)'; btn.style.boxShadow = '0 18px 40px rgba(10,42,84,0.36)'; };
  btn.onmouseleave = () => { btn.style.transform = 'scale(1)';    btn.style.boxShadow = '0 14px 34px rgba(10,42,84,0.28)'; };

  // Iframe
  const frame = document.createElement('iframe');
  Object.assign(frame.style, {
    position:     'fixed',
    bottom:       (BTN_SIZE + MARGIN + 12) + 'px',
    right:        MARGIN + 'px',
    // Clamp to the viewport so the panel doesn't overflow on phones.
    width:        `min(${W_WIDTH}px, calc(100vw - ${MARGIN * 2}px))`,
    height:       `min(${W_HEIGHT}px, calc(100vh - ${BTN_SIZE + MARGIN * 2 + 24}px))`,
    border:       'none',
    borderRadius: '12px',
    boxShadow:    '0 14px 34px rgba(10,42,84,0.22)',
    zIndex:       '999999',
    display:      'none',
  });
  frame.src   = widgetSrc;
  frame.title = 'SC AI Policy Navigator';

  let open = false;
  btn.onclick = () => {
    open = !open;
    frame.style.display = open ? 'block' : 'none';
    btn.innerHTML = open
      ? `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`
      : `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
  };

  document.body.appendChild(frame);
  document.body.appendChild(btn);
})();
