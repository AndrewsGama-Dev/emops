import configparser
import os
import time

import requests

def ler_config():
    """
    Lê o arquivo .config e retorna um dicionário com todas as seções
    """
    try:
        if not os.path.exists('.config'):
            print("❌ Arquivo .config não encontrado")
            return None
        
        config = configparser.ConfigParser()
        config.read('.config', encoding='utf-8')
        
        # Converter para dicionário para facilitar o uso
        config_dict = {}
        for secao in config.sections():
            config_dict[secao] = dict(config[secao])
        
        return config_dict
        
    except Exception as e:
        print(f"❌ Erro ao ler arquivo .config: {e}")
        return None

def ler_token_config():
    """
    Lê especificamente o token da seção APISOURCE
    """
    try:
        config = ler_config()
        if config and 'APISOURCE' in config:
            token = config['APISOURCE'].get('token')
            if token:
                print("✅ Token carregado do arquivo .config")
                return token.strip('"')  # Remove aspas se houver
        
        print("❌ Token não encontrado na seção [APISOURCE]")
        return None
        
    except Exception as e:
        print(f"❌ Erro ao ler token: {e}")
        return None

def obter_headers_api():
    """
    Obtém os headers necessários para chamadas à API da Alterdata
    """
    token = ler_token_config()
    if not token:
        return None
    
    headers = {
        'Content-Type': 'application/vnd.api+json',
        'Authorization': f'Bearer {token}'
    }
    
    return headers


def get_jsonapi_paginado(url, headers, params=None, page_limit=100, max_paginas=200, timeout=60, pausa=0.2):
    """
    Percorre páginas JSON:API reaplicando os filtros em toda requisição.

    A URL em links.next da eContador costuma omitir filter[...], então
    não deve ser usada quando há filtro de empresa/status.
    Yields: (pagina, data_json, itens)
    """
    params = dict(params or {})
    limit = int(params.get("page[limit]", page_limit))
    offset = 0

    for pagina in range(1, max_paginas + 1):
        req = dict(params)
        req["page[limit]"] = str(limit)
        req["page[offset]"] = str(offset)
        response = requests.get(url, headers=headers, params=req, timeout=timeout)
        if response.status_code == 429:
            time.sleep(10)
            response = requests.get(url, headers=headers, params=req, timeout=timeout)
        if response.status_code != 200:
            print(f"Erro API {response.status_code}: {response.text[:200]}")
            return
        data = response.json()
        itens = data.get("data") or []
        yield pagina, data, itens
        if len(itens) < limit:
            return
        offset += limit
        if pausa:
            time.sleep(pausa)


def _parse_ids_separados(valor):
    """Aceita '9' ou '9,10,11' (vírgula ou ponto e vírgula)."""
    ids = []
    if valor is None:
        return ids
    texto = str(valor).strip().strip('"').strip("'")
    if not texto:
        return ids
    for parte in texto.replace(';', ',').split(','):
        item = parte.strip()
        if item and item not in ids:
            ids.append(item)
    return ids


def ler_codigos_empresa_filtro():
    """
    Lê os IDs de empresa em [FILTROS].codigo_empresa.

    Aceita um ID (`9`) ou vários separados por vírgula (`9,10,11`).
    Returns:
        list[str]: IDs (ex.: ["9", "10", "11"]) ou lista vazia = todas as empresas.
    """
    try:
        config = ler_config()
        if not config or 'FILTROS' not in config:
            return []
        return _parse_ids_separados(config['FILTROS'].get('codigo_empresa'))
    except Exception as e:
        print(f"❌ Erro ao ler codigo_empresa do .config: {e}")
        return []


def ler_departamentos_ignorar():
    """
    IDs de departamento (eContador) que não entram na integração.
    [FILTROS].departamentos_ignorar — ex.: 940,973 (MAPA AP e MAPA RORAIMA).
    """
    try:
        config = ler_config()
        if not config or 'FILTROS' not in config:
            return []
        return _parse_ids_separados(config['FILTROS'].get('departamentos_ignorar'))
    except Exception as e:
        print(f"❌ Erro ao ler departamentos_ignorar do .config: {e}")
        return []


def id_departamento_do_funcionario(funcionario):
    """ID do departamento no relacionamento JSON:API, ou ''."""
    if not funcionario:
        return ""
    rel = (funcionario.get("relationships") or {}).get("departamento") or {}
    data = rel.get("data")
    if isinstance(data, dict):
        return str(data.get("id") or "").strip()
    return ""


