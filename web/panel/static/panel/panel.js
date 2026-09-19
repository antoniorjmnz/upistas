/* Previsualizar una factura: cualquier botón con data-pdf abre el PDF encima de la página, sin salir de ella. */
(function () {
  var visor = document.getElementById("visor");
  if (!visor || typeof visor.showModal !== "function") { return; }
  var marco = visor.querySelector("iframe");
  var titulo = visor.querySelector(".visor-titulo");
  var abrir = visor.querySelector(".visor-abrir");

  document.addEventListener("click", function (e) {
    var boton = e.target.closest("[data-pdf]");
    if (boton) {
      e.preventDefault();
      var url = boton.getAttribute("data-pdf");
      titulo.textContent = boton.getAttribute("data-titulo") || "Factura";
      abrir.href = url;
      marco.src = url;
      visor.showModal();
      return;
    }
    if (e.target.closest("[data-cerrar]") || e.target === visor) {
      visor.close();
    }
  });
  visor.addEventListener("close", function () { marco.src = "about:blank"; });
})();

/* Preguntar: el panel lateral que hay en todas las pantallas (menos en /preguntar/) y lo común con la pantalla entera. */
(function () {
  var panel = document.getElementById("asistente");
  var botones = document.querySelectorAll("[data-abrir-asistente]");
  var abierto = false;

  function guardar(valor) {
    try { sessionStorage.setItem("asistente", valor ? "1" : ""); } catch (e) { /* sin almacenamiento, no pasa nada */ }
  }
  function marcar() {
    botones.forEach(function (b) { b.setAttribute("aria-expanded", abierto ? "true" : "false"); });
    document.body.classList.toggle("con-asistente", abierto);
  }
  function abrir() {
    if (!panel || abierto) { return; }
    if (typeof panel.show === "function") { panel.show(); } else { panel.setAttribute("open", ""); }
    abierto = true;
    marcar();
    guardar(true);
    var chat = panel.querySelector(".chat");
    if (chat) { chat.scrollTop = chat.scrollHeight; }
    var input = panel.querySelector("input[name=pregunta]");
    if (input) { input.focus({ preventScroll: true }); }
  }
  function cerrar() {
    if (!panel || !abierto) { return; }
    if (typeof panel.close === "function") { panel.close(); } else { panel.removeAttribute("open"); }
    abierto = false;
    marcar();
    guardar(false);
  }

  if (panel) {
    botones.forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.preventDefault();
        if (abierto) { cerrar(); } else { abrir(); }
      });
    });
    // «No» en una propuesta es un envío normal del formulario (rechazar=1): la sesión la olvida.
    document.addEventListener("click", function (e) {
      if (e.target.closest("[data-cerrar-asistente]")) { cerrar(); }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && abierto) { cerrar(); }
    });
    // Sigue abierto al cambiar de pantalla, y se abre si la dirección lleva #asistente.
    var guardado = "";
    try { guardado = sessionStorage.getItem("asistente") || ""; } catch (e) { /* nada */ }
    if (guardado === "1" || location.hash === "#asistente") { abrir(); }
  }

  // La pregunta aparece al instante en la conversación; la respuesta llega por htmx cuando la IA termina.
  document.addEventListener("htmx:beforeRequest", function (e) {
    var form = e.target.closest ? e.target.closest("form.formpregunta") : null;
    if (!form) { return; }
    var input = form.querySelector("input[name=pregunta]");
    if (!input || !input.value.trim()) { return; }
    var destino = document.querySelector(form.getAttribute("hx-target"));
    if (!destino) { return; }
    var vacio = destino.querySelector(".vacio-chat");
    if (vacio) { vacio.remove(); }
    var div = document.createElement("div");
    div.className = "mensaje alberto";
    var p = document.createElement("p");
    p.textContent = input.value;
    div.appendChild(p);
    destino.appendChild(div);
    destino.scrollTop = destino.scrollHeight;
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    var chat = e.target.closest ? e.target.closest(".chat") : null;
    if (chat) { chat.scrollTop = chat.scrollHeight; }
  });

  // Las preguntas de ejemplo rellenan el cuadro que tienen al lado.
  document.addEventListener("click", function (e) {
    var chip = e.target.closest("[data-ejemplo]");
    if (!chip) { return; }
    var raiz = chip.closest("dialog, section") || document;
    var input = raiz.querySelector("input[name=pregunta]");
    if (input) { input.value = chip.textContent.trim(); input.focus(); }
  });
})();
