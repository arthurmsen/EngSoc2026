#!/usr/bin/env python3
"""
Coleta dados legislativos sobre moedas sociais e gera uma planilha XLSX.

Este script nao altera dados.json. Ele cria uma planilha de candidatos para o
fluxo: Planilha -> administrador/validacao -> JSON.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


CAMPOS = [
    "id",
    "titulo",
    "data_inicio",
    "data_fim",
    "status",
    "principal_responsavel",
    "tipo_responsavel",
    "resumo",
    "link_acesso",
    "uf",
    "cidade",
    "abrangencia",
    "palavras_chave",
    "fonte",
    "ultima_atualizacao",
    "latitude",
    "longitude",
]

TERMOS_PADRAO = [
    "moeda social",
    "moedas sociais",
    "banco comunitario",
    "banco comunitário",
    "bancos comunitarios",
    "bancos comunitários",
    "economia solidaria",
    "economia solidária",
    "financas solidarias",
    "finanças solidárias",
    "moeda complementar",
]

CAMARA_BASE = "https://dadosabertos.camara.leg.br/api/v2"
SENADO_PROCESSO_URL = "https://legis.senado.leg.br/dadosabertos/processo"
SENADO_DETALHE_URL = "https://legis.senado.leg.br/dadosabertos/processo/{id}"

UF_COORDENADAS = {
    "AC": (-9.97499, -67.82430),
    "AL": (-9.66599, -35.73500),
    "AM": (-3.10194, -60.02500),
    "AP": (0.03493, -51.06939),
    "BA": (-12.97111, -38.51083),
    "CE": (-3.71722, -38.54306),
    "DF": (-15.79389, -47.88278),
    "ES": (-20.31550, -40.31280),
    "GO": (-16.68639, -49.26444),
    "MA": (-2.53073, -44.30680),
    "MG": (-19.92083, -43.93778),
    "MS": (-20.44278, -54.64639),
    "MT": (-15.59889, -56.09489),
    "PA": (-1.45583, -48.50389),
    "PB": (-7.11500, -34.86306),
    "PE": (-8.05389, -34.88111),
    "PI": (-5.08917, -42.80194),
    "PR": (-25.42972, -49.27194),
    "RJ": (-22.90685, -43.17290),
    "RN": (-5.79500, -35.20944),
    "RO": (-8.76194, -63.90389),
    "RR": (2.81972, -60.67333),
    "RS": (-30.03306, -51.23000),
    "SC": (-27.59350, -48.55854),
    "SE": (-10.91111, -37.07167),
    "SP": (-23.55052, -46.63331),
    "TO": (-10.18444, -48.33361),
}

UFS_VALIDAS = set(UF_COORDENADAS)


@dataclass
class Config:
    termos: list[str]
    fonte: str
    ano_inicio: int
    ano_fim: int
    limite_por_termo: int
    output: Path | None
    pausa: float


def main() -> None:
    config = parse_args()
    registros: list[dict[str, Any]] = []

    if config.fonte in {"camara", "ambas"}:
        registros.extend(coletar_camara(config))

    if config.fonte in {"senado", "ambas"}:
        registros.extend(coletar_senado(config))

    registros = deduplicar(registros)
    output = config.output or caminho_saida_padrao()
    escrever_xlsx(output, registros)

    print(f"OK: {len(registros)} registros exportados para {output}")


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Coleta proposicoes legislativas e gera planilha XLSX para validacao."
    )
    parser.add_argument(
        "--termo",
        action="append",
        dest="termos",
        help="Termo de busca. Pode ser informado mais de uma vez.",
    )
    parser.add_argument(
        "--fonte",
        choices=["camara", "senado", "ambas"],
        default="ambas",
        help="Fonte a consultar. Padrao: ambas.",
    )
    parser.add_argument("--ano-inicio", type=int, default=2020)
    parser.add_argument("--ano-fim", type=int, default=datetime.now().year)
    parser.add_argument(
        "--limite-por-termo",
        type=int,
        default=100,
        help="Limite de registros por termo e fonte. Use 0 para sem limite pratico.",
    )
    parser.add_argument("--output", type=Path, help="Caminho do XLSX de saida.")
    parser.add_argument(
        "--pausa",
        type=float,
        default=0.12,
        help="Pausa entre chamadas HTTP, em segundos.",
    )
    args = parser.parse_args()

    termos = normalizar_termos(args.termos or TERMOS_PADRAO)
    return Config(
        termos=termos,
        fonte=args.fonte,
        ano_inicio=args.ano_inicio,
        ano_fim=args.ano_fim,
        limite_por_termo=args.limite_por_termo,
        output=args.output,
        pausa=args.pausa,
    )


def coletar_camara(config: Config) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    cache_deputados: dict[str, dict[str, Any]] = {}

    for termo in config.termos:
        print(f"Camara: buscando '{termo}'")
        encontrados = buscar_camara_por_termo(termo, config)
        for item in encontrados:
            detalhe = request_json(f"{CAMARA_BASE}/proposicoes/{item['id']}")
            autores = request_json(f"{CAMARA_BASE}/proposicoes/{item['id']}/autores")
            time.sleep(config.pausa)

            dados = detalhe.get("dados", {})
            autores_dados = autores.get("dados", [])
            uf_autor = obter_uf_autor_camara(autores_dados, cache_deputados, config.pausa)
            registros.append(normalizar_camara(dados, autores_dados, termo, uf_autor))

    return registros


def buscar_camara_por_termo(termo: str, config: Config) -> list[dict[str, Any]]:
    resultados: list[dict[str, Any]] = []
    pagina = 1
    limite = config.limite_por_termo or 10_000

    while len(resultados) < limite:
        params = {
            "keywords": termo,
            "itens": 100,
            "pagina": pagina,
            "ordem": "DESC",
            "ordenarPor": "id",
        }
        data = request_json(f"{CAMARA_BASE}/proposicoes?{urllib.parse.urlencode(params)}")
        itens = data.get("dados", [])
        if not itens:
            break

        for item in itens:
            ano = int(item.get("ano") or 0)
            if config.ano_inicio <= ano <= config.ano_fim:
                resultados.append(item)
                if len(resultados) >= limite:
                    break

        links = {link.get("rel"): link.get("href") for link in data.get("links", [])}
        if "next" not in links or len(itens) < 100:
            break
        pagina += 1
        time.sleep(config.pausa)

    return resultados


def normalizar_camara(
    dados: dict[str, Any], autores: list[dict[str, Any]], termo: str, uf_autor: str
) -> dict[str, Any]:
    identificacao = montar_identificacao(
        dados.get("siglaTipo"), dados.get("numero"), dados.get("ano")
    )
    status_api = dados.get("statusProposicao") or {}
    situacao = texto(status_api.get("descricaoSituacao"))
    ultima_atualizacao = data_curta(status_api.get("dataHora")) or data_curta(
        dados.get("dataApresentacao")
    )
    status = classificar_status_camara(situacao, status_api.get("descricaoTramitacao"))
    autor = autores[0] if autores else {}
    palavras = palavras_relevantes([termo, dados.get("keywords"), dados.get("ementa")])
    latitude, longitude = coordenadas_uf(uf_autor)

    return {
        "id": f"camara-{dados.get('id')}",
        "titulo": identificacao,
        "data_inicio": data_curta(dados.get("dataApresentacao")),
        "data_fim": ultima_atualizacao if status == "encerrada" else "",
        "status": status,
        "principal_responsavel": texto(autor.get("nome")) or "Nao informado",
        "tipo_responsavel": texto(autor.get("tipo")) or "Nao informado",
        "resumo": texto(dados.get("ementa")),
        "link_acesso": texto(dados.get("urlInteiroTeor")) or texto(dados.get("uri")),
        "uf": uf_autor,
        "cidade": "",
        "abrangencia": "federal",
        "palavras_chave": "; ".join(palavras),
        "fonte": "Camara dos Deputados - Dados Abertos",
        "ultima_atualizacao": ultima_atualizacao,
        "latitude": latitude,
        "longitude": longitude,
    }


def coletar_senado(config: Config) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    termos_regex = compilar_termos(config.termos)
    por_termo = {termo: 0 for termo in config.termos}
    limite = config.limite_por_termo or 10_000

    for ano in range(config.ano_inicio, config.ano_fim + 1):
        print(f"Senado: buscando processos apresentados em {ano}")
        params = {
            "dataInicioApresentacao": f"{ano}-01-01",
            "dataFimApresentacao": f"{ano}-12-31",
        }
        data = request_json(f"{SENADO_PROCESSO_URL}?{urllib.parse.urlencode(params)}")
        for item in lista_senado(data):
            texto_busca = " ".join(
                [
                    texto(item.get("identificacao")),
                    texto(item.get("ementa")),
                    texto(item.get("tipoConteudo")),
                    texto(item.get("tipoDocumento")),
                ]
            )
            termos_encontrados = termos_que_batem(texto_busca, termos_regex)
            if not termos_encontrados:
                continue
            if all(por_termo[termo] >= limite for termo in termos_encontrados):
                continue

            for termo in termos_encontrados:
                por_termo[termo] += 1

            registros.append(normalizar_senado(item, termos_encontrados))

        time.sleep(config.pausa)

    return registros


def normalizar_senado(item: dict[str, Any], termos: list[str]) -> dict[str, Any]:
    tramitando = texto(item.get("tramitando")).lower()
    situacao = texto(item.get("situacaoAtual"))
    status = "proposta" if tramitando == "sim" else "encerrada"
    ultima_atualizacao = data_curta(item.get("dataUltimaAtualizacao")) or data_curta(
        item.get("dataSituacaoAtual")
    )
    autoria = texto(item.get("autoria")) or "Nao informado"
    uf_autor = extrair_uf_autoria(autoria)
    latitude, longitude = coordenadas_uf(uf_autor)

    return {
        "id": f"senado-{item.get('id')}",
        "titulo": texto(item.get("identificacao")),
        "data_inicio": data_curta(item.get("dataApresentacao")),
        "data_fim": data_curta(item.get("dataSituacaoAtual")) if status == "encerrada" else "",
        "status": status,
        "principal_responsavel": autoria,
        "tipo_responsavel": texto(item.get("tipoDocumento")) or "Nao informado",
        "resumo": texto(item.get("ementa")),
        "link_acesso": texto(item.get("urlDocumento"))
        or SENADO_DETALHE_URL.format(id=item.get("id")),
        "uf": uf_autor,
        "cidade": "",
        "abrangencia": "federal",
        "palavras_chave": "; ".join(sorted(set(termos))),
        "fonte": "Senado/Congresso - Dados Abertos",
        "ultima_atualizacao": ultima_atualizacao,
        "latitude": latitude,
        "longitude": longitude,
    }


def request_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "DataProvider-Moedas-Sociais/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read().decode(charset)
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro HTTP {exc.code} em {url}: {body[:500]}") from exc


def lista_senado(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        value = data.get("value", [])
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def obter_uf_autor_camara(
    autores: list[dict[str, Any]], cache_deputados: dict[str, dict[str, Any]], pausa: float
) -> str:
    if not autores:
        return ""

    autor = autores[0]
    uri = texto(autor.get("uri"))
    tipo = texto(autor.get("tipo")).lower()
    if "deput" not in tipo or not uri:
        return ""

    if uri not in cache_deputados:
        detalhe = request_json(uri)
        cache_deputados[uri] = detalhe.get("dados", {}) if isinstance(detalhe, dict) else {}
        time.sleep(pausa)

    dados = cache_deputados.get(uri, {})
    ultimo_status = dados.get("ultimoStatus") or {}
    uf = texto(ultimo_status.get("siglaUf")).upper()
    return uf if uf in UFS_VALIDAS else ""


def extrair_uf_autoria(autoria: str) -> str:
    for match in re.finditer(r"[/\-]([A-Z]{2})(?:\)|,|\s|$)", autoria.upper()):
        uf = match.group(1)
        if uf in UFS_VALIDAS:
            return uf
    return ""


def coordenadas_uf(uf: str) -> tuple[str | float, str | float]:
    if uf not in UF_COORDENADAS:
        return "", ""
    return UF_COORDENADAS[uf]


def escrever_xlsx(path: Path, registros: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    linhas = [CAMPOS] + [[registro.get(campo, "") for campo in CAMPOS] for registro in registros]

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as xlsx:
        xlsx.writestr("[Content_Types].xml", content_types_xml())
        xlsx.writestr("_rels/.rels", rels_xml())
        xlsx.writestr("xl/workbook.xml", workbook_xml())
        xlsx.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml())
        xlsx.writestr("xl/styles.xml", styles_xml())
        xlsx.writestr("xl/worksheets/sheet1.xml", sheet_xml(linhas))
        xlsx.writestr("docProps/core.xml", core_xml())
        xlsx.writestr("docProps/app.xml", app_xml())


def sheet_xml(linhas: list[list[Any]]) -> str:
    rows = []
    widths = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(
            [18, 22, 13, 13, 13, 28, 20, 70, 52, 8, 18, 14, 35, 28, 18, 12, 12],
            start=1,
        )
    )

    for row_idx, linha in enumerate(linhas, start=1):
        cells = []
        style = 1 if row_idx == 1 else 2
        for col_idx, valor in enumerate(linha, start=1):
            ref = f"{coluna_excel(col_idx)}{row_idx}"
            cells.append(celula_xml(ref, valor, style))
        rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <cols>{widths}</cols>
  <sheetData>{"".join(rows)}</sheetData>
  <autoFilter ref="A1:Q{max(len(linhas), 1)}"/>
</worksheet>'''


def celula_xml(ref: str, valor: Any, style: int) -> str:
    if valor is None:
        valor = ""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return f'<c r="{ref}" s="{style}"><v>{valor}</v></c>'
    valor_texto = escape(str(valor))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{valor_texto}</t></is></c>'


def content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""


def rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def workbook_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="dados_extraidos" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""


def workbook_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>
    <font><sz val="10"/><name val="Calibri"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFD9E2EC"/></left><right style="thin"><color rgb="FFD9E2EC"/></right><top style="thin"><color rgb="FFD9E2EC"/></top><bottom style="thin"><color rgb="FFD9E2EC"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
  </cellXfs>
</styleSheet>"""


