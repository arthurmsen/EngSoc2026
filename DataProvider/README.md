# DataProvider

Coletor MVP para buscar proposicoes legislativas federais sobre moedas sociais,
bancos comunitarios e economia solidaria, gerando uma planilha `.xlsx` para
validacao administrativa antes de qualquer mescla com `dados.json`.

## Uso

```powershell
python DataProvider\coletar_legislativo.py
```

Por padrao, o script consulta:

- Camara dos Deputados: `https://dadosabertos.camara.leg.br/api/v2/`
- Senado/Congresso: `https://legis.senado.leg.br/dadosabertos/processo`

E gera um arquivo em:

```text
DataProvider\outputs\dados_legislativos_YYYYMMDD_HHMMSS.xlsx
```

## Opcoes uteis

```powershell
python DataProvider\coletar_legislativo.py --fonte camara
python DataProvider\coletar_legislativo.py --fonte senado
python DataProvider\coletar_legislativo.py --termo "moeda social" --termo "banco comunitario"
python DataProvider\coletar_legislativo.py --ano-inicio 2020 --ano-fim 2026
python DataProvider\coletar_legislativo.py --limite-por-termo 50
```

## Observacoes

A planilha gerada usa as mesmas colunas do modelo administrativo:

`id titulo data_inicio data_fim status principal_responsavel tipo_responsavel resumo link_acesso uf cidade abrangencia palavras_chave fonte ultima_atualizacao latitude longitude`

Para apoiar visualizacao em mapa, o coletor tenta preencher `uf`, `latitude` e
`longitude` a partir do responsavel principal:

- Camara: consulta o detalhe do deputado autor e usa a UF do mandato.
- Senado/Congresso: extrai UF de autorias no formato `Nome (PARTIDO/UF)`.

As coordenadas usam um mapeamento interno `UF -> latitude/longitude` baseado nas
capitais como ponto representativo. Portanto, esses campos indicam a UF de
representacao/autoria da proposta, nao necessariamente o territorio de execucao
da politica publica. `cidade` continua vazio no resultado bruto.
