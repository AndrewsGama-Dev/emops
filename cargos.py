import requests
import json
import pandas as pd
from datetime import datetime
import time
import hashlib
import pytz
import configparser
from config_reader import (
    obter_headers_api,
    ler_token_config,
    empresas_para_consultar,
    descrever_filtro_empresa,
    get_jsonapi_paginado,
    funcionario_departamento_ignorado,
    ler_departamentos_ignorar,
)

def carregar_configuracoes_target():
    """
    Carrega configurações da seção [APITARGET] do arquivo .config
    """
    try:
        config = configparser.ConfigParser()
        config.read('.config', encoding='utf-8')
        
        if 'APITARGET' not in config:
            print("❌ Seção [APITARGET] não encontrada no arquivo .config")
            return None
        
        return {
            'url': config['APITARGET'].get('url', '').strip(),
            'integracao': config['APITARGET'].get('integracao', '').strip(),
            'token_base': config['APITARGET'].get('token_base', '').strip()
        }
    except Exception as e:
        print(f"❌ Erro ao carregar configurações [APITARGET]: {e}")
        return None

def gerar_token_target():
    """
    Gera o token para a API de destino usando a data atual
    """
    config_target = carregar_configuracoes_target()
    if not config_target:
        return None, None
    
    # Configurar timezone para São Paulo
    tz_sao_paulo = pytz.timezone('America/Sao_Paulo')
    data_atual = datetime.now(tz_sao_paulo).strftime('%d/%m/%Y')
    
    # Gerar token final
    token_concatenado = config_target['token_base'] + data_atual
    token_final = hashlib.sha256(token_concatenado.encode('utf-8')).hexdigest()
    
    print(f"🔑 Data atual: {data_atual}")
    print(f"🔗 Token base: {config_target['token_base']}")
    print(f"🔐 Token final gerado: {token_final[:32]}...")
    
    return config_target, token_final

def enviar_csv_para_api_target(nome_arquivo_csv):
    """
    Envia o CSV de cargos para a API de destino via POST
    """
    import os
    
    if not os.path.exists(nome_arquivo_csv):
        print(f"❌ Arquivo {nome_arquivo_csv} não encontrado!")
        return False
    
    print(f"✅ Arquivo {nome_arquivo_csv} encontrado")
    
    # Obter configurações e token
    config_target, token_final = gerar_token_target()
    if not config_target or not token_final:
        print("❌ Falha ao gerar token para API de destino")
        return False
    
    # Usar 'gotech' como usuário
    usuario_correto = 'gotech'
    
    # Preparar headers e dados
    headers = {
        "user": usuario_correto,
        "token": token_final
    }
    
    data = {
        "pag": "configuracao_cargo",
        "cmd": "importar_cad",
        "separador": ";"
    }
    
    try:
        print(f"📤 Enviando POST para API de destino...")
        print(f"🌐 URL: {config_target['url']}")
        print(f"👤 Usuário: {usuario_correto}")
        print(f"📄 Endpoint: configuracao_cargo")
        print(f"🔑 Token: {token_final[:32]}...")
        
        with open(nome_arquivo_csv, 'rb') as arquivo:
            files = {
                'arquivo': (nome_arquivo_csv, arquivo, 'text/csv')
            }
            
            response = requests.post(
                config_target['url'], 
                data=data, 
                files=files,
                headers=headers,
                timeout=30
            )
        
        print(f"📊 Status da resposta: {response.status_code}")
        
        if response.status_code == 200:
            try:
                resultado = response.json()
                
                if resultado.get('success') == False:
                    print(f"❌ API retornou erro:")
                    print(f"📝 Resposta: {json.dumps(resultado, indent=2, ensure_ascii=False)}")
                    
                    if 'login' in str(resultado.get('info', '')).lower():
                        print(f"\n💡 SUGESTÕES PARA CORRIGIR ERRO DE LOGIN:")
                        print(f"1. ❌ Verificar se token_base está correto: '{config_target['token_base']}'")
                        print(f"2. ❌ Verificar formato da data (atual: {datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m/%Y')})")
                        print(f"3. ❌ Confirmar usuário correto (usando: '{usuario_correto}')")
                        print(f"4. ❌ Execute debug_token.py para mais detalhes")
                    
                    return False
                else:
                    print(f"✅ POST de cargos realizado com sucesso!")
                    print(f"📋 Resposta da API:")
                    print(json.dumps(resultado, indent=2, ensure_ascii=False))
                    
                    cadastrados = resultado.get('ok', 0)
                    if cadastrados > 0:
                        print(f"🎉 {cadastrados} cargo(s) cadastrado(s) com sucesso!")
                    
                    return True
                
            except json.JSONDecodeError:
                print(f"⚠️ Resposta não é JSON válido:")
                print(f"📝 Resposta: {response.text[:500]}...")
                return False
                
        else:
            print(f"❌ ERRO no POST - Status: {response.status_code}")
            print(f"📝 Resposta: {response.text[:500]}...")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ ERRO na requisição para API de destino: {e}")
        return False

