# Relatório de conhecimento — integração Corprint

Documento de referência para reutilizar este projeto em **outra integração**, possivelmente com outro padrão de comunicação no destino.

Origem deste código: pasta `corprint`, copiada de `hevi-integracao`, adaptada para o cliente **Corprint da Amazônia Gráfica e Editora Ltda**.

**Última sincronização com o projeto corprint:** 03/09/2026 — inclui afastamentos e demissões com `campo_chave=cpf` (sem coluna matrícula), filtro de empresa, `[MODULOS]`, `[AFASTAMENTOS]` e lista `funcionarios_ignorar.txt`.

---

## 1. O que esta integração faz

Lê dados de RH na **API eContador (Alterdata Pack)** e envia para o **ifPonto / iFractal** via **REST** (CSV multipart).

Fluxo padrão:

```
eContador (JSON:API)  →  CSV local (; / utf-8-sig)  →  POST REST iFractal
```

Orquestrador: `main.py` (também chamado por `integrador.sh` no cron).

Sequência:

1. Empresas
2. Departamentos
3. Cargos
4. Funcionários
5. Afastamentos (inclui férias como tipo 1011)
6. Demissões

Cada módulo pode ser ligado/desligado em `[MODULOS]` no `.config`.

---

## 2. Arquivos essenciais (o que está nesta pasta)

| Arquivo | Papel |
|---------|--------|
| `main.py` | Orquestra os módulos na ordem acima |
| `config_reader.py` | Lê `.config`: token origem, filtros, módulos, códigos de afastamento |
| `empresas.py` | Lista empresas ativas e envia CSV |
| `departamentos.py` | Extrai departamentos a partir dos funcionários |
| `cargos.py` | Extrai cargos/funções a partir dos funcionários |
| `funcionarios.py` | Coleta ativos, gera CSV, envia REST |
| `afastamentos.py` | Coleta afastamentos (exceto férias no CSV), envia REST |
| `demissoes.py` | Coleta demitidos, gera CSV, envia REST (SOAP legado existe no mesmo arquivo) |
| `integrador.sh` | Ativa `.venv` e executa `main.py` (uso em cron) |
| `.config.exemplo` | Modelo de configuração **sem senhas** — copiar para `.config` |
| `funcionarios_ignorar.txt` | Lista de CPF a excluir do CSV de funcionários |
| `requirements.txt` | `requests`, `pandas`, `pytz` |

**Não copiados de propósito** (não são necessários para o fluxo principal):

- `demissoes_rest.py` — variante antiga (histórico por CPF); o `main.py` usa `demissoes.py`
- `ferias.py` — módulo separado; o `main.py` não o chama (férias são tratadas em `afastamentos.py` como tipo 1011, mas **não** vão no CSV de afastamento)
- Scripts de diagnóstico: `consulta_funcionarios_ativos.py`, `relatorio_funcionarios_demitidos.py`
- CSVs gerados (`*_api.csv`), logs, JSON de detalhe, PDF de requisitos
- `.config` real — contém token JWT, `token_base` e senha SOAP

---

## 3. Arquitetura

```
                    [APISOURCE] JWT Bearer
                    https://dp.pack.alterdata.com.br/api/v1/...
                              |
                         módulos Python
                              |
                    CSV local (*_api.csv)
                              |
                    [APITARGET] REST
                    SHA256(token_base + DD/MM/YYYY America/Sao_Paulo)
                    POST multipart: pag + cmd=importar_cad + separador=; + arquivo
                              |
                    https://stou.ifractal.com.br/<cliente>/rest/
```

Há também `[SOAP]` (`ws_ifPonto.php`) usado só no caminho legado `python demissoes.py soap`. O fluxo do cron é **REST**.

---

## 4. API origem — eContador / Alterdata

### Autenticação

Header:

```
Content-Type: application/vnd.api+json
Authorization: Bearer <token JWT da seção [APISOURCE]>
```

O token é estático no `.config` (não é gerado pelo script). Se expirar, precisa atualizar no arquivo.

### Endpoints usados

Base: `https://dp.pack.alterdata.com.br/api/v1`

