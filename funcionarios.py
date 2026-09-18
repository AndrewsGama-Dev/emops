import os
import tempfile
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
    ler_departamentos_ignorar,
    funcionario_departamento_ignorado,
)

ARQUIVO_FUNCIONARIOS_IGNORAR = "funcionarios_ignorar.txt"


def carregar_cpfs_funcionarios_ignorar(caminho=ARQUIVO_FUNCIONARIOS_IGNORAR):
    """
    Lê CPFs a ignorar no CSV de funcionários.
    Formato por linha: CPF;NOME  (nome opcional). # e linhas vazias são ignorados.
    """
    if not os.path.exists(caminho):
        return set()

    cpfs = set()
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                texto = linha.strip()
                if not texto or texto.startswith("#"):
                    continue
                # Aceita CPF;NOME ou só CPF
                parte_cpf = texto.split(";", 1)[0].strip()
                cpf = formatar_cpf_11_digitos(parte_cpf)
                if len(cpf) == 11:
                    cpfs.add(cpf)
    except OSError as e:
        print(f"⚠️  Não foi possível ler {caminho}: {e}")
    return cpfs


def salvar_dataframe_csv_funcionarios(df, nome_preferido="funcionarios_api.csv"):
    """
    Grava o DataFrame em CSV. Se o arquivo padrão estiver bloqueado (Excel, OneDrive),
    tenta outro nome na mesma pasta e, por último, na pasta temp do sistema.
    """
    base, ext = os.path.splitext(nome_preferido)
    if not ext:
        ext = ".csv"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidatos = [
        nome_preferido,
        f"{base}_{stamp}{ext}",
        os.path.join(tempfile.gettempdir(), f"{base}_{stamp}{ext}"),
    ]

    ultimo_erro = None
    for caminho in candidatos:
        try:
            df.to_csv(caminho, index=False, encoding="utf-8-sig", sep=";")
            if caminho != nome_preferido:
                print(
                    f"⚠️  Não foi possível sobrescrever '{nome_preferido}' (arquivo em uso ou bloqueado)."
                )
                print(f"✅ CSV salvo em: {os.path.abspath(caminho)}")
            else:
                print(f"✅ CSV gerado com sucesso: {caminho}")
            return caminho
        except PermissionError as e:
            ultimo_erro = e
            continue
        except OSError as e:
            if getattr(e, "errno", None) == 13:
                ultimo_erro = e
                continue
            raise

    print("❌ Não foi possível gravar o CSV (permissão negada).")
    print("   Sugestões:")
    print("   • Feche o arquivo funcionarios_api.csv no Excel (ou outro programa).")
    print("   • Se a pasta está no OneDrive, aguarde a sincronização ou use 'Sempre manter neste dispositivo'.")
    if ultimo_erro:
        print(f"   Detalhe: {ultimo_erro}")
    return None

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

def formatar_cpf_11_digitos(cpf):
    """
    Formata CPF para garantir 11 dígitos com zeros à esquerda
    """
    if not cpf:
        return ""
    
    # Converter para string e remover caracteres não numéricos
    cpf_str = str(cpf).replace('.', '').replace('-', '').replace('/', '').strip()
    
    # Se não for numérico ou estiver vazio, retornar vazio
    if not cpf_str.isdigit():
        return ""
    
    # Completar com zeros à esquerda para 11 dígitos
    cpf_formatado = cpf_str.zfill(11)
    
    # Validar se tem exatamente 11 dígitos
    if len(cpf_formatado) == 11:
        return cpf_formatado
    
    return ""