def extrair_funcoes_dos_funcionarios():
    """
    Extrai funções/cargos únicos a partir dos funcionários
    """
    print("🔍 INICIANDO COLETA DE CARGOS/FUNÇÕES...")
    
    # Obter headers do arquivo .config
    headers = obter_headers_api()
    if not headers:
        print("❌ Não foi possível obter o token do arquivo .config")
        return {}, None
    
    # Configurações da API
    base_url = "https://dp.pack.alterdata.com.br/api/v1/funcionarios"
    
    params_base = {
        "sort": "codigo",
        "filter[status]": "ativo",
        "fields": "codigo,nome,nomefuncao",
        "include": "departamento",
    }
    print(f"Filtro de empresa ativo: {descrever_filtro_empresa()}")
    depts_ignorar = ler_departamentos_ignorar()
    if depts_ignorar:
        print(f"Departamentos ignorados: {', '.join(depts_ignorar)}")

    funcoes_unicas = {}
    for empresa_consulta in empresas_para_consultar():
        params = dict(params_base)
        if empresa_consulta:
            params["filter[empresa.id]"] = empresa_consulta
            print(f"  Empresa {empresa_consulta}...")

        for pagina, _data, funcionarios_pagina in get_jsonapi_paginado(
            base_url, headers, params=params, page_limit=100, pausa=0.3
        ):
            print(f"  📄 Processando página {pagina}... {len(funcionarios_pagina)} funcionários")

            for funcionario in funcionarios_pagina:
                if funcionario_departamento_ignorado(funcionario):
                    continue
                attributes = funcionario.get('attributes', {})
                nome_funcao = attributes.get('nomefuncao', '')

                if nome_funcao and ' - ' in nome_funcao:
                    partes = nome_funcao.split(' - ', 1)
                    if len(partes) == 2:
                        codigo_funcao = partes[0].strip()
                        nome_funcao_limpo = partes[1].strip()
                        empresa_id = empresa_consulta or ''
                        chave = (codigo_funcao, empresa_id)

                        if chave not in funcoes_unicas:
                            funcoes_unicas[chave] = {
                                'codigo': codigo_funcao,
                                'nome': nome_funcao_limpo,
                                'nome_completo': nome_funcao,
                                'empresa_id': empresa_id,
                                'funcionarios_exemplo': []
                            }

                        if len(funcoes_unicas[chave]['funcionarios_exemplo']) < 3:
                            funcoes_unicas[chave]['funcionarios_exemplo'].append({
                                'id': funcionario.get('id'),
                                'nome': attributes.get('nome', '')
                            })
    
    print(f"\n✅ Total de funções únicas encontradas: {len(funcoes_unicas)}")
    return funcoes_unicas, headers