| Recurso | Caminho | Filtros típicos |
|---------|---------|-----------------|
| Empresas | `/empresas` | `filter[empresas][ativa][EQ]=true` |
| Detalhe empresa | `/empresas/{id}` | — |
| Funcionários | `/funcionarios` | `filter[status]=ativo` ou `demitido`; `filter[empresa.id]={id}` |
| Empresa do funcionário | `/funcionarios/{id}/empresa` | — |
| Departamento do funcionário | `/funcionarios/{id}/departamento` (via relacionamento) | — |

Paginação: seguir `links.next` da resposta JSON:API. **Não** usar `page[number]` — a API responde 400.

### Empresa Corprint (referência)

| Campo | Valor |
|-------|--------|
| `id` (usar em `codigo_empresa`) | `129` |
| Nome | CORPRINT DA AMAZONIA GRAFICA E EDITORA LTDA |
| `externoid` | `00620` |
| CNPJ | 07.519.331/0001-81 |

O campo `codigo` da listagem de empresas vem vazio; o identificador estável é o `id`.

### Particularidade importante da origem

A mesma matrícula (`attributes.codigo`) pode existir **duas vezes**:

- um cadastro `status=Ativo`
- outro `status=Demitido` (vínculo antigo / readmissão)

O CSV de funcionários usa só `filter[status]=ativo`. Por isso alguém “demitido na planilha do cliente” ainda pode aparecer no CSV se houver vínculo ativo na API.

Não existe endpoint `/tipos-afastamento`. O tipo vem só no texto `afastamentodescricao`.

---

## 5. API destino — iFractal / ifPonto REST

### Geração do token (crítico)

```
data_atual  = agora em America/Sao_Paulo no formato DD/MM/YYYY  (com zeros)
token_final = SHA256( token_base + data_atual )   # hex, sem separador
```

Exemplo Python:

```python
import hashlib
from datetime import datetime
import pytz

tz = pytz.timezone("America/Sao_Paulo")
data_atual = datetime.now(tz).strftime("%d/%m/%Y")
token_final = hashlib.sha256((token_base + data_atual).encode("utf-8")).hexdigest()
```

Erros clássicos de login: timezone UTC, data sem zero (`1/8/2026`), `token_base` errado.

### Headers (não é Bearer)

```
user:  <APITARGET.integracao>     # ex.: gotech
token: <token_final sha256>
```

### Body multipart

| Campo | Valor |
|-------|--------|
| `pag` | depende do módulo (tabela abaixo) |
| `cmd` | `importar_cad` |
| `separador` | `;` |
| `arquivo` | CSV (`text/csv`) |

### `pag` por módulo

| Módulo | `pag` |
|--------|--------|
| Empresas | `configuracao_empresa` |
| Departamentos | `configuracao_depto` |
| Cargos | `configuracao_cargo` |
| Funcionários | `funcionario_cadastrar` |
| Afastamentos | `ponto_afastamento` |
| Demissões | `funcionario_demissao` (sobrescreve com `[APITARGET] pag_demissao`) |

### Resposta

HTTP 200 **não basta**. Interpretar JSON:

```json
{ "success": true, "ok": 10, "ja_cad": 2, "erros": [], "info": "..." }
```

- `success == false` → falha (login/token/layout)
- `success == true` → sucesso do módulo, mesmo com avisos em `erros[]`
- `ok` cadastrados agora; `ja_cad` já existiam

---

## 6. Configuração (`.config`)

Copiar `.config.exemplo` → `.config`.

### `[APISOURCE]`

Token JWT da Alterdata.

### `[FILTROS]`

| Chave | Efeito |
|-------|--------|
| `codigo_empresa` | ID eContador. Aplicado em `funcionarios.py` e `afastamentos.py`. Demissões **ainda não filtram** por empresa na API |
| `historico_demissoes` | `true` = lê/grava `demissoes_matricula_processados.txt`. `false` = reprocessa tudo. Também aceito em `[MODULOS]` por compatibilidade |

### `[MODULOS]`

`true`/`false` por módulo. O `main.py` **pula** o que estiver `false` (não chama a API).

Atenção: `python empresas.py` direto **ignora** esse flag. Só o `main.py` / `integrador.sh` respeitam.

### `[AFASTAMENTOS]`

Mapa descrição eContador → código ifPonto (`ID-AFASTAMENTO`):

