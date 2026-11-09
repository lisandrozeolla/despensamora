/* Barra de escaneo global.
   El lector de codigos de barras USB actua como teclado: escribe el codigo
   en #scan-input y envia un Enter. Cada pagina se suscribe al evento 'scan'
   para procesar el codigo segun la pantalla activa. */
(function () {
  const input = document.getElementById('scan-input');

  // Muestra un mensaje flotante en la parte inferior de la pantalla.
  window.toast = function (texto, tipo) {
    const el = document.getElementById('toast');
    el.textContent = texto;
    el.className = 'toast' + (tipo === 'error' ? ' error' : '');
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add('hidden'), 2600);
  };

  // Dispara el evento 'scan' con el codigo leido.
  function procesarLectura() {
    const codigo = input.value.trim();
    input.value = '';
    if (!codigo) return;
    document.dispatchEvent(new CustomEvent('scan', { detail: { codigo } }));
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') procesarLectura();
  });

  // Si no se esta escribiendo en otro campo, el foco vuelve al escaner.
  document.addEventListener('click', (e) => {
    const tag = e.target.tagName;
    const escribiendo = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag);
    const enBoton = e.target.closest('button, a');
    if (!escribiendo && !enBoton) input.focus();
  });

  // Oculta el badge de reposicion si no hay casos pendientes.
  // data.total ya incluye faltantes, bajo minimo y reclamos al proveedor.
  fetch('/api/alertas')
    .then((r) => r.json())
    .then((data) => {
      const badge = document.getElementById('badge-reposicion');
      const total = data.total || 0;
      if (badge && total > 0) {
        badge.textContent = total;
        badge.classList.remove('hidden');
      }
    })
    .catch(() => {});

  input.focus();
})();
