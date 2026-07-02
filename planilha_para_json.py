#!/usr/bin/env python3
"""
Converte a planilha administrativa de moedas sociais para o dados.json do site.

Uso principal:
  python scripts/planilha_para_json.py csv-to-json modelo_moedas_sociais.csv dados.json

Uso direto com XLSX:
  python scripts/planilha_para_json.py xlsx-to-json planilha_validada.xlsx dados.json

Uso auxiliar para gerar um CSV editável a partir do JSON atual:
  python scripts/planilha_para_json.py json-to-csv dados.json modelo_moedas_sociais.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


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

CAMPOS_OBRIGATORIOS = [
    "id",
    "titulo",
    "data_inicio",
    "status",
    "principal_responsavel",
    "tipo_responsavel",
    "resumo",
    "link_acesso",
    "abrangencia",
    "palavras_chave",
    "fonte",
    "ultima_atualizacao",
]

STATUS_VALIDOS = {"ativa", "encerrada", "proposta", "suspensa", "desconhecida"}


def csv_to_json(csv_path: Path, json_path: Path) -> None:
    linhas = ler_csv(csv_path)
    registros = [normalizar_linha(linha, index + 2) for index, linha in enumerate(linhas)]
    validar_ids_unicos(registros)

    json_path.write_text(
        json.dumps(registros, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK: {len(registros)} registros exportados para {json_path}")


def xlsx_to_json(xlsx_path: Path, json_path: Path) -> None:
    linhas = ler_xlsx(xlsx_path)
    registros = [normalizar_linha(linha, index + 2) for index, linha in enumerate(linhas)]
    validar_ids_unicos(registros)

    json_path.write_text(
        json.dumps(registros, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK: {len(registros)} registros exportados para {json_path}")


def json_to_csv(json_path: Path, csv_path: Path) -> None:
    registros = json.loads(json_path.read_text(encoding="utf-8"))

    with csv_path.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=CAMPOS)
        writer.writeheader()
        for registro in registros:
            linha = {campo: serializar_celula(registro.get(campo)) for campo in CAMPOS}
            writer.writerow(linha)

    print(f"OK: {len(registros)} registros exportados para {csv_path}")


def ler_csv(csv_path: Path) -> list[dict[str, str]]:
    texto = csv_path.read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(texto[:4096], delimiters=",;")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as arquivo:
        reader = csv.DictReader(arquivo, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("O CSV não possui cabeçalho.")

        campos_faltando = [campo for campo in CAMPOS if campo not in reader.fieldnames]
        if campos_faltando:
            raise ValueError(f"Campos ausentes no CSV: {', '.join(campos_faltando)}")

        return list(reader)


def ler_xlsx(xlsx_path: Path) -> list[dict[str, str]]:
    namespaces = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    with zipfile.ZipFile(xlsx_path) as arquivo:
        shared_strings = ler_shared_strings(arquivo, namespaces)
        sheet_xml = arquivo.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_xml)
    linhas_matriz: list[list[str]] = []

    for row in root.findall(".//main:sheetData/main:row", namespaces):
        valores_por_coluna: dict[int, str] = {}
        for cell in row.findall("main:c", namespaces):
            referencia = cell.attrib.get("r", "")
            coluna = indice_coluna_excel(referencia)
            valores_por_coluna[coluna] = ler_celula_xlsx(cell, shared_strings, namespaces)

        if valores_por_coluna:
            max_coluna = max(valores_por_coluna)
            linhas_matriz.append([valores_por_coluna.get(i, "") for i in range(1, max_coluna + 1)])

    if not linhas_matriz:
        raise ValueError("O XLSX nÃ£o possui dados.")

    cabecalho = [limpar(valor) for valor in linhas_matriz[0]]
    campos_faltando = [campo for campo in CAMPOS if campo not in cabecalho]
    if campos_faltando:
        raise ValueError(f"Campos ausentes no XLSX: {', '.join(campos_faltando)}")

    registros: list[dict[str, str]] = []
    for valores in linhas_matriz[1:]:
        if not any(limpar(valor) for valor in valores):
            continue

        linha = {campo: "" for campo in cabecalho}
        for index, campo in enumerate(cabecalho):
            linha[campo] = valores[index] if index < len(valores) else ""
        registros.append(linha)

    return registros


def ler_shared_strings(arquivo: zipfile.ZipFile, namespaces: dict[str, str]) -> list[str]:
    if "xl/sharedStrings.xml" not in arquivo.namelist():
        return []

    root = ET.fromstring(arquivo.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("main:si", namespaces):
        partes = [texto.text or "" for texto in item.findall(".//main:t", namespaces)]
        strings.append("".join(partes))
    return strings


def ler_celula_xlsx(
    cell: ET.Element, shared_strings: list[str], namespaces: dict[str, str]
) -> str:
    tipo = cell.attrib.get("t")

    if tipo == "inlineStr":
        partes = [texto.text or "" for texto in cell.findall(".//main:t", namespaces)]
        return "".join(partes)

    valor = cell.find("main:v", namespaces)
    if valor is None or valor.text is None:
        return ""

    if tipo == "s":
        index = int(valor.text)
        return shared_strings[index] if index < len(shared_strings) else ""

    return valor.text


def indice_coluna_excel(referencia: str) -> int:
    letras = "".join(caractere for caractere in referencia if caractere.isalpha())
    indice = 0
    for letra in letras.upper():
        indice = indice * 26 + (ord(letra) - ord("A") + 1)
    return indice


def normalizar_linha(linha: dict[str, str], numero_linha: int) -> dict[str, Any]:
    registro: dict[str, Any] = {}

    for campo in CAMPOS:
        valor = limpar(linha.get(campo, ""))

        if campo in CAMPOS_OBRIGATORIOS and not valor:
            raise ValueError(f"Linha {numero_linha}: campo obrigatório vazio: {campo}")

        if campo in {"data_inicio", "data_fim", "ultima_atualizacao"}:
            data = normalizar_data(valor, numero_linha, campo)
            registro[campo] = data if campo != "data_fim" else data or None
        elif campo == "palavras_chave":
            registro[campo] = separar_lista(valor)
        elif campo in {"latitude", "longitude"}:
            registro[campo] = converter_float(valor, numero_linha, campo) if valor else None
        elif campo == "uf":
            registro[campo] = valor.upper()
        elif campo == "status":
            status = valor.lower()
            if status not in STATUS_VALIDOS:
                raise ValueError(
                    f"Linha {numero_linha}: status inválido '{valor}'. "
                    f"Use: {', '.join(sorted(STATUS_VALIDOS))}"
                )
            registro[campo] = status
        else:
            registro[campo] = valor

    return registro


def validar_ids_unicos(registros: list[dict[str, Any]]) -> None:
    vistos: set[str] = set()
    duplicados: set[str] = set()

    for registro in registros:
        item_id = registro["id"]
        if item_id in vistos:
            duplicados.add(item_id)
        vistos.add(item_id)

    if duplicados:
        raise ValueError(f"IDs duplicados: {', '.join(sorted(duplicados))}")


def limpar(valor: Any) -> str:
    return str(valor or "").strip()


def separar_lista(valor: str) -> list[str]:
    itens = [item.strip() for item in valor.replace("|", ";").split(";")]
    return [item for item in itens if item]


def converter_float(valor: str, numero_linha: int, campo: str) -> float:
    try:
        return float(valor.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Linha {numero_linha}: valor numérico inválido em {campo}: {valor}") from exc


def normalizar_data(valor: str, numero_linha: int, campo: str) -> str:
    if not valor:
        return ""

    match = re.match(r"^\d{4}-\d{2}-\d{2}", valor)
    if match:
        return match.group(0)

    try:
        serial = float(valor)
    except ValueError:
        return valor

    if serial <= 0:
        raise ValueError(f"Linha {numero_linha}: data invÃ¡lida em {campo}: {valor}")

    data = datetime(1899, 12, 30) + timedelta(days=serial)
    return data.strftime("%Y-%m-%d")


def serializar_celula(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, list):
        return "; ".join(str(item) for item in valor)
    return str(valor)


def main() -> None:
    parser = argparse.ArgumentParser(description="Converte CSV/JSON de moedas sociais.")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    csv_to_json_parser = subparsers.add_parser("csv-to-json", help="Converte CSV para dados.json")
    csv_to_json_parser.add_argument("csv", type=Path)
    csv_to_json_parser.add_argument("json", type=Path)

    xlsx_to_json_parser = subparsers.add_parser("xlsx-to-json", help="Converte XLSX para dados.json")
    xlsx_to_json_parser.add_argument("xlsx", type=Path)
    xlsx_to_json_parser.add_argument("json", type=Path)

    json_to_csv_parser = subparsers.add_parser("json-to-csv", help="Converte dados.json para CSV editável")
    json_to_csv_parser.add_argument("json", type=Path)
    json_to_csv_parser.add_argument("csv", type=Path)

    args = parser.parse_args()

    if args.comando == "csv-to-json":
        csv_to_json(args.csv, args.json)
    elif args.comando == "xlsx-to-json":
        xlsx_to_json(args.xlsx, args.json)
    elif args.comando == "json-to-csv":
        json_to_csv(args.json, args.csv)


if __name__ == "__main__":
    main()