def core_xml() -> str:
    agora = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>DataProvider</dc:creator>
  <cp:lastModifiedBy>DataProvider</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{agora}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{agora}</dcterms:modified>
</cp:coreProperties>"""


def app_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>DataProvider</Application>
</Properties>"""


def deduplicar(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vistos: dict[str, dict[str, Any]] = {}
    for registro in registros:
        chave = texto(registro.get("id"))
        if not chave:
            continue
        if chave in vistos:
            antigas = set(separar_palavras(vistos[chave].get("palavras_chave")))
            novas = set(separar_palavras(registro.get("palavras_chave")))
            vistos[chave]["palavras_chave"] = "; ".join(sorted(antigas | novas))
        else:
            vistos[chave] = registro
    return sorted(vistos.values(), key=lambda item: (item.get("fonte", ""), item.get("titulo", "")))


def caminho_saida_padrao() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "outputs" / f"dados_legislativos_{timestamp}.xlsx"


def montar_identificacao(sigla: Any, numero: Any, ano: Any) -> str:
    partes = [texto(sigla), texto(numero), texto(ano)]
    return " ".join(parte for parte in partes if parte)


def classificar_status_camara(situacao: str, tramitacao: Any) -> str:
    base = f"{situacao} {texto(tramitacao)}".lower()
    if any(palavra in base for palavra in ["arquivad", "transformad", "prejudicad", "retirad"]):
        return "encerrada"
    if any(palavra in base for palavra in ["aguardando", "tramitando", "pronta", "relatoria"]):
        return "proposta"
    return "desconhecida"


def palavras_relevantes(valores: list[Any]) -> list[str]:
    palavras: list[str] = []
    for valor in valores:
        for parte in separar_palavras(valor):
            if parte and parte.lower() not in {p.lower() for p in palavras}:
                palavras.append(parte)
    return palavras[:12]


def separar_palavras(valor: Any) -> list[str]:
    if not valor:
        return []
    bruto = re.split(r"[;,|]", texto(valor))
    return [item.strip() for item in bruto if item.strip()]


def normalizar_termos(termos: list[str]) -> list[str]:
    vistos: set[str] = set()
    saida: list[str] = []
    for termo in termos:
        termo_limpo = termo.strip()
        chave = termo_limpo.lower()
        if termo_limpo and chave not in vistos:
            vistos.add(chave)
            saida.append(termo_limpo)
    return saida


def compilar_termos(termos: list[str]) -> dict[str, re.Pattern[str]]:
    return {
        termo: re.compile(r"\b" + re.escape(remover_acentos(termo).lower()) + r"\b")
        for termo in termos
    }


def termos_que_batem(texto_busca: str, termos_regex: dict[str, re.Pattern[str]]) -> list[str]:
    normalizado = remover_acentos(texto_busca).lower()
    return [termo for termo, regex in termos_regex.items() if regex.search(normalizado)]


def remover_acentos(valor: str) -> str:
    mapa = str.maketrans(
        "áàãâäéèêëíìîïóòõôöúùûüçÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇ",
        "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC",
    )
    return valor.translate(mapa)


def data_curta(valor: Any) -> str:
    valor_texto = texto(valor)
    if not valor_texto:
        return ""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", valor_texto)
    return match.group(1) if match else valor_texto


def texto(valor: Any) -> str:
    if valor is None:
        return ""
    return html.unescape(str(valor)).strip()


def coluna_excel(indice: int) -> str:
    letras = ""
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


if __name__ == "__main__":
    main()
