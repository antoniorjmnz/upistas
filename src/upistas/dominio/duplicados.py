import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from datetime import date

from upistas.dominio.importes import normaliza_iban
from upistas.dominio.modelos import Comprobacion, Decision, Factura, Resultado


def resolver_duplicados(decisiones: list[Decision], facturas: Mapping[str, Factura] | None = None,
                        hashes_aprobados: frozenset[str] = frozenset()) -> list[Decision]:
    datos = facturas or {}
    salida = {d.file_id: d for d in decisiones}
    por_hash, por_pedido = defaultdict(list), defaultdict(list)
    copias = set()

    def bloquear(file_id, regla, detalle, resultado):
        actual = salida[file_id]
        if resultado == Resultado.ESCALAR and actual.resultado == Resultado.NO_PAGAR:
            if not actual.comprobaciones or any(not c.ok and c.regla in (
                "R5_no_pagada", "R5_hash_previo", "R5_copia_hash", "R5_reenvio",
            ) for c in actual.comprobaciones):
                resultado = Resultado.NO_PAGAR
        motivo = detalle if actual.resultado == Resultado.PAGAR else f"{actual.motivo}; {detalle}"
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
        documentos = [datos.get(fid) for fid in candidatos]
        identificables = all(f and f.nif and f.numero and f.fecha and f.total is not None and f.iban for f in documentos)
        identidades = {(f.nif, f.numero, f.total, normaliza_iban(f.iban)) for f in documentos if f} if identificables else set()
        if identificables and len(identidades) == 1:
            primera = original(candidatos)
            for fid in candidatos:
                if fid != primera:
                    bloquear(fid, "R5_reenvio", f"Reenvío de {primera}, pedido {pedido}", Resultado.NO_PAGAR)
        else:
            detalle = f"Pedido duplicado {pedido} sin original inequívoca: " + ", ".join(sorted(candidatos))
            for fid in candidatos:
                bloquear(fid, "R5_duplicado", detalle, Resultado.ESCALAR)
    return [salida[d.file_id] for d in decisiones]