def funcionario_departamento_ignorado(funcionario):
    """True se o funcionário pertence a um departamento em departamentos_ignorar."""
    ignorar = set(ler_departamentos_ignorar())
    if not ignorar:
        return False
    return id_departamento_do_funcionario(funcionario) in ignorar


def ler_codigo_empresa_filtro():
    """
    Compatibilidade: primeiro ID configurado, ou None se vazio.
    Prefira ler_codigos_empresa_filtro() quando houver várias empresas.
    """
    ids = ler_codigos_empresa_filtro()
    return ids[0] if ids else None


def empresas_para_consultar():
    """
    IDs a consultar na API. [None] = não aplicar filter[empresa.id].
    """
    ids = ler_codigos_empresa_filtro()
    return ids if ids else [None]


def descrever_filtro_empresa():
    ids = ler_codigos_empresa_filtro()
    if not ids:
        return "sem filtro (todas as empresas)"
    return ", ".join(ids)


def _parse_bool_config(valor, default=True):
    """Interpreta true/false, 1/0, sim/nao, yes/no (case insensitive)."""
    if valor is None:
        return default
    texto = str(valor).strip().strip('"').lower()
    if texto in ('true', '1', 'yes', 'y', 'sim', 's', 'on'):
        return True
    if texto in ('false', '0', 'no', 'n', 'nao', 'não', 'off'):
        return False
    return default


MODULOS_PADRAO = (
    'empresas',
    'departamentos',
    'cargos',
    'funcionarios',
    'afastamentos',
    'demissoes',
)


def ler_modulos_habilitados():
    """
    Lê a seção [MODULOS] do .config (true/false por módulo).

    Se a seção não existir, todos os módulos ficam habilitados (compatibilidade).
    """
    habilitados = {nome: True for nome in MODULOS_PADRAO}
    try:
        config = ler_config()
        if not config or 'MODULOS' not in config:
            return habilitados

        secao = config['MODULOS']
        for nome in MODULOS_PADRAO:
            if nome in secao:
                habilitados[nome] = _parse_bool_config(secao.get(nome), default=True)
        return habilitados
    except Exception as e:
        print(f"❌ Erro ao ler [MODULOS] do .config: {e}")
        return habilitados


def modulo_habilitado(nome_modulo):
    """Retorna True se o módulo deve ser executado conforme [MODULOS]."""
    return bool(ler_modulos_habilitados().get(nome_modulo, True))


# Chaves da seção [AFASTAMENTOS] e valores padrão (ifPonto)
CODIGOS_AFASTAMENTO_PADRAO = {
    'codigo_padrao': '1022',
    'ferias': '1011',
    'atestado': '1012',
    'beneficio': '1013',
    'licenca_remunerada': '1014',
    'salario_maternidade': '1015',
    'sat': '1016',
    'suspensao_contrato': '1017',
    'licenca_sem_remuneracao': '1018',
    'aposentadoria_invalidez': '1019',
    'servico_militar': '1020',
    'licenca_paternidade': '1021',
    'atestado_acidente_trabalho': '1016',
    'outros': '1022',
}


def ler_codigos_afastamento():
    """
    Lê [AFASTAMENTOS] do .config (código ifPonto por tipo).
    Se a seção/chave não existir, usa os padrões sequenciais (1011+).
    """
    codigos = dict(CODIGOS_AFASTAMENTO_PADRAO)
    try:
        config = ler_config()
        if not config or 'AFASTAMENTOS' not in config:
            return codigos

        secao = config['AFASTAMENTOS']
        for chave in codigos:
            if chave in secao and str(secao.get(chave) or '').strip():
                codigos[chave] = str(secao.get(chave)).strip().strip('"')
        return codigos
    except Exception as e:
        print(f"❌ Erro ao ler [AFASTAMENTOS] do .config: {e}")
        return codigos


def historico_demissoes_habilitado():
    """
    Lê historico_demissoes (true/false).

    Ordem: [FILTROS] e, se não existir, [MODULOS] (compatibilidade).
    true  = usa demissoes_matricula_processados.txt (padrão)
    false = não lê nem grava o histórico (reprocessa demissões)
    """
    try:
        config = ler_config()
        if not config:
            return True

        valor = None
        if 'FILTROS' in config and 'historico_demissoes' in config['FILTROS']:
            valor = config['FILTROS'].get('historico_demissoes')
        elif 'MODULOS' in config and 'historico_demissoes' in config['MODULOS']:
            valor = config['MODULOS'].get('historico_demissoes')

        if valor is None:
            return True

        return _parse_bool_config(valor, default=True)
    except Exception as e:
        print(f"❌ Erro ao ler historico_demissoes do .config: {e}")
        return True