| Tipo | Código padrão |
|------|----------------|
| Férias | 1011 |
| Atestado | 1012 |
| Benefício | 1013 |
| Licença remunerada | 1014 |
| Salário maternidade | 1015 |
| S.A.T | 1016 |
| Suspensão de contrato | 1017 |
| Licença sem remuneração | 1018 |
| Aposentadoria por invalidez | 1019 |
| Serviço militar | 1020 |
| Licença paternidade | 1021 |
| Outros / desconhecido | 1022 (`codigo_padrao`) |

### `[APITARGET]`

`url`, `integracao` (header `user`), `token_base`.

`campo_chave = cpf` — usado no CSV de **demissões e afastamentos** (o ifPonto identifica o funcionário pelo CPF). Sem essa chave, o código assume `cpf`.

### `[SOAP]`

Só para `python demissoes.py soap`.

---

## 7. Comportamento de cada módulo

### Empresas (`empresas.py`)

- GET empresas ativas (paginado).
- Para cada uma, GET detalhe `/empresas/{id}`.
- CSV: `codigo_legado`, `campo_chave`, `nro`, `nome`, `cnpj`, endereço, etc.
- POST `configuracao_empresa`.
- Na Corprint costuma ficar **desligado** (`empresas = false`): o token origem vê **centenas** de empresas do escritório, não só a Corprint.

### Departamentos (`departamentos.py`)

Não há endpoint confiável de departamentos. O código percorre funcionários ativos com `include=departamento,empresa` e monta o conjunto único.

CSV: `campo_chave`, `codigo_legado`, `nome`, `conta`, `id-empresa`.

### Cargos (`cargos.py`)

Mesma ideia: extrai `nomefuncao` dos funcionários. CSV: `campo_chave`, `codigo_legado`, `nome`, `id-empresa`.

### Funcionários (`funcionarios.py`)

- `filter[status]=ativo` + `filter[empresa.id]` se `[FILTROS].codigo_empresa` estiver preenchido.
- Ignora CPF listados em `funcionarios_ignorar.txt` (`CPF;NOME`).
- Matrícula = `attributes.codigo` com 6 dígitos.
- Senha padrão enviada: `Ponto123`.
- Login/crachá = CPF 11 dígitos.
- POST `funcionario_cadastrar`.
- Comandos: `python funcionarios.py csv` (só arquivo) ou `python funcionarios.py integracao` (CSV + envio). Sem argumento = só CSV.

### Afastamentos (`afastamentos.py`)

- Lê `afastamento` (início), `retorno` (fim), `afastamentodescricao` e `cpf`.
- Mapeia descrição → código via `[AFASTAMENTOS]` (férias = 1011, atestado = 1012, etc.).
- CSV **sem coluna matrícula**: `campo_chave` = `cpf` e coluna `cpf` com 11 dígitos.
- Inclui férias no CSV (tipo 1011).
- Aplica `filter[empresa.id]` se `[FILTROS].codigo_empresa` estiver preenchido.
- POST `ponto_afastamento`.

### Demissões (`demissoes.py`)

- `filter[status]=demitido`.
- Recorta a partir de `2025-01-01` (`filtrar_demissoes_recentes`).
- CSV **sem coluna matrícula**. `campo_chave` = `cpf` (configurável em `[APITARGET] campo_chave`).
- Histórico interno: `demissoes_matricula_processados.txt` (uma matrícula por linha, não vai no CSV). Só grava **depois** do POST REST com sucesso. Liga/desliga com `historico_demissoes`.
- Se o histórico estiver ligado e a matrícula já existir, **não envia**.
- POST `funcionario_demissao`.
- **Não aplica** filtro de empresa hoje — puxa demitidos de **todas** as empresas do token, a menos que se altere o código.
- Comandos: `csv`, `enviar`, `soap`, ou sem argumento = REST completo.

---

## 8. Layouts de CSV (destino ifPonto)

Separador `;`, encoding `utf-8-sig`.

### Funcionários (principais)

`nome`, `cpf`, `matricula`, `rg`, `pis`, `dtadmissao`, `email`, endereço, `login`, `cod_empresa`, `codigo_legado_empresa`, `salario`, `dtnascimento`, `sexo`, `codigo_unidade`, `nome_unidade`, `codigo_cargo`, `nome_cargo`, `senha`, `cracha`, `empresa`, `nome_funcao`, centro de custo, etc.

