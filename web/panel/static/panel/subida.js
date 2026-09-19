/* Subir facturas (y también Importar datos): soltar ficheros en la zona, enseñar cuáles se han elegido
   y el nombre del lote nuevo. Sin esto la pantalla sigue funcionando: se eligen con el botón de siempre
   y se envía el formulario. */
(function () {
  var zona = document.getElementById("zona-subida");
  var entrada = zona ? zona.querySelector("input[type=file]") : null;
  var elegidas = document.getElementById("elegidas");
  var enviar = document.getElementById("enviar");
  if (!zona || !entrada) { return; }

  function contar() {
    var ficheros = entrada.files;
    var nombres = [];
    for (var i = 0; i < ficheros.length; i++) { nombres.push(ficheros[i].name); }
    if (enviar) { enviar.disabled = nombres.length === 0; }
    if (!elegidas) { return; }
    elegidas.hidden = nombres.length === 0;
    elegidas.textContent = nombres.length === 1
      ? "Va a subir " + nombres[0]
      : "Va a subir " + nombres.length + " ficheros: " + nombres.join(", ");
  }

  entrada.addEventListener("change", contar);
  contar();

  ["dragenter", "dragover"].forEach(function (evento) {
    zona.addEventListener(evento, function (e) { e.preventDefault(); zona.classList.add("encima"); });
  });
  ["dragleave", "drop"].forEach(function (evento) {
    zona.addEventListener(evento, function (e) { e.preventDefault(); zona.classList.remove("encima"); });
  });
  zona.addEventListener("drop", function (e) {
    if (e.dataTransfer && e.dataTransfer.files.length) {
      entrada.files = e.dataTransfer.files;
      contar();
    }
  });

  var lote = document.getElementById("lote");
  var campoNuevo = document.getElementById("campo-lote-nuevo");
  var nombreNuevo = document.getElementById("lote_nuevo");
  if (lote && campoNuevo) {
    lote.addEventListener("change", function () {
      campoNuevo.hidden = lote.value !== "__nuevo__";
      if (!campoNuevo.hidden && nombreNuevo) { nombreNuevo.focus(); }
    });
  }
})();
