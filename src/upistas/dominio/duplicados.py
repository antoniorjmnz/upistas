import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from datetime import date

from upistas.dominio.importes import normaliza_iban
from upistas.dominio.modelos import GRAVEDAD, Comprobacion, Decision, Factura, Resultado

# Con estas causas no se puede dar por probado nada: un bloqueo por duplicado no las convierte en NO_PAGAR.
DUDA_REAL = frozenset({"R0_lectura", "R6_evaluacion_disponible", "R6_maestro_verificable"})
# Si la norma ya había dejado la factura en revisión por esto, el duplicado se anota pero no decide.
REVISION_PENDIENTE = frozenset({"R3_datos_fiscales", "R6_notas", "R6_contenido_oculto"})


def resolver_duplicados(decisiones: list[Decision], facturas: Mapping[str, Factura] | None = None,
                        hashes_aprobados: frozenset[str] = frozenset()) -> list[Decision]:
    datos = facturas or {}
    salida = {d.file_id: d for d in decisiones}
    por_hash, por_pedido = defaultdict(list), defaultdict(list)
    copias = set()

    LECTURA_FALLIDA = "R0_lectura"
    # Si no nos creemos sus campos, tampoco su pedido: no puede bloquear a una factura que sí se leyó.
    no_fiables = {d.file_id for d in decisiones if any(not c.ok and c.regla == LECTURA_FALLIDA for c in d.comprobaciones)}

    def bloquear(file_id, regla, detalle, resultado, frase=""):
        """`frase` es cómo se cuenta en el motivo de una factura que cumplía la norma y escala por esto."""
        actual = salida[file_id]
        fallidas = {c.regla for c in actual.comprobaciones if not c.ok}
        # Un duplicado nunca rebaja lo ya decidido: gana el resultado más restrictivo.
        if GRAVEDAD[actual.resultado] > GRAVEDAD[resultado]:
            resultado = actual.resultado
        # Y tampoco convierte una duda en un incumplimiento probado.
        if fallidas & DUDA_REAL or (actual.resultado == Resultado.ESCALAR and fallidas & REVISION_PENDIENTE):
            resultado = Resultado.ESCALAR
        if actual.resultado != Resultado.PAGAR:
            motivo = f"{actual.motivo}; {detalle}"
        else:
            motivo = f"Cumple la norma; se escala porque {frase}" if frase else detalle
        salida[file_id] = replace(actual, resultado=resultado, motivo=motivo,
                                 comprobaciones=actual.comprobaciones + (Comprobacion(regla, False, detalle),))

    def original(grupo):
        return min(grupo, key=lambda fid: (datos[fid].fecha if fid in datos and datos[fid].fecha else date.max, fid))

    for d in decisiones:
        f = datos.get(d.file_id)
        sha = f.sha256.lower() if f else ""
        if re.fullmatch(r"[0-9a-f]{64}", sha):
            por_hash[sha].append(d.file_id)
            if sha in hashes_aprobados:
                bloquear(d.file_id, "R5_hash_previo", f"Documento ya aprobado en otro lote: SHA-256 {sha}", Resultado.NO_PAGAR)
        pedido = re.sub(r"[\s\u200b\ufeff]", "", d.pedido or (f.pedido if f else "") or "").upper()
        if pedido:
            por_pedido[pedido].append(d.file_id)

    for sha, grupo in por_hash.items():
        if len(grupo) < 2:
            continue
        primera = original(grupo)
        for fid in grupo:
            if fid != primera:
                copias.add(fid)
                bloquear(fid, "R5_copia_hash", f"Copia exacta de {primera}: SHA-256 {sha}", Resultado.NO_PAGAR)

    for pedido, grupo in por_pedido.items():
        candidatos = [fid for fid in grupo if fid not in copias]
        if len(candidatos) < 2:
            continue
        for fid in candidatos:
            if fid in no_fiables:
                otros = ", ".join(sorted(f for f in candidatos if f != fid))
                aviso = f"Pedido {pedido} también en {otros}; esta lectura falló y no bloquea a las demás"
                salida[fid] = replace(salida[fid], alertas=salida[fid].alertas + (aviso,))
        candidatos = [fid for fid in candidatos if fid not in no_fiables]
        if len(candidatos) < 2:
            continue
        documentos = [datos.get(fid) for fid in candidatos]
        identificables = all(f and f.nif and f.numero and f.fecha and f.total is not None and f.iban for f in documentos)
        identidades = {(f.nif, f.numero, f.total, normaliza_iban(f.iban)) for f in documentos if f} if identificables else set()
        if identificables and len(identidades) == 1:
            primera = original(candidatos)
            for fid in candidatos:
                if fid != primera:
                    bloquear(fid, "R5_reenvio", f"Reenvío de {primera}, pedido {pedido}", Resultado.NO_PAGAR)
        else:
            cuantas, lista = "dos" if len(candidatos) == 2 else "varias", ", ".join(sorted(candidatos))
            detalle = f"Pedido {pedido} en {cuantas} facturas sin original inequívoca: {lista}"
            frase = f"el pedido {pedido} está en {cuantas} facturas y no está claro cuál es la original: {lista}"
            for fid in candidatos:
                bloquear(fid, "R5_duplicado", detalle, Resultado.ESCALAR, frase)
    return [salida[d.file_id] for d in decisiones]
