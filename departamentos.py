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
    Envia o CSV de departamentos para a API de destino via POST
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
        "pag": "configuracao_depto",
        "cmd": "importar_cad",
        "separador": ";"
    }
    
    try:
        print(f"📤 Enviando POST para API de destino...")
        print(f"🌐 URL: {config_target['url']}")
        print(f"👤 Usuário: {usuario_correto}")
        print(f"📄 Endpoint: configuracao_depto")
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
                    print(f"✅ POST de departamentos realizado com sucesso!")
                    print(f"📋 Resposta da API:")
                    print(json.dumps(resultado, indent=2, ensure_ascii=False))
                    
                    cadastrados = resultado.get('ok', 0)
                    if cadastrados > 0:
                        print(f"🎉 {cadastrados} departamento(s) cadastrado(s) com sucesso!")
                    
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

def extrair_departamentos_dos_funcionarios():
    """
    Extrai departamentos através dos relacionamentos dos funcionários
    """
    print("🔍 INICIANDO COLETA DE DEPARTAMENTOS...")
    
    # Obter headers do arquivo .config
    headers = obter_headers_api()
    if not headers:
        print("❌ Não foi possível obter o token do arquivo .config")
        return {}, None
    
    base_url = "https://dp.pack.alterdata.com.br/api/v1/funcionarios"
    
    departamentos_unicos = {}
    empresas_departamentos = {}

    params_base = {
        "filter[status]": "ativo",
        "include": "departamento,empresa",
        "page[limit]": "50",
    }
    print(f"Filtro de empresa ativo: {descrever_filtro_empresa()}")
    depts_ignorar = set(ler_departamentos_ignorar())
    if depts_ignorar:
        print(f"Departamentos ignorados: {', '.join(sorted(depts_ignorar))}")

    for empresa_consulta in empresas_para_consultar():
        params = dict(params_base)
        if empresa_consulta:
            params["filter[empresa.id]"] = empresa_consulta
            print(f"  Empresa {empresa_consulta}...")

        for pagina, data, funcionarios in get_jsonapi_paginado(
            base_url, headers, params=params, page_limit=50, pausa=0.3
        ):
            print(f"  📄 Processando página {pagina}... {len(funcionarios)} funcionários")
            included = data.get('included', [])
            included_depts = {}
            for item in included:
                if item.get('type') == 'departamentos':
                    included_depts[item.get('id')] = item.get('attributes', {})

            for funcionario in funcionarios:
                dept_relationship = funcionario.get('relationships', {}).get('departamento', {})
                empresa_relationship = funcionario.get('relationships', {}).get('empresa', {})

                dept_data = dept_relationship.get('data')
                empresa_data = empresa_relationship.get('data')
                if not dept_data:
                    continue

                dept_id = dept_data.get('id')
                if str(dept_id) in depts_ignorar:
                    continue
                empresa_id = (empresa_data or {}).get('id') or empresa_consulta or ''
                chave = (dept_id, empresa_id)

                if dept_id not in empresas_departamentos:
                    empresas_departamentos[dept_id] = empresa_id

                if chave not in departamentos_unicos:
                    dept_attributes = included_depts.get(dept_id, {})
                    departamentos_unicos[chave] = {
                        'id': dept_id,
                        'codigo': dept_attributes.get('externoid', ''),
                        'nome': dept_attributes.get('nome', ''),
                        'cei': dept_attributes.get('cei', ''),
                        'funcionarios_exemplo': [],
                        'empresa_id': empresa_id
                    }

                if len(departamentos_unicos[chave]['funcionarios_exemplo']) < 3:
                    departamentos_unicos[chave]['funcionarios_exemplo'].append({
                        'id': funcionario.get('id'),
                        'nome': funcionario.get('attributes', {}).get('nome', '')
                    })
    
    print(f"\n✅ Total de departamentos únicos encontrados: {len(departamentos_unicos)}")
    print(f"📊 Mapeamentos departamento->empresa: {len(empresas_departamentos)}")
    
    return departamentos_unicos, headers

def mapear_departamento_para_csv(dept_id, dados_departamento):
    """
    Mapeia um departamento para o formato esperado no CSV
    """
    # Mapeamento dos campos conforme a query original
    codigo = dados_departamento.get('id') or dept_id
    if isinstance(codigo, tuple):
        codigo = codigo[0]
    departamento_csv = {
        'campo_chave': 'codigo_legado',
        'codigo_legado': codigo,
        'nome': dados_departamento['nome'],
        'conta': codigo,
        'id-empresa': dados_departamento['empresa_id']
    }
    
    return departamento_csv

