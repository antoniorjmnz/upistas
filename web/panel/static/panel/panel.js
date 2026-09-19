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