def enviar_csv_para_api_target(nome_arquivo_csv):
    """
    Envia o CSV de funcionários para a API da Hevi
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
    
    usuario_integracao = config_target['integracao']
    
    headers = {
        "user": usuario_integracao,
        "token": token_final
    }
    
    data = {
        "pag": "funcionario_cadastrar",
        "cmd": "importar_cad",
        "separador": ";"
    }
    
    try:
        print(f"📤 Enviando POST para API da Hevi...")
        print(f"🌐 URL: {config_target['url']}")
        print(f"👤 Usuário: {usuario_integracao}")
        print(f"📄 Endpoint: funcionario_cadastrar")
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
                timeout=120
            )
        
        print(f"📊 Status da resposta: {response.status_code}")
        
        if response.status_code == 200:
            try:
                resultado = response.json()
                
                if resultado.get('success') == False:
                    print(f"❌ API retornou erro:")
                    print(f"📝 Resposta: {json.dumps(resultado, indent=2, ensure_ascii=False)}")
                    return False
                else:
                    print(f"✅ POST de funcionários realizado com sucesso!")
                    print(f"📋 Resposta da API:")
                    print(json.dumps(resultado, indent=2, ensure_ascii=False))
                    
                    cadastrados = resultado.get('ok', 0)
                    if cadastrados > 0:
                        print(f"🎉 {cadastrados} funcionário(s) cadastrado(s) com sucesso!")
                    
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
        print(f"❌ ERRO na requisição para API da Hevi: {e}")
        return False

def buscar_dados_empresa(funcionario_id, headers):
    """
    Busca informações da empresa do funcionário
    """
    try:
        url_empresa = f"https://dp.pack.alterdata.com.br/api/v1/funcionarios/{funcionario_id}/empresa"
        response = requests.get(url_empresa, headers=headers)
        
        if response.status_code == 200:
            empresa_data = response.json()
            empresa_info = empresa_data.get('data', {})
            if empresa_info:
                attributes = empresa_info.get('attributes', {})
                return {
                    'id': empresa_info.get('id', ''),
                    'codigo': attributes.get('codigo', ''),
                    'nome': attributes.get('nome', ''),
                    'cnpj': attributes.get('cnpj', '')
                }
    except Exception as e:
        pass
    
    return None

def extrair_codigo_departamento(externoid, nome, cei, id_departamento):
    """
    Para seguir o padrão da query SQL que funciona, usar o ID do departamento
    """
    # Na query SQL que funciona, eles usam: col.ID_CENTRO_CUSTO AS codigo_unidade
    # Então vamos usar o ID do departamento diretamente
    if id_departamento:
        return str(id_departamento)
    
    # Estratégia alternativa: externoid válido
    if externoid and len(externoid) < 15 and not externoid.startswith('ZZZG7') and externoid != '':
        return externoid
    
    # Extrair código do nome se possível
    if nome and ' - ' in nome:
        partes = nome.split(' - ', 1)
        if len(partes) >= 2:
            possivel_codigo = partes[0].strip()
            if possivel_codigo.isdigit() and len(possivel_codigo) <= 6:
                return possivel_codigo
    
    # Fallback
    return str(id_departamento) if id_departamento else "1"

def extrair_nome_limpo_departamento(nome):
    """
    Extrai apenas o nome do departamento, removendo códigos
    """
    if not nome:
        return ""
    
    if ' - ' in nome:
        partes = nome.split(' - ', 1)
        if len(partes) >= 2:
            return partes[1].strip()
    
    return nome.strip()

def extrair_nome_limpo_cargo(nome_funcao):
    """
    Extrai apenas o nome do cargo, removendo códigos
    """
    if not nome_funcao:
        return ""
    
    if ' - ' in nome_funcao:
        partes = nome_funcao.split(' - ', 1)
        if len(partes) >= 2:
            return partes[1].strip()
    
    return nome_funcao.strip()

def buscar_dados_departamento(funcionario_id, headers):
    """
    Busca informações do departamento do funcionário
    """
    try:
        # Primeira tentativa: buscar funcionário com include do departamento
        url_funcionario = f"https://dp.pack.alterdata.com.br/api/v1/funcionarios/{funcionario_id}?include=departamento"
        response = requests.get(url_funcionario, headers=headers)
        
        if response.status_code == 200:
            funcionario_data = response.json()
            
            # Verificar se há dados included (departamento)
            included = funcionario_data.get('included', [])
            for item in included:
                if item.get('type') == 'departamentos':
                    attributes = item.get('attributes', {})
                    externoid = attributes.get('externoid', '')
                    nome = attributes.get('nome', '')
                    cei = attributes.get('cei', '')
                    
                    codigo_final = extrair_codigo_departamento(externoid, nome, cei, item.get('id', ''))
                    
                    return {
                        'id': item.get('id', ''),
                        'codigo': codigo_final,
                        'nome': extrair_nome_limpo_departamento(nome),
                        'cei': cei
                    }
            
            # Se não encontrou nos included, verificar relationships
            data_list = funcionario_data.get('data', [])
            if isinstance(data_list, list) and data_list:
                relationships = data_list[0].get('relationships', {})
            elif isinstance(data_list, dict):
                relationships = data_list.get('relationships', {})
            else:
                relationships = {}
                
            departamento_rel = relationships.get('departamento', {})
            departamento_data = departamento_rel.get('data')
            
            if departamento_data:
                departamento_id = departamento_data.get('id')
                if departamento_id:
                    # Buscar departamento diretamente
                    url_departamento = f"https://dp.pack.alterdata.com.br/api/v1/departamentos/{departamento_id}"
                    dept_response = requests.get(url_departamento, headers=headers)
                    
                    if dept_response.status_code == 200:
                        dept_data = dept_response.json()
                        dept_attributes = dept_data.get('data', {}).get('attributes', {})
                        
                        externoid = dept_attributes.get('externoid', '')
                        nome = dept_attributes.get('nome', '')
                        cei = dept_attributes.get('cei', '')
                        
                        codigo_final = extrair_codigo_departamento(externoid, nome, cei, departamento_id)
                        
                        return {
                            'id': departamento_id,
                            'codigo': codigo_final,
                            'nome': extrair_nome_limpo_departamento(nome),
                            'cei': cei
                        }
        
        # Segunda tentativa: buscar departamento através do endpoint direto
        url_departamento_funcionario = f"https://dp.pack.alterdata.com.br/api/v1/funcionarios/{funcionario_id}/departamento"
        dept_response = requests.get(url_departamento_funcionario, headers=headers)
        
        if dept_response.status_code == 200:
            dept_data = dept_response.json()
            dept_info = dept_data.get('data', {})
            if dept_info:
                attributes = dept_info.get('attributes', {})
                
                externoid = attributes.get('externoid', '')
                nome = attributes.get('nome', '')
                cei = attributes.get('cei', '')
                
                codigo_final = extrair_codigo_departamento(externoid, nome, cei, dept_info.get('id', ''))
                
                return {
                    'id': dept_info.get('id', ''),
                    'codigo': codigo_final,
                    'nome': extrair_nome_limpo_departamento(nome),
                    'cei': cei
                }
                        
    except Exception as e:
        print(f"⚠️ Erro ao buscar departamento do funcionário {funcionario_id}: {e}")
    
    return None

# Relacionamentos documentados em GET /api/v1/funcionarios?include=...
# (ePlugin — naturalidade/estado vêm como estados; sexo/estadocivil/escolaridade como tipos-*)
INCLUDE_FUNCIONARIOS_BASE = (
    "naturalidade,estado,estadocivil,departamento,sexo,nacionalidade,pais"
)
INCLUDE_FUNCIONARIOS_OPCIONAL_ESCOLARIDADE = INCLUDE_FUNCIONARIOS_BASE + ",escolaridade"


def _acumular_included(acumulado, included_list):
    """Mescla recursos do array included (JSON:API) num índice type:id."""
    if not included_list:
        return
    for item in included_list:
        if not item or item.get("id") is None:
            continue
        chave = f'{item.get("type")}:{item.get("id")}'
        acumulado[chave] = item


def _buscar_included(indice, tipo, id_ref):
    """Recupera um recurso included pelo type e id."""
    if id_ref is None or tipo is None:
        return None
    return indice.get(f'{tipo}:{id_ref}')


def _relacionamento_data(funcionario, nome_rel):
    """Retorna (type, id) do relationship ou (None, None)."""
    rels = funcionario.get('relationships') or {}
    bloco = rels.get(nome_rel) or {}
    data = bloco.get('data')
    if not data:
        return None, None
    return data.get('type'), data.get('id')


def extrair_campos_api_included(funcionario_api, indice_included):
    """
    Preenche sexo, estado civil, escolaridade, nacionalidade, naturalidade, UF (estado),
    orgão emissor e nomes dos pais a partir de attributes + included.
    """
    attributes = funcionario_api.get('attributes', {})

    # ---- Atributos diretos (documentação ePlugin / exemplo funcionário) ----
    bairro = (attributes.get('bairro') or '').strip()
    nome_mae = (
        attributes.get('nomedamae')
        or attributes.get('nomeMae')
        or attributes.get('nome_mae')
        or ''
    )
    nome_mae = str(nome_mae).strip() if nome_mae else ''
    nome_pai = (
        attributes.get('nomedopai')
        or attributes.get('nomePai')
        or attributes.get('nome_pai')
        or ''
    )
    nome_pai = str(nome_pai).strip() if nome_pai else ''

    org_emissor = (
        attributes.get('orgaoemissor')
        or attributes.get('orgaoemissoridentidade')
        or attributes.get('orgaoEmissorIdentidade')
        or ''
    )
    org_emissor = str(org_emissor).strip() if org_emissor else ''

    qtd_filho = attributes.get('quantidadefilhos')
    if qtd_filho is None:
        qtd_filho = attributes.get('qtdfilhos')
    if qtd_filho is None:
        qtd_filho = attributes.get('numerodependentes')
    qtd_str = '' if qtd_filho is None else str(qtd_filho)

    # ---- Relacionamentos via included ----
    def desc_tipo(rel_name, tipo_recurso):
        t, i = _relacionamento_data(funcionario_api, rel_name)
        if not t or not i:
            return ''
        rec = _buscar_included(indice_included, t, i)
        if not rec:
            return ''
        a = rec.get('attributes') or {}
        if tipo_recurso == 'pais':
            return (a.get('nome') or a.get('sigla') or '').strip()
        if tipo_recurso == 'estados':
            return (a.get('nome') or '').strip()
        # tipos-sexo, tipos-estado-civil, tipos-escolaridade
        return (a.get('descricao') or a.get('nome') or '').strip()

    sexo = desc_tipo('sexo', 'tipo')
    estado_civil = desc_tipo('estadocivil', 'tipo')
    escolaridade = desc_tipo('escolaridade', 'tipo')
    if not escolaridade:
        escolaridade = (attributes.get('escolaridade') or '')
        if escolaridade and not isinstance(escolaridade, str):
            escolaridade = str(escolaridade)

    nacionalidade = desc_tipo('nacionalidade', 'pais')

    naturalidade = desc_tipo('naturalidade', 'estados')

    t_est, id_est = _relacionamento_data(funcionario_api, 'estado')
    uf_sigla = ''
    estado_nome = ''
    if t_est and id_est:
        est = _buscar_included(indice_included, t_est, id_est)
        if est:
            ea = est.get('attributes') or {}
            uf_sigla = (ea.get('sigla') or '').strip()
            estado_nome = (ea.get('nome') or '').strip()

    # Fallback UF em atributo texto, se houver
    if not uf_sigla:
        uf_sigla = (attributes.get('uf') or attributes.get('estado') or '')
        if uf_sigla and not isinstance(uf_sigla, str):
            uf_sigla = str(uf_sigla)

    return {
        'bairro': bairro,
        'nome_mae': nome_mae,
        'nome_pai': nome_pai,
        'orgao_emissor_rg': org_emissor,
        'qtd_filho': qtd_str,
        'sexo': sexo,
        'estado_civil': estado_civil,
        'escolaridade': escolaridade,
        'nacionalidade': nacionalidade,
        'naturalidade': naturalidade,
        'uf': uf_sigla,
        'estado_endereco_nome': estado_nome,
    }

def consultar_todos_funcionarios_para_csv():
    """
    Coleta APENAS funcionários ATIVOS da API, com include dos relacionamentos
    (sexo, estado civil, nacionalidade, naturalidade, estado/UF, escolaridade quando disponível).
    Se [FILTROS].codigo_empresa estiver no .config, restringe a essas empresas
    (um ID ou vários: 9,10,11).
    """
    print("🔍 INICIANDO COLETA DE FUNCIONÁRIOS ATIVOS PARA CSV...")
    
    headers = obter_headers_api()
    if not headers:
        print("❌ Não foi possível obter o token do arquivo .config")
        return [], None, {}

    print(f"🏭 Filtro de empresa ativo: {descrever_filtro_empresa()}")
    depts_ignorar = ler_departamentos_ignorar()
    if depts_ignorar:
        print(f"🚫 Departamentos ignorados: {', '.join(depts_ignorar)}")
    
    base_url = "https://dp.pack.alterdata.com.br/api/v1/funcionarios"
    
    params_base = {
        "filter[status]": "ativo",
        "sort": "codigo",
        "page[limit]": "100",
        "include": INCLUDE_FUNCIONARIOS_OPCIONAL_ESCOLARIDADE,
    }

    todos_funcionarios = []
    included_global = {}
    pagina_global = 0
    ignorados_departamento = 0
    include_usado = INCLUDE_FUNCIONARIOS_OPCIONAL_ESCOLARIDADE
    page_limit = 100
    max_tentativas_sem_dados = 3

    for empresa_id in empresas_para_consultar():
        params = dict(params_base)
        params["include"] = include_usado
        params["page[limit]"] = str(page_limit)
        if empresa_id:
            params["filter[empresa.id]"] = empresa_id
            print(f"  🏭 Empresa {empresa_id}...")

        pagina = 1
        offset = 0
        tentativas_sem_dados = 0

        while tentativas_sem_dados < max_tentativas_sem_dados:
            try:
                params["page[offset]"] = str(offset)
                print(f"  📄 Coletando página {pagina}... ", end="")

                response = requests.get(base_url, headers=headers, params=params, timeout=60)
                if pagina == 1 and response.status_code >= 400 and include_usado != INCLUDE_FUNCIONARIOS_BASE:
                    print(f"\n  ⚠️ Include com escolaridade falhou ({response.status_code}); tentando sem escolaridade...")
                    include_usado = INCLUDE_FUNCIONARIOS_BASE
                    params["include"] = include_usado
                    params_base["include"] = include_usado
                    response = requests.get(base_url, headers=headers, params=params, timeout=60)

                print(f"Status: {response.status_code}")

                if response.status_code == 200:
                    data = response.json()
                    funcionarios_pagina = data.get('data', [])
                    _acumular_included(included_global, data.get('included'))

                    if funcionarios_pagina:
                        if depts_ignorar:
                            aceitos = []
                            for funcionario in funcionarios_pagina:
                                if funcionario_departamento_ignorado(funcionario):
                                    ignorados_departamento += 1
                                    continue
                                aceitos.append(funcionario)
                            todos_funcionarios.extend(aceitos)
                            print(
                                f"    ✅ {len(aceitos)} ativos "
                                f"(ignorados dept: {len(funcionarios_pagina) - len(aceitos)}; "
                                f"Total: {len(todos_funcionarios)})"
                            )
                        else:
                            todos_funcionarios.extend(funcionarios_pagina)
                            print(f"    ✅ {len(funcionarios_pagina)} funcionários ATIVOS coletados (Total: {len(todos_funcionarios)})")
                        tentativas_sem_dados = 0
                        pagina_global += 1

                        if len(funcionarios_pagina) < page_limit:
                            print(f"    📋 Última página desta empresa")
                            break

                        offset += page_limit
                        pagina += 1
                        time.sleep(0.2)
                    else:
                        print(f"    ⚠️ Página sem dados")
                        tentativas_sem_dados += 1
                        break

                elif response.status_code == 429:
                    print(f"    ⏰ Rate limit - aguardando 10 segundos...")
                    time.sleep(10)
                    continue
                else:
                    print(f"    ❌ Erro {response.status_code}: {response.text[:100]}")
                    tentativas_sem_dados += 1
                    break

            except requests.exceptions.RequestException as e:
                print(f"    ❌ Erro na conexão: {e}")
                tentativas_sem_dados += 1
                time.sleep(2)
    
    print(f"\n✅ COLETA FINALIZADA:")
    print(f"  📊 Total de funcionários ATIVOS coletados: {len(todos_funcionarios)}")
    if depts_ignorar:
        print(f"  🚫 Ignorados por departamento ({', '.join(depts_ignorar)}): {ignorados_departamento}")
    print(f"  📄 Páginas processadas: {pagina_global}")
    print(f"  🔗 Recursos included únicos (tipos relacionados): {len(included_global)}")
    
    return todos_funcionarios, headers, included_global

def formatar_data_brasileira(data_iso):
    """
    Converte data ISO para formato brasileiro DD/MM/AAAA
    """
    if not data_iso:
        return ""
    
    try:
        data_str = data_iso.replace('Z', '').split('T')[0]
        data_obj = datetime.strptime(data_str, '%Y-%m-%d')
        return data_obj.strftime('%d/%m/%Y')
    except Exception as e:
        return ""

def mapear_funcionario_para_csv(funcionario_api, headers=None, included_index=None):
    """
    Mapeia um funcionário da API para o formato esperado no CSV
    Baseado na query SQL que funciona com a API Hevi.
    `included_index`: dicionário JSON:API type:id -> recurso (do include na listagem).
    """
    attributes = funcionario_api.get('attributes', {})
    funcionario_id = funcionario_api.get('id', '')
    indice = included_index if included_index is not None else {}
    
    # PRIMEIRO: Formatar CPF com 11 dígitos (zeros à esquerda)
    cpf_formatado = formatar_cpf_11_digitos(attributes.get('cpf', ''))
    
    # SEGUNDO: Usar o campo 'codigo' dos atributos em vez do ID
    codigo_funcionario = attributes.get('codigo', '')
    if not codigo_funcionario:
        # Fallback para o ID se não tiver código
        codigo_funcionario = str(funcionario_id).zfill(6)
    
    # TERCEIRO: Buscar dados da empresa e departamento
    empresa_info = None
    departamento_info = None
    
    if headers and funcionario_id:
        empresa_info = buscar_dados_empresa(funcionario_id, headers)
        departamento_info = buscar_dados_departamento(funcionario_id, headers)
    
    # Campos vindos da API (attributes + relacionamentos include)
    ex = extrair_campos_api_included(funcionario_api, indice)
    
    funcionario_csv = {
        'nome': attributes.get('nome', ''),
        'cpf': cpf_formatado,  # CPF formatado com 11 dígitos
        'matricula': codigo_funcionario,  # Campo 'codigo' da API
        'rg': attributes.get('identidade', ''),
        'pis': attributes.get('pis', '') or cpf_formatado,  # CPF como fallback
        'dtadmissao': formatar_data_brasileira(attributes.get('admissao')),
        'cnh': '',
        'email': attributes.get('email', ''),
        'nome_tipo_pessoa': '',
        'telefone': '',
        'ramal': '',
        'endereco': attributes.get('rua', ''),
        'bairro': ex['bairro'],
        'cidade': attributes.get('cidade', ''),
        'uf': ex['uf'],
        'cep': attributes.get('cep', ''),
        'login': cpf_formatado,  # CPF formatado
        'cod_empresa': empresa_info.get('id', '') if empresa_info else '',
        'codigo_legado_empresa': empresa_info.get('id', '') if empresa_info else '',
        'dtdemissao': '',
        'regime_juridico': '',
        'tipo_salario': '',
        'salario': str(attributes.get('salarioBase', '')),
        'dtnascimento': formatar_data_brasileira(attributes.get('nascimento')),
        'nome_mae': ex['nome_mae'],
        'nome_pai': ex['nome_pai'],
        'escolaridade': ex['escolaridade'],
        'estado_civil': ex['estado_civil'],
        'qtd_filho': ex['qtd_filho'],
        'sexo': ex['sexo'],
        'nacionalidade': ex['nacionalidade'],
        'naturalidade': ex['naturalidade'],
        'complemento': attributes.get('complemento', ''),
        # Campos baseados na query SQL de referência
        'codigo_unidade': departamento_info.get('id', '') if departamento_info else '',
        'nome_unidade': extrair_nome_limpo_departamento(departamento_info.get('nome', '')) if departamento_info else '',
        'codigo_cargo': '',  # Será preenchido abaixo
        'nome_cargo': extrair_nome_limpo_cargo(attributes.get('nomefuncao', '')),
        'cracha': cpf_formatado,  # CPF formatado
        'nome_nivel': '',
        'cod_escala_padrao': '',
        'codigo_escala': '',
        'dtinicio_escala': '',
        'empresa': empresa_info.get('nome', '') if empresa_info else '',
        'nome_funcao': extrair_nome_limpo_cargo(attributes.get('nomefuncao', '')),
        'codigo_legado_funcao': '',  # Será preenchido abaixo
        'nro_centro_custo': departamento_info.get('id', '') if departamento_info else '',
        'codigo_legado_centro_custo': departamento_info.get('id', '') if departamento_info else '',
        'nome_centro_custo': extrair_nome_limpo_departamento(departamento_info.get('nome', '')) if departamento_info else '',
        'cod_sindicato': '',
        'nome_sindicato': '',
        'orgao_emissor_rg': ex['orgao_emissor_rg'],
        'timezone': 'America/Manaus'
    }
    
    # Extrair código do cargo do campo nomefuncao
    nome_funcao = attributes.get('nomefuncao', '')
    if nome_funcao and ' - ' in nome_funcao:
        try:
            partes = nome_funcao.split(' - ', 1)
            if len(partes) >= 2:
                codigo_funcao = partes[0].strip()
                if codigo_funcao:
                    funcionario_csv['codigo_cargo'] = codigo_funcao
                    funcionario_csv['codigo_legado_funcao'] = codigo_funcao
        except Exception as e:
            pass
    
    return funcionario_csv

def gerar_csv_funcionarios():
    """
    Função principal para gerar o CSV dos funcionários ATIVOS
    """
    print("=" * 80)
    print("         🚀 GERAÇÃO DE CSV DE FUNCIONÁRIOS ATIVOS - API eContador")
    print("=" * 80)
    
    token = ler_token_config()
    if not token:
        print("❌ Falha ao carregar token do arquivo .config")
        return None
    
    funcionarios_api, headers, included_global = consultar_todos_funcionarios_para_csv()
    
    if not funcionarios_api:
        print("❌ Nenhum funcionário ATIVO foi coletado da API")
        return
    
    print(f"\n🔄 Convertendo {len(funcionarios_api)} funcionários ATIVOS para formato CSV...")

    cpfs_ignorar = carregar_cpfs_funcionarios_ignorar()
    if cpfs_ignorar:
        print(
            f"🚫 Lista de exclusão ativa ({ARQUIVO_FUNCIONARIOS_IGNORAR}): "
            f"{len(cpfs_ignorar)} CPF(s)"
        )
    
    funcionarios_csv = []
    erros = []
    ignorados = 0
    
    for i, funcionario_api in enumerate(funcionarios_api, 1):
        try:
            attrs = funcionario_api.get("attributes") or {}
            cpf_api = formatar_cpf_11_digitos(attrs.get("cpf", ""))
            if cpf_api and cpf_api in cpfs_ignorar:
                ignorados += 1
                nome_ign = (attrs.get("nome") or "").strip()
                print(f"  🚫 Ignorado (lista): {nome_ign or cpf_api} | CPF {cpf_api}")
                continue

            funcionario_csv = mapear_funcionario_para_csv(
                funcionario_api, headers, included_global
            )
            funcionarios_csv.append(funcionario_csv)
            
            if i % 10 == 0:
                print(f"  ✅ Processados {i}/{len(funcionarios_api)} funcionários...")
                time.sleep(0.5)
                
        except Exception as e:
            erros.append({'id': funcionario_api.get('id', 'N/A'), 'erro': str(e)})
            print(f"  ❌ Erro ao processar funcionário {funcionario_api.get('id', 'N/A')}: {e}")
    
    if not funcionarios_csv:
        print("❌ Nenhum funcionário foi convertido com sucesso")
        return
    
    print(f"\n📊 Criando DataFrame com {len(funcionarios_csv)} funcionários...")
    df = pd.DataFrame(funcionarios_csv)
    
    nome_arquivo = salvar_dataframe_csv_funcionarios(df)
    if not nome_arquivo:
        return None

    print(f"\n📈 ESTATÍSTICAS:")
    print(f"  📊 Total de funcionários processados: {len(funcionarios_csv)}")
    print(f"  🚫 Ignorados pela lista: {ignorados}")
    print(f"  ❌ Erros de conversão: {len(erros)}")
    print(f"  📋 Colunas no CSV: {len(df.columns)}")
    
    print(f"\n👁️ PREVIEW DOS DADOS (primeiras 3 linhas):")
    print(df.head(3).to_string())
    
    return nome_arquivo

def validar_dados_csv(nome_arquivo):
    """
    Valida os dados do CSV gerado
    """
    if not nome_arquivo:
        return
    
    try:
        print(f"\n🔍 VALIDANDO DADOS DO CSV: {nome_arquivo}")
        
        df = pd.read_csv(nome_arquivo, sep=';', encoding='utf-8-sig')
        
        print(f"  📊 Total de registros: {len(df)}")
        print(f"  📋 Total de colunas: {len(df.columns)}")
        
        campos_obrigatorios = ['nome', 'cpf', 'matricula']
        
        for campo in campos_obrigatorios:
            if campo in df.columns:
                vazios = df[campo].isna().sum() + (df[campo] == '').sum()
                if vazios > 0:
                    print(f"  ⚠️ Campo '{campo}': {vazios} registros vazios")
                else:
                    print(f"  ✅ Campo '{campo}': todos preenchidos")
        
        print(f"  ✅ Validação concluída")
        
    except Exception as e:
        print(f"  ❌ Erro na validação: {e}")

def processar_apenas_exportacao_csv():
    """
    Gera funcionarios_api.csv a partir da API eContador, sem enviar à Hevi.
    Útil para análise local do arquivo.
    """
    print("=" * 80)
    print("   EXPORTAR APENAS CSV (sem integração Hevi)")
    print("=" * 80)
    arquivo_csv = gerar_csv_funcionarios()
    if not arquivo_csv:
        print("Falha na geração do CSV.")
        return False
    validar_dados_csv(arquivo_csv)
    print(f"\nArquivo pronto para análise: {arquivo_csv}")
    return True

def processar_integracao_completa():
    """
    Função principal que executa todo o processo
    """
    print("=" * 80)
    print("    🚀 INTEGRAÇÃO COMPLETA DE FUNCIONÁRIOS ATIVOS - eContador → Hevi")
    print("=" * 80)
    
    print("\n📋 ETAPA 1: Coletando funcionários ATIVOS da API eContador...")
    arquivo_csv = gerar_csv_funcionarios()
    
    if not arquivo_csv:
        print("❌ Falha na geração do CSV. Processo interrompido.")
        return False
    
    print("\n🔍 ETAPA 2: Validando dados do CSV...")
    validar_dados_csv(arquivo_csv)
    
    print("\n📤 ETAPA 3: Enviando CSV para API da Hevi...")
    sucesso_envio = enviar_csv_para_api_target(arquivo_csv)
    
    if sucesso_envio:
        print("\n🎉 INTEGRAÇÃO COMPLETA FINALIZADA COM SUCESSO!")
        print(f"✅ Funcionários ATIVOS coletados da API eContador")
        print(f"✅ CSV gerado: {arquivo_csv}")
        print(f"✅ Dados enviados para sistema Hevi")
        return True
    else:
        print("\n💥 FALHA NA INTEGRAÇÃO!")
        print(f"✅ CSV gerado: {arquivo_csv}")
        print(f"❌ Falha no envio para sistema Hevi")
        return False

# Exemplo de uso
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        comando = sys.argv[1].lower()
        
        if comando in ("csv", "somente-csv", "export", "exportar"):
            ok = processar_apenas_exportacao_csv()
            sys.exit(0 if ok else 1)
        
        if comando == "enviar":
            arquivo = sys.argv[2] if len(sys.argv) > 2 else "funcionarios_api.csv"
            sucesso = enviar_csv_para_api_target(arquivo)
            sys.exit(0 if sucesso else 1)

        if comando == "integracao":
            sucesso = processar_integracao_completa()
            if sucesso:
                print(f"\n🚀 INTEGRAÇÃO FINALIZADA COM SUCESSO!")
            else:
                print(f"\n💥 INTEGRAÇÃO FALHOU - Verifique os logs acima")
            sys.exit(0 if sucesso else 1)
        else:
            print("Comandos disponíveis:")
            print("  python funcionarios.py csv         - Gerar só funcionarios_api.csv (sem enviar)")
            print("  python funcionarios.py enviar      - Envia funcionarios_api.csv para o stou")
            print("  python funcionarios.py integracao  - Gera CSV e envia")
            sys.exit(1)
    else:
        # Sem argumentos: só exporta CSV (análise local, sem integrar)
        ok = processar_apenas_exportacao_csv()
        sys.exit(0 if ok else 1)