def gerar_csv_departamentos():
    """
    Função principal para gerar o CSV dos departamentos
    """
    print("=" * 80)
    print("         🏢 GERAÇÃO DE CSV DE DEPARTAMENTOS - API eContador")
    print("=" * 80)
    
    # Verificar se token está disponível
    token = ler_token_config()
    if not token:
        print("❌ Falha ao carregar token do arquivo .config")
        return None
    
    # Extrair departamentos dos funcionários
    departamentos_dict, headers = extrair_departamentos_dos_funcionarios()
    
    if not departamentos_dict:
        print("❌ Nenhum departamento foi extraído dos funcionários")
        return
    
    print(f"\n🔄 Convertendo {len(departamentos_dict)} departamentos para formato CSV...")
    
    # Converter para formato CSV
    departamentos_csv = []
    erros = []
    departamentos_com_empresa = 0
    
    for dept_id, dados_departamento in departamentos_dict.items():
        try:
            departamento_csv = mapear_departamento_para_csv(dept_id, dados_departamento)
            departamentos_csv.append(departamento_csv)
            
            if dados_departamento['empresa_id']:
                departamentos_com_empresa += 1
                
        except Exception as e:
            erros.append({'id': dept_id, 'erro': str(e)})
            print(f"  ❌ Erro ao processar departamento {dept_id}: {e}")
    
    if not departamentos_csv:
        print("❌ Nenhum departamento foi convertido com sucesso")
        return
    
    # Criar DataFrame
    print(f"\n📊 Criando DataFrame com {len(departamentos_csv)} departamentos...")
    df = pd.DataFrame(departamentos_csv)
    
    # Ordenar por código legado
    df = df.sort_values('codigo_legado')
    
    # Gerar arquivo CSV
    nome_arquivo = f"departamentos_api.csv"
    
    try:
        df.to_csv(nome_arquivo, index=False, encoding='utf-8-sig', sep=';')
        print(f"✅ CSV gerado com sucesso: {nome_arquivo}")
        
        # Estatísticas
        print(f"\n📈 ESTATÍSTICAS:")
        print(f"  🏢 Total de departamentos processados: {len(departamentos_csv)}")
        print(f"  🏭 Departamentos com empresa associada: {departamentos_com_empresa}")
        print(f"  ❌ Erros de conversão: {len(erros)}")
        print(f"  📋 Colunas no CSV: {len(df.columns)}")
        print(f"  💾 Arquivo gerado: {nome_arquivo}")
        
        # Mostrar preview dos dados
        print(f"\n👁️  PREVIEW DOS DADOS (primeiras 5 linhas):")
        print(df.head(5).to_string())
        
        # Salvar relatório de erros se houver
        if erros:
            arquivo_erros = f"erros_departamentos.json"
            with open(arquivo_erros, 'w', encoding='utf-8') as f:
                json.dump(erros, f, indent=2, ensure_ascii=False)
            print(f"\n⚠️  Relatório de erros salvo em: {arquivo_erros}")
        
        # Salvar dados detalhados dos departamentos
        dados_detalhados = {
            'departamentos_extraidos': departamentos_dict,
            'total_departamentos': len(departamentos_csv),
            'departamentos_com_empresa': departamentos_com_empresa,
            'timestamp': datetime.now().isoformat()
        }
        
        with open('departamentos_dados_detalhados.json', 'w', encoding='utf-8') as f:
            json.dump(dados_detalhados, f, indent=2, ensure_ascii=False)
        print(f"💾 Dados detalhados salvos em 'departamentos_dados_detalhados.json'")
        
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
    print("    🚀 INTEGRAÇÃO COMPLETA DE DEPARTAMENTOS - eContador → Sistema Destino")
    print("=" * 80)
    
    # Etapa 1: Gerar CSV dos departamentos
    print("\n📋 ETAPA 1: Coletando departamentos da API eContador...")
    arquivo_csv = gerar_csv_departamentos()
    
    if not arquivo_csv:
        print("❌ Falha na geração do CSV. Processo interrompido.")
        return False
    
    # Etapa 2: Validar dados
    print("\n🔍 ETAPA 2: Validando dados do CSV...")
    validar_dados_departamentos_csv(arquivo_csv)
    
    # Etapa 3: Enviar para API de destino
    print("\n📤 ETAPA 3: Enviando CSV para API de destino...")
    sucesso_envio = enviar_csv_para_api_target(arquivo_csv)
    
    if sucesso_envio:
        print("\n🎉 INTEGRAÇÃO COMPLETA FINALIZADA COM SUCESSO!")
        print(f"✅ Departamentos coletados da API eContador")
        print(f"✅ CSV gerado: {arquivo_csv}")
        print(f"✅ Dados enviados para sistema de destino")
        return True
    else:
        print("\n💥 FALHA NA INTEGRAÇÃO!")
        print(f"✅ CSV gerado: {arquivo_csv}")
        print(f"❌ Falha no envio para sistema de destino")
        return False

def validar_dados_departamentos_csv(nome_arquivo):
    """
    Valida os dados do CSV de departamentos gerado
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
        print(f"  🏢 Departamentos com nome preenchido: {(df['nome'] != '').sum()}")
        print(f"  🏭 Departamentos com empresa definida: {(df['id-empresa'] != '').sum()}")
        print(f"  📊 Departamentos com conta definida: {(df['conta'] != '').sum()}")
        
        # Verificar distribuição por empresa
        if 'id-empresa' in df.columns:
            empresas_unicas = df[df['id-empresa'] != '']['id-empresa'].nunique()
            print(f"  🏭 Total de empresas diferentes: {empresas_unicas}")
        
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