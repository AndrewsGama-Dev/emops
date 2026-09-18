import requests
import json
import pandas as pd
from datetime import datetime, timedelta
import time
import hashlib
import base64
import os
import pytz
import configparser
import csv
import io
import unicodedata
import re
from config_reader import (
    obter_headers_api,
    ler_token_config,
    ler_config,
    ler_codigos_afastamento,
    empresas_para_consultar,
    descrever_filtro_empresa,
    get_jsonapi_paginado,
    funcionario_departamento_ignorado,
    ler_departamentos_ignorar,
)
from funcionarios import formatar_cpf_11_digitos


def ler_campo_chave_afastamento():
    """Chave de identificacao no ifPonto. Padrao: cpf."""
    cfg = ler_config()
    if cfg and "APITARGET" in cfg:
        chave = (cfg["APITARGET"].get("campo_chave") or "cpf").strip().strip('"').strip("'")
        return chave.lower() if chave else "cpf"
    return "cpf"


def _normalizar_texto_afastamento(texto):
    """Minusculo, sem acento, espacos colapsados — para casar descricao com chave do .config."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


# Ordem importa: regras mais especificas primeiro
_REGRAS_TIPO_AFASTAMENTO = (
    (("ferias",), "ferias"),
    (
        (
            "atestado por acidente",
            "doenca ocasio",
            "doenca ocasion",
            "acidente/ doenca",
        ),
        "atestado_acidente_trabalho",
    ),
    (("atestado",), "atestado"),
    (("beneficio",), "beneficio"),
    (("licenca remunerada",), "licenca_remunerada"),
    (("salario maternidade", "maternidade"), "salario_maternidade"),
    (("licenca paternidade", "paternidade"), "licenca_paternidade"),
    (("licenca sem remuneracao", "sem remuneracao"), "licenca_sem_remuneracao"),
    (("s.a.t", "sat"), "sat"),
    (("suspensao",), "suspensao_contrato"),
    (("aposentadoria",), "aposentadoria_invalidez"),
    (("servico militar", "militar"), "servico_militar"),
    (("outros motivos", "outros"), "outros"),
)


def resolver_codigo_afastamento(descricao):
    """
    Converte afastamentodescricao (eContador) no ID-AFASTAMENTO (ifPonto)
    conforme [AFASTAMENTOS] no .config.
    """
    codigos = ler_codigos_afastamento()
    padrao = codigos.get("codigo_padrao") or codigos.get("outros") or "1022"
    obs = _normalizar_texto_afastamento(descricao)
    if not obs:
        return padrao, "codigo_padrao"

    for termos, chave in _REGRAS_TIPO_AFASTAMENTO:
        if any(termo in obs for termo in termos):
            return codigos.get(chave, padrao), chave

    return padrao, "codigo_padrao"

def carregar_configuracoes():
    """Funcao para carregar configuracoes do arquivo .config"""
    config = configparser.ConfigParser(interpolation=None)
    config.read('.config')
    
    if not config.has_section('APITARGET'):
        print("Secao [APITARGET] nao encontrada no arquivo .config")
        return None
    
    return {
        'apitarget': {
            'url': config.get('APITARGET', 'url'),
            'integracao': config.get('APITARGET', 'integracao'),
            'token_base': config.get('APITARGET', 'token_base')
        }
    }

def gerar_token_target():
    """Gera o token para a API de destino usando a data atual"""
    config = carregar_configuracoes()
    if not config:
        print("Erro ao carregar configuracoes")
        return None, None, None
    
    url = config['apitarget']['url']
    integracao = config['apitarget']['integracao']
    token_base = config['apitarget']['token_base']
    
    tz_sao_paulo = pytz.timezone('America/Sao_Paulo')
    data_atual = datetime.now(tz_sao_paulo).strftime('%d/%m/%Y')
    
    token_concatenado = token_base + data_atual
    token_final = hashlib.sha256(token_concatenado.encode('utf-8')).hexdigest()
    
    return url, integracao, token_final

def converter_para_csv(dados, nome_arquivo="dados.csv"):
    """Funcao para converter dados em CSV com cabecalhos em lowercase"""
    if not dados:
        print("Nao ha dados para converter em CSV")
        return None
    
    try:
        output = io.StringIO()
        
        fieldnames_originais = dados[0].keys()
        fieldnames_lowercase = [field.lower() for field in fieldnames_originais]
        
        dados_lowercase = []
        for linha in dados:
            linha_lowercase = {}
            for key, value in linha.items():
                linha_lowercase[key.lower()] = value
            dados_lowercase.append(linha_lowercase)
        
        writer = csv.DictWriter(output, fieldnames=fieldnames_lowercase, delimiter=';')
        writer.writeheader()
        for linha in dados_lowercase:
            writer.writerow(linha)
        
        csv_content = output.getvalue()
        output.close()
        
        with open(nome_arquivo, 'w', encoding='utf-8', newline='') as f:
            f.write(csv_content)
        
        print(f"CSV gerado com sucesso: {nome_arquivo}")
        print(f"Total de registros: {len(dados)}")
        
        return csv_content
        
    except Exception as e:
        print(f"Erro ao gerar CSV: {e}")
        return None

def importar_via_post_generico(nome_arquivo_csv, endpoint, nome_modulo):
    """Funcao para importar CSV via POST"""
    if not os.path.exists(nome_arquivo_csv):
        print(f"Arquivo {nome_arquivo_csv} NAO encontrado!")
        return None
    
    resultado_token = gerar_token_target()
    if not resultado_token or resultado_token[0] is None:
        print("Falha ao gerar token para API de destino")
        return None
    
    url, integracao, token_final = resultado_token
    
    headers = {"user": integracao, "token": token_final}
    data = {"pag": endpoint, "cmd": "importar_cad", "separador": ";"}
    
    try:
        with open(nome_arquivo_csv, 'rb') as arquivo:
            files = {'arquivo': (nome_arquivo_csv, arquivo, 'text/csv')}
            response = requests.post(url, data=data, files=files, headers=headers, timeout=30)
        
        if response.status_code == 200:
            try:
                resultado = response.json()
                if resultado.get('success') == False:
                    print(f"API retornou erro: {json.dumps(resultado, indent=2, ensure_ascii=False)}")
                    return None
                else:
                    print(f"POST de {nome_modulo} realizado!")
                    cadastrados = resultado.get('ok', 0)
                    if cadastrados > 0:
                        print(f"{cadastrados} {nome_modulo} cadastrado(s)!")
                    return resultado
            except json.JSONDecodeError:
                print(f"Resposta nao eh JSON valido: {response.text[:500]}...")
                return None
        else:
            print(f"ERRO - Status: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"ERRO na requisicao: {e}")
        return None

def processar_modulo_afastamentos(dados_afastamentos, nome_arquivo_csv, nome_modulo):
    """Funcao generica para processar um modulo completo"""
    print(f"\n" + "="*50)
    print(f"PROCESSANDO {nome_modulo.upper()}...")
    print("="*50)
    
    if dados_afastamentos:
        print(f"\n{len(dados_afastamentos)} {nome_modulo} encontrados!")
        
        csv_content = converter_para_csv(dados_afastamentos, nome_arquivo_csv)
        
        if csv_content:
            resultado = importar_via_post_generico(nome_arquivo_csv, "ponto_afastamento", nome_modulo)
            
            if resultado:
                print(f"\nINTEGRACAO DE {nome_modulo.upper()} CONCLUIDA!")
                return True
            else:
                print(f"\nFALHA NO POST DE {nome_modulo.upper()}!")
                return False
        else:
            return False
    else:
        print(f"\nNenhum dado de {nome_modulo} disponivel")
        return False

def extrair_datas_dos_campos_corretos(attributes):
    """
    FUNCAO CORRIGIDA: Extrai datas dos campos corretos identificados
    
    CAMPOS CORRETOS IDENTIFICADOS:
    - attributes['afastamento'] = Data de INICIO (2025-07-16T03:00:00Z)
    - attributes['retorno'] = Data de FIM (2025-07-18T03:00:00Z)
    """
    print(f"  Extraindo datas dos CAMPOS CORRETOS...")
    
    # BUSCAR CAMPOS CORRETOS
    campo_inicio = attributes.get('afastamento')  # Data de INICIO
    campo_fim = attributes.get('retorno')         # Data de FIM
    
    print(f"    Campo 'afastamento' (INICIO): {campo_inicio}")
    print(f"    Campo 'retorno' (FIM): {campo_fim}")
    
    # Verificar se temos ambos os campos
    if campo_inicio and campo_fim:
        try:
            # Converter datas ISO para formato DD/MM/YYYY
            dt_inicio = datetime.fromisoformat(campo_inicio.replace('Z', '+00:00'))
            dt_fim = datetime.fromisoformat(campo_fim.replace('Z', '+00:00'))
            
            data_inicio_fmt = dt_inicio.strftime('%d/%m/%Y')
            data_fim_fmt = dt_fim.strftime('%d/%m/%Y')
            
            print(f"    DATAS EXTRAIDAS: {data_inicio_fmt} ate {data_fim_fmt}")
            return data_inicio_fmt, data_fim_fmt, "CAMPOS_CORRETOS_API"
            
        except Exception as e:
            print(f"    Erro ao converter datas: {e}")
    
    # Afastamento em aberto (Benefício/SAT sem data de retorno)
    elif campo_inicio:
        try:
            dt_inicio = datetime.fromisoformat(campo_inicio.replace('Z', '+00:00'))
            data_inicio_fmt = dt_inicio.strftime('%d/%m/%Y')
            print(f"    Afastamento em aberto: inicio {data_inicio_fmt} (sem retorno)")
            return data_inicio_fmt, "", "INICIO_SEM_RETORNO"
        except Exception as e:
            print(f"    Erro ao converter data de inicio: {e}")

    elif campo_fim:
        try:
            dt_fim = datetime.fromisoformat(campo_fim.replace('Z', '+00:00'))
            data_fim_fmt = dt_fim.strftime('%d/%m/%Y')
            
            print(f"    Apenas data FIM: {data_fim_fmt}")
            return None, data_fim_fmt, "APENAS_RETORNO"
            
        except Exception as e:
            print(f"    Erro ao converter data de retorno: {e}")
    
    print(f"    Campos de data nao encontrados")
    return None, None, "SEM_DATAS_API"

def consultar_funcionarios_com_afastamentos():
    """Coleta funcionarios ATIVOS/AFASTADOS com afastamento na empresa filtrada."""
    print("INICIANDO COLETA - VERSAO CORRIGIDA")
    
    headers = obter_headers_api()
    if not headers:
        print("Nao foi possivel obter o token do arquivo .config")
        return [], None
    
    base_url = "https://dp.pack.alterdata.com.br/api/v1/funcionarios"
    
    params_base = {
        "fields": "codigo,nome,cpf,afastamento,afastamentodescricao,status,retorno",
        "include": "departamento",
        "sort": "codigo",
        "page[limit]": "100",
    }
    print(f"Filtro de empresa ativo: {descrever_filtro_empresa()}")
    depts_ignorar = ler_departamentos_ignorar()
    if depts_ignorar:
        print(f"Departamentos ignorados: {', '.join(depts_ignorar)}")

    funcionarios_com_afastamento = []
    for empresa_id in empresas_para_consultar():
        params = dict(params_base)
        if empresa_id:
            params["filter[empresa.id]"] = empresa_id
            print(f"  Empresa {empresa_id}...")

        for pagina, _data, funcionarios_pagina in get_jsonapi_paginado(
            base_url, headers, params=params, page_limit=100, pausa=0.3
        ):
            print(f"  Coletando pagina {pagina}... ", end="")
            for funcionario in funcionarios_pagina:
                if funcionario_departamento_ignorado(funcionario):
                    continue
                attributes = funcionario.get('attributes', {})
                status_norm = _normalizar_texto_afastamento(attributes.get('status'))
                if status_norm not in ('ativo', 'afastado'):
                    continue

                afastamento = attributes.get('afastamento')
                afastamento_desc_raw = attributes.get('afastamentodescricao', '')
                afastamento_desc = afastamento_desc_raw.lower() if afastamento_desc_raw else ''

                if afastamento is not None or (afastamento_desc and afastamento_desc.strip()):
                    print(f"\n  Funcionario {attributes.get('codigo', 'N/A')} ({attributes.get('status')}) - {afastamento_desc_raw}")
                    funcionarios_com_afastamento.append(funcionario)

            com_desc = len([
                f for f in funcionarios_pagina
                if (f.get('attributes', {}).get('afastamentodescricao') or '').strip()
            ])
            print(f"{len(funcionarios_pagina)} funcionarios ({com_desc} com descricao de afastamento)")

    print(f"\nTotal de funcionarios com afastamento (Ativo/Afastado): {len(funcionarios_com_afastamento)}")
    return funcionarios_com_afastamento, headers

def mapear_afastamento_para_csv(funcionario_api):
    """
    FUNCAO PRINCIPAL CORRIGIDA: Usar os campos corretos
    """
    attributes = funcionario_api.get('attributes', {})
    funcionario_id = funcionario_api.get('id', '')
    
    afastamento_desc = attributes.get('afastamentodescricao', '')
    codigo_funcionario = attributes.get('codigo', funcionario_id)
    cpf = formatar_cpf_11_digitos(attributes.get('cpf', ''))
    campo_chave = ler_campo_chave_afastamento()

    codigo_afastamento, chave_tipo = resolver_codigo_afastamento(afastamento_desc)

    print(f"\nMapeando funcionario {codigo_funcionario}")
    print(f"    Descricao original: '{afastamento_desc}'")
    print(f"    Tipo (.config): {chave_tipo} -> ID-AFASTAMENTO {codigo_afastamento}")
    print(f"    Chave: {campo_chave} | CPF: {cpf}")
    print(f"    ID-Afastamento FINAL: {codigo_afastamento}")
    
    # USAR CAMPOS CORRETOS DIRETAMENTE
    dtinicio, dtfim, origem_data = extrair_datas_dos_campos_corretos(attributes)
    
    if not dtinicio:
        print(f"    ERRO: Nao foi possivel obter data de inicio")
        dtinicio = 'SEM_DATA_API'
        origem_data = 'ERRO_API'
    elif origem_data == "INICIO_SEM_RETORNO":
        dtfim = dtfim or ""
    elif not dtfim:
        print(f"    ERRO: Nao foi possivel obter data de fim")
        dtfim = 'SEM_DATA_API'
        origem_data = 'ERRO_API'
    
    # Mapeamento final - chave de integracao = cpf (sem coluna matricula)
    afastamento_csv = {
        'ID-AFASTAMENTO': codigo_afastamento,
        'DTINICIO': dtinicio,
        'DTFIM': dtfim,
        'OBS': afastamento_desc if afastamento_desc else 'Afastamento',
        'CAMPO_CHAVE': campo_chave,
        'CPF': cpf
    }
    
    return afastamento_csv

def gerar_csv_afastamentos():
    """FUNCAO PRINCIPAL: Gerar CSV usando os campos corretos"""
    print("=" * 80)
    print("     GERACAO DE CSV - VERSAO FINAL CORRIGIDA")
    print("=" * 80)
    
    token = ler_token_config()
    if not token:
        print("Falha ao carregar token do arquivo .config")
        return None
    
    print("\n1. Consultando afastamentos na API Alterdata...")
    funcionarios_afastamento, headers = consultar_funcionarios_com_afastamentos()
    
    if not funcionarios_afastamento:
        print("Nenhum funcionario com afastamento foi encontrado")
        return None
    
    # Converter para formato CSV
    afastamentos_csv = []
    funcionarios_com_datas_reais = 0
    funcionarios_sem_datas = 0
    
    for funcionario_api in funcionarios_afastamento:
        try:
            afastamento_csv = mapear_afastamento_para_csv(funcionario_api)
            afastamentos_csv.append(afastamento_csv)

            if afastamento_csv['DTINICIO'] != 'SEM_DATA_API' and afastamento_csv['DTFIM'] != 'SEM_DATA_API':
                funcionarios_com_datas_reais += 1
            else:
                funcionarios_sem_datas += 1
                    
        except Exception as e:
            print(f"Erro ao processar funcionario: {e}")
            funcionarios_sem_datas += 1
    
    print(f"\nRESULTADO:")
    print(f"   Funcionarios com datas CORRETAS: {funcionarios_com_datas_reais}")
    print(f"   Funcionarios sem datas: {funcionarios_sem_datas}")
    print(f"   Total de registros: {len(afastamentos_csv)}")
    
    return afastamentos_csv

def processar_integracao_completa():
    """FUNCAO PRINCIPAL CORRIGIDA"""
    print("INICIANDO INTEGRACAO FINAL CORRIGIDA")
    print("="*50)
    
    dados_afastamentos = gerar_csv_afastamentos()
    
    if not dados_afastamentos:
        print("Falha na coleta de dados")
        return False
    
    sucesso = processar_modulo_afastamentos(
        dados_afastamentos,
        'afastamentos_api.csv',
        'afastamentos'
    )
    
    if sucesso:
        print(f"\nINTEGRACAO FINAL CONCLUIDA!")
        print(f"CSV gerado: afastamentos_api.csv")
        
        # Mostrar todos os registros gerados
        try:
            df = pd.read_csv('afastamentos_api.csv', sep=';')
            print(f"\nREGISTROS GERADOS ({len(df)} total):")
            for i, row in df.iterrows():
                print(f"   {row.get('cpf', '')}: {row['dtinicio']} a {row['dtfim']} | {row['obs']}")
                
        except Exception as e:
            print(f"Erro ao ler CSV: {e}")
        
        return True
    else:
        print(f"\nFALHA NA INTEGRACAO!")
        return False

# =================== EXECUCAO PRINCIPAL ===================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        comando = sys.argv[1].lower()
        
        if comando == "completo" or comando == "integracao":
            sucesso = processar_integracao_completa()
            
        elif comando == "csv":
            dados = gerar_csv_afastamentos()
            if dados:
                csv_content = converter_para_csv(dados, 'afastamentos_api.csv')
                if csv_content:
                    print(f"\nCSV FINAL GERADO!")
                    print(f"Arquivo: afastamentos_api.csv")
                    
                    # Mostrar todos os registros
                    try:
                        df = pd.read_csv('afastamentos_api.csv', sep=';')
                        print(f"\nTODOS OS REGISTROS ({len(df)}):")
                        for i, row in df.iterrows():
                            print(f"   {row.get('cpf', '')}: {row['dtinicio']} a {row['dtfim']} | {row['obs']}")
                            
                    except Exception as e:
                        print(f"Erro ao analisar CSV: {e}")
                    
        elif comando == "enviar":
            nome_arquivo = sys.argv[2] if len(sys.argv) > 2 else "afastamentos_api.csv"
            if os.path.exists(nome_arquivo):
                resultado = importar_via_post_generico(nome_arquivo, "ponto_afastamento", "afastamentos")
                if resultado:
                    print(f"\nARQUIVO ENVIADO COM SUCESSO!")
                else:
                    print(f"\nFALHA NO ENVIO!")
            else:
                print(f"Arquivo {nome_arquivo} nao encontrado!")
                
        else:
            print("Comando invalido! Use:")
            print("  python afastamentos.py completo   # Integracao completa")
            print("  python afastamentos.py csv        # Apenas gerar CSV")
            print("  python afastamentos.py enviar [arquivo.csv]")
    else:
        print("EXECUTANDO INTEGRACAO FINAL CORRIGIDA")
        sucesso = processar_integracao_completa()
        if sucesso:
            print(f"\nPROBLEMA RESOLVIDO!")
        else:
            print(f"\nINTEGRACAO FALHOU")