def buscar_empresa_padrao(headers):
    """
    Fallback se o cargo nao vier com empresa_id.
    """
    ids = [e for e in empresas_para_consultar() if e]
    if ids:
        return ids[0]

    try:
        url_empresas = "https://dp.pack.alterdata.com.br/api/v1/empresas"
        params = {"filter[empresas][ativa][EQ]": "true", "page[limit]": "1"}
        
        response = requests.get(url_empresas, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            empresas = data.get('data', [])
            if empresas:
                return empresas[0].get('id', '')
    except Exception:
        pass
    
    return ''

def mapear_cargo_para_csv(codigo, dados_funcao, id_empresa_padrao):
    """
    Mapeia uma função/cargo para o formato esperado no CSV
    """
    # Mapeamento dos campos conforme a query original
    cargo_csv = {
        'campo_chave': 'codigo_legado',  # 'codigo_legado' AS campo_chave
        'codigo_legado': codigo,  # f.ID_FUNCAO AS codigo_legado
        'nome': dados_funcao['nome'],  # f.DESCRICAO AS nome
        'id-empresa': id_empresa_padrao,  # f.id_empresa AS "id-empresa"
        'nome_cbo': '',  # '' AS nome_cbo (campo vazio conforme query)
        'nro_cbo': ''  # '' AS nro_cbo (campo vazio conforme query)
    }
    
    return cargo_csv

def gerar_csv_cargos():
    """
    Função principal para gerar o CSV dos cargos/funções
    """
    print("=" * 80)
    print("         💼 GERAÇÃO DE CSV DE CARGOS/FUNÇÕES - API eContador")
    print("=" * 80)
    
    # Verificar se token está disponível
    token = ler_token_config()
    if not token:
        print("❌ Falha ao carregar token do arquivo .config")
        return None
    
    # Extrair funções dos funcionários
    funcoes_dict, headers = extrair_funcoes_dos_funcionarios()
    
    if not funcoes_dict:
        print("❌ Nenhuma função foi extraída dos funcionários")
        return
    
    # Buscar empresa padrão
    print(f"\n🏢 Buscando empresa padrão...")
    id_empresa_padrao = buscar_empresa_padrao(headers)
    if id_empresa_padrao:
        print(f"✅ Empresa padrão encontrada: ID {id_empresa_padrao}")
    else:
        print("⚠️  Empresa padrão não encontrada, usando campo vazio")
    
    print(f"\n🔄 Convertendo {len(funcoes_dict)} funções para formato CSV...")
    
    # Converter para formato CSV
    cargos_csv = []
    erros = []
    
    for chave, dados_funcao in funcoes_dict.items():
        try:
            codigo = dados_funcao.get('codigo') or (chave[0] if isinstance(chave, tuple) else chave)
            id_empresa = dados_funcao.get('empresa_id') or id_empresa_padrao
            cargo_csv = mapear_cargo_para_csv(codigo, dados_funcao, id_empresa)
            cargos_csv.append(cargo_csv)
        except Exception as e:
            erros.append({'codigo': str(chave), 'erro': str(e)})
            print(f"  ❌ Erro ao processar função {chave}: {e}")
    
    if not cargos_csv:
        print("❌ Nenhuma função foi convertida com sucesso")
        return
    
    # Criar DataFrame
    print(f"\n📊 Criando DataFrame com {len(cargos_csv)} cargos...")
    df = pd.DataFrame(cargos_csv)
    
    # Ordenar por código legado
    df = df.sort_values('codigo_legado')
    
    # Gerar arquivo CSV
    nome_arquivo = f"cargos_api.csv"
    
    try:
        df.to_csv(nome_arquivo, index=False, encoding='utf-8-sig', sep=';')
        print(f"✅ CSV gerado com sucesso: {nome_arquivo}")
        
        # Estatísticas
        print(f"\n📈 ESTATÍSTICAS:")
        print(f"  💼 Total de cargos processados: {len(cargos_csv)}")
        print(f"  ❌ Erros de conversão: {len(erros)}")
        print(f"  📋 Colunas no CSV: {len(df.columns)}")
        print(f"  🏢 Empresa padrão usada: {id_empresa_padrao or 'Não definida'}")
        print(f"  💾 Arquivo gerado: {nome_arquivo}")
        
        # Mostrar preview dos dados
        print(f"\n👁️  PREVIEW DOS DADOS (primeiras 5 linhas):")
        print(df.head(5).to_string())
        
        # Salvar relatório de erros se houver
        if erros:
            arquivo_erros = f"erros_cargos.json"
            with open(arquivo_erros, 'w', encoding='utf-8') as f:
                json.dump(erros, f, indent=2, ensure_ascii=False)
            print(f"\n⚠️  Relatório de erros salvo em: {arquivo_erros}")
        
        # Salvar dados detalhados das funções
        dados_detalhados = {
            'funcoes_extraidas': funcoes_dict,
            'empresa_padrao_id': id_empresa_padrao,
            'total_cargos': len(cargos_csv),
            'timestamp': datetime.now().isoformat()
        }
        
        with open('cargos_dados_detalhados.json', 'w', encoding='utf-8') as f:
            json.dump(dados_detalhados, f, indent=2, ensure_ascii=False)
        print(f"💾 Dados detalhados salvos em 'cargos_dados_detalhados.json'")
        
        # Verificar campos com dados
        print(f"\n🔍 ANÁLISE DE PREENCHIMENTO DOS CAMPOS:")
        for coluna in df.columns:
            valores_nao_vazios = df[coluna].notna().sum() - (df[coluna] == '').sum()
            percentual = (valores_nao_vazios / len(df)) * 100
            status = "✅" if percentual > 0 else "⭕"
            print(f"  {status} {coluna:<20}: {valores_nao_vazios:3d}/{len(df)} ({percentual:5.1f}%)")
        
        return nome_arquivo
        
    except Exception as e:
        print(f"❌ Erro ao gerar CSV: {e}")
        return None

def processar_integracao_completa():
    """
    Função principal que executa todo o processo: coleta da API -> CSV -> POST para destino
    """
    print("=" * 80)
    print("    🚀 INTEGRAÇÃO COMPLETA DE CARGOS - eContador → Sistema Destino")
    print("=" * 80)
    
    # Etapa 1: Gerar CSV dos cargos
    print("\n📋 ETAPA 1: Coletando cargos da API eContador...")
    arquivo_csv = gerar_csv_cargos()
    
    if not arquivo_csv:
        print("❌ Falha na geração do CSV. Processo interrompido.")
        return False
    
    # Etapa 2: Validar dados
    print("\n🔍 ETAPA 2: Validando dados do CSV...")
    validar_dados_cargos_csv(arquivo_csv)
    
    # Etapa 3: Enviar para API de destino
    print("\n📤 ETAPA 3: Enviando CSV para API de destino...")
    sucesso_envio = enviar_csv_para_api_target(arquivo_csv)
    
    if sucesso_envio:
        print("\n🎉 INTEGRAÇÃO COMPLETA FINALIZADA COM SUCESSO!")
        print(f"✅ Cargos coletados da API eContador")
        print(f"✅ CSV gerado: {arquivo_csv}")
        print(f"✅ Dados enviados para sistema de destino")
        return True
    else:
        print("\n💥 FALHA NA INTEGRAÇÃO!")
        print(f"✅ CSV gerado: {arquivo_csv}")
        print(f"❌ Falha no envio para sistema de destino")
        return False

def validar_dados_cargos_csv(nome_arquivo):
    """
    Valida os dados do CSV de cargos gerado
    """
    if not nome_arquivo:
        return
    
    try:
        print(f"\n🔍 VALIDANDO DADOS DO CSV: {nome_arquivo}")
        
        # Ler o CSV gerado
        df = pd.read_csv(nome_arquivo, sep=';', encoding='utf-8-sig')
        
        print(f"  📊 Total de registros: {len(df)}")
        print(f"  📋 Total de colunas: {len(df.columns)}")
        
        # Verificar campos obrigatórios
        campos_obrigatorios = ['codigo_legado', 'nome', 'campo_chave']
        
        for campo in campos_obrigatorios:
            if campo in df.columns:
                vazios = df[campo].isna().sum() + (df[campo] == '').sum()
                if vazios > 0:
                    print(f"  ⚠️  Campo '{campo}': {vazios} registros vazios")
                else:
                    print(f"  ✅ Campo '{campo}': todos preenchidos")
            else:
                print(f"  ❌ Campo obrigatório '{campo}' não encontrado")
        
        # Verificar duplicatas por código legado
        if 'codigo_legado' in df.columns:
            codigos_duplicados = df['codigo_legado'].duplicated().sum()
            if codigos_duplicados > 0:
                print(f"  ⚠️  Códigos legados duplicados: {codigos_duplicados}")
            else:
                print(f"  ✅ Nenhum código legado duplicado")
        
        # Estatísticas de preenchimento
        print(f"\n📊 ESTATÍSTICAS DE PREENCHIMENTO:")
        print(f"  💼 Cargos com nome preenchido: {(df['nome'] != '').sum()}")
        print(f"  🏢 Cargos com empresa definida: {(df['id-empresa'] != '').sum()}")
        
        print(f"  ✅ Validação concluída")
        
    except Exception as e:
        print(f"  ❌ Erro na validação: {e}")

# Exemplo de uso
if __name__ == "__main__":
    # Executar integração completa automaticamente
    sucesso = processar_integracao_completa()
    if sucesso:
        print(f"\n🚀 INTEGRAÇÃO FINALIZADA COM SUCESSO!")
    else:
        print(f"\n💥 INTEGRAÇÃO FALHOU - Verifique os logs acima")