### Afastamentos

`id-afastamento`, `dtinicio`, `dtfim`, `obs`, `campo_chave`, `cpf`  
Chave padrão: **`cpf`**. Não envia coluna `matricula`.

### Demissões

`campo_chave`, `cpf`, `nome`, `DATA_DEMISSAO`, `obs`, `data_aviso`, `data_ultimo_dia_trabalhado`, `data_acerto`, `motivo`, …  
Chave padrão: **`cpf`**. Não envia coluna `matricula`.

---

## 9. Execução e deploy

### Local

```bash
cp .config.exemplo .config   # preencher credenciais
pip install -r requirements.txt
python funcionarios.py csv
python main.py
```

### Servidor (referência Corprint)

Pasta: `/home/gogotech/integracao/corprint`

Cron (a cada 30 min, com lock):

```cron
*/30 * * * * cd /home/gogotech/integracao/corprint && flock -n /tmp/integrador_corprint.lock ./integrador.sh >> /home/gogotech/integracao/corprint/integrador.log 2>&1
```

`chmod +x integrador.sh`. O script faz `cd` para a própria pasta, exige `.config` e usa `.venv/bin/python` se existir.

Git: o `.config` **não** vai no repositório. Depois de `git pull`, conferir seções novas (`[MODULOS]`, `[FILTROS]`, `[AFASTAMENTOS]`).

---

## 10. Lições já aprendidas (não repetir)

1. **Não ligar `empresas` sem filtro** — o token do escritório vê ~367 empresas.
2. **`historico_demissoes` tem que ser lido onde foi gravado** — se colocar só em `[MODULOS]`, o código antigo ignorava e o histórico continuava ativo. Hoje lê `[FILTROS]` e `[MODULOS]`.
3. **Cron vs manual**: o `integrador.sh` é o mesmo. Se o cron “não manda demissão”, na prática o módulo rodou e pulou o POST porque as matrículas já estavam no `.txt`.
4. **Git “dubious ownership”**: não rodar `git pull` como `root` na pasta do `gogotech`; ou `chown` + `safe.directory`.
5. **Readmissão**: ativo + demitido na mesma matrícula. O CSV de ativos está correto do ponto de vista da API.
6. **Lista de exclusão** (`funcionarios_ignorar.txt`) é o jeito operacional de tirar gente do CSV sem mudar código.
7. Códigos 1011/1012 são do **ifPonto**, não da eContador. Novos tipos precisam existir no cadastro do ponto **e** no `[AFASTAMENTOS]`.

---

## 11. Como usar esta pasta em uma nova integração (outro padrão de comunicação)

O que **reaproveitar de verdade**:

- Coleta da origem (`obter_headers_api`, paginação `links.next`, filtros JSON:API).
- Mapeamento eContador → estrutura interna (matrícula 6 dígitos, CPF 11, datas `DD/MM/YYYY`).
- `config_reader.py` + `.config` (módulos, empresa, ignore list).
- `main.py` como orquestrador e `integrador.sh` para cron.

O que **trocar** se o destino não for iFractal REST:

- `gerar_token_target()` (SHA256 + data) e headers `user`/`token`.
- POST multipart (`pag`, `cmd=importar_cad`, `separador`).
- Layouts de CSV (colunas ifPonto).
- Seção `[APITARGET]` / `[SOAP]`.

Sugestão de desenho para o projeto 2:

1. Manter os módulos de **coleta** (origem).
2. Isolar um `destino.py` (ou pasta `destino/`) com: autenticar, transformar, enviar.
3. Cada módulo de negócio chama `destino.enviar(tipo, registros)` em vez de POST iFractal direto.
4. Copiar `.config.exemplo`, preencher origem e o novo destino.

Dependências mínimas: `requests`, `pandas`, `pytz`. `configparser` é da biblioteca padrão.

---

## 12. Comandos úteis

```bash
python funcionarios.py csv          # só CSV, sem envio
python funcionarios.py integracao   # CSV + REST
python afastamentos.py csv
python demissoes.py csv
python demissoes.py                 # coleta + REST
python main.py                      # tudo que estiver true em [MODULOS]
./integrador.sh                     # igual ao cron
```
