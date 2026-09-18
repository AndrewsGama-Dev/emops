import requests
import json
import pandas as pd
from datetime import datetime, timedelta
import time
import configparser
import xml.etree.ElementTree as ET
import os
from config_reader import (
    obter_headers_api,
    ler_token_config,
    ler_config,
    historico_demissoes_habilitado,
    empresas_para_consultar,
    descrever_filtro_empresa,
    get_jsonapi_paginado,
    funcionario_departamento_ignorado,
    ler_departamentos_ignorar,
)
from funcionarios import gerar_token_target, formatar_cpf_11_digitos

NOME_ARQUIVO_CSV = "demissoes_api.csv"
ARQUIVO_HISTORICO_MATRICULAS = "demissoes_matricula_processados.txt"

COLUNAS_CSV_DEMISSOES = [
    "campo_chave",
    "cpf",
    "nome",
    "DATA_DEMISSAO",
    "obs",
    "data_aviso",
    "data_ultimo_dia_trabalhado",
    "data_acerto",
    "motivo",
    "local_exame",
    "opcao_empregado",
    "tipo_aviso",
    "devolveu_cracha",
    "dias_indenizados",
    "data_exame",
]

def formatar_matricula_simples(codigo):
    """Matricula no padrao atual da integracao: 6 digitos com zeros a esquerda."""
    if codigo is None or str(codigo).strip() == "":
        return ""
    return str(codigo).strip().zfill(6)


def ler_campo_chave_config():
    """Chave de identificacao no ifPonto. Padrao: cpf."""
    cfg = ler_config()
    if cfg and "APITARGET" in cfg:
        chave = (cfg["APITARGET"].get("campo_chave") or "cpf").strip().strip('"').strip("'")
        return chave.lower() if chave else "cpf"
    return "cpf"


def formatar_cpf_com_mascara_csv(cpf):
    """CPF no CSV (XXX.XXX.XXX-XX). Usado como campo_chave nesta integracao."""
    digitos = formatar_cpf_11_digitos(cpf)
    if len(digitos) != 11:
        return ""
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def carregar_matriculas_demissoes_processadas():
    if not historico_demissoes_habilitado():
        print(
            f"Historico de demissoes DESLIGADO ([FILTROS] historico_demissoes=false) — "
            f"ignorando {ARQUIVO_HISTORICO_MATRICULAS}."
        )
        return set()
    if not os.path.exists(ARQUIVO_HISTORICO_MATRICULAS):
        return set()
    matriculas = set()
    try:
        with open(ARQUIVO_HISTORICO_MATRICULAS, "r", encoding="utf-8") as f:
            for linha in f:
                mat = formatar_matricula_simples(linha.strip())
                if mat:
                    matriculas.add(mat)
    except OSError as e:
        print(f"AVISO: nao foi possivel ler {ARQUIVO_HISTORICO_MATRICULAS}: {e}")
    return matriculas


def registrar_matriculas_demissoes_processadas(matriculas_novas):
    if not historico_demissoes_habilitado():
        print(
            f"Historico de demissoes DESLIGADO — nao gravando {ARQUIVO_HISTORICO_MATRICULAS}."
        )
        return
    novas = []
    for matricula in matriculas_novas:
        norm = formatar_matricula_simples(matricula)
        if norm:
            novas.append(norm)
    if not novas:
        return
    # Carrega do arquivo direto (sem o early-return do flag) para unificar
    atual = set()
    if os.path.exists(ARQUIVO_HISTORICO_MATRICULAS):
        try:
            with open(ARQUIVO_HISTORICO_MATRICULAS, "r", encoding="utf-8") as f:
                for linha in f:
                    mat = formatar_matricula_simples(linha.strip())
                    if mat:
                        atual.add(mat)
        except OSError as e:
            print(f"AVISO: nao foi possivel ler {ARQUIVO_HISTORICO_MATRICULAS}: {e}")
    atual.update(novas)
    try:
        with open(ARQUIVO_HISTORICO_MATRICULAS, "w", encoding="utf-8") as f:
            for mat in sorted(atual):
                f.write(mat + "\n")
        print(
            f"\nHistorico de matriculas atualizado (+{len(novas)}): "
            f"{ARQUIVO_HISTORICO_MATRICULAS} ({len(atual)} no total)."
        )
    except OSError as e:
        print(f"ERRO ao gravar historico de matriculas: {e}")


def ler_pag_demissao_rest():
    """Le [APITARGET].pag_demissao (opcional). Padrao: funcionario_demissao."""
    cfg = ler_config()
    if not cfg or "APITARGET" not in cfg:
        return "funcionario_demissao"
    pag = (cfg["APITARGET"].get("pag_demissao") or "").strip().strip('"').strip("'")
    return pag if pag else "funcionario_demissao"


def preparar_csv_para_rest(nome_arquivo_csv=NOME_ARQUIVO_CSV):
    """Garante colunas exigidas pelo REST (chave = cpf; sem coluna matricula)."""
    df = pd.read_csv(nome_arquivo_csv, sep=";", encoding="utf-8-sig", dtype=str)
    df = df.fillna("")

    campo_chave = ler_campo_chave_config()
    if "campo_chave" not in df.columns:
        df.insert(0, "campo_chave", campo_chave)
    else:
        df["campo_chave"] = campo_chave

    if "cpf" not in df.columns:
        df.insert(1, "cpf", "")
    if "nome" not in df.columns:
        df.insert(2, "nome", "")

    if "matricula" in df.columns:
        df = df.drop(columns=["matricula"])

    for coluna in COLUNAS_CSV_DEMISSOES:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df[COLUNAS_CSV_DEMISSOES]
    df.to_csv(nome_arquivo_csv, index=False, encoding="utf-8-sig", sep=";")
    return nome_arquivo_csv


def analisar_resultado_rest_demissoes(resultado):
    """
    Interpreta o JSON da API REST no mesmo espirito dos outros modulos (funcionarios, etc.).
    success=true conta como sucesso do modulo, mesmo com avisos em erros[].
    """
    if resultado.get("success") is False:
        return False

    ok_count = int(resultado.get("ok") or 0)
    ja_cad = int(resultado.get("ja_cad") or 0)
    erros_api = resultado.get("erros") or []
    info = (resultado.get("info") or "").strip()

    if info:
        print(f"Resumo API: {info}")

    if ok_count:
        print(f"{ok_count} registro(s) cadastrado(s) no destino.")
    if ja_cad:
        print(f"{ja_cad} registro(s) ja existiam no destino.")

    if erros_api:
        print(f"AVISO: API reportou {len(erros_api)} mensagem(ns) em erros[] (modulo segue como sucesso).")
        if len(erros_api) <= 5:
            for item in erros_api:
                print(f"   - {item}")

    return True


def enviar_csv_demissoes_rest(nome_arquivo_csv=NOME_ARQUIVO_CSV):
    """Envia demissoes_api.csv via REST (mesmo padrao de funcionarios/afastamentos)."""
    if not os.path.exists(nome_arquivo_csv):
        print(f"Arquivo {nome_arquivo_csv} nao encontrado!")
        return False

    preparar_csv_para_rest(nome_arquivo_csv)
    print(f"Arquivo {nome_arquivo_csv} encontrado e normalizado para REST")

    config_target, token_final = gerar_token_target()
    if not config_target or not token_final:
        print("Falha ao gerar token para API de destino")
        return False

    pag = ler_pag_demissao_rest()
    usuario = config_target["integracao"]
    headers = {"user": usuario, "token": token_final}
    data = {"pag": pag, "cmd": "importar_cad", "separador": ";"}

    try:
        print("Enviando POST de demissoes via REST...")
        print(f"URL: {config_target['url']}")
        print(f"Usuario: {usuario}")
        print(f"pag: {pag}")
        print(f"Token: {token_final[:32]}...")

        with open(nome_arquivo_csv, "rb") as arquivo:
            files = {"arquivo": (nome_arquivo_csv, arquivo, "text/csv")}
            response = requests.post(
                config_target["url"],
                data=data,
                files=files,
                headers=headers,
                timeout=90,
            )

        print(f"Status da resposta: {response.status_code}")

        if response.status_code == 200:
            try:
                resultado = response.json()
                if resultado.get("success") is False:
                    print("API retornou erro:")
                    print(json.dumps(resultado, indent=2, ensure_ascii=False))
                    return False

                print("POST de demissoes realizado com sucesso!")
                print(json.dumps(resultado, indent=2, ensure_ascii=False))
                return analisar_resultado_rest_demissoes(resultado)
            except json.JSONDecodeError:
                print(f"Resposta nao e JSON valido: {response.text[:500]}...")
                return False

        print(f"ERRO no POST - Status: {response.status_code}")
        print(f"Resposta: {response.text[:500]}...")
        return False

    except requests.exceptions.RequestException as e:
        print(f"ERRO na requisicao: {e}")
        return False


def carregar_configuracoes_soap():
    """
    Função para carregar configurações SOAP do arquivo .config
    """
    config = configparser.ConfigParser(interpolation=None)
    config.read('.config')
    
    if not config.has_section('SOAP'):
        print("❌ Seção [SOAP] não encontrada no arquivo .config")
        return None
    
    return {
        'url': config.get('SOAP', 'url'),
        'client_id': config.get('SOAP', 'client_id'),
        'usuario': config.get('SOAP', 'usuario'),
        'senha': config.get('SOAP', 'senha')
    }

def consultar_funcionarios_demitidos():
    """
    Coleta funcionários DEMITIDOS da API Alterdata (endpoint correto encontrado!)
    """
    print("📋 INICIANDO COLETA DE FUNCIONÁRIOS DEMITIDOS...")
    
    # Obter headers do arquivo .config
    headers = obter_headers_api()
    if not headers:
        print("❌ Não foi possível obter o token do arquivo .config")
        return [], None
    
    # Configurações da API - ENDPOINT CORRETO ENCONTRADO!
    base_url = "https://dp.pack.alterdata.com.br/api/v1/funcionarios"
    
    # FILTRO PARA FUNCIONÁRIOS DEMITIDOS (confirmado pelo diagnóstico)
    params_base = {
        "filter[status]": "demitido",
        "fields": "codigo,nome,status,demissao,cpf,identidade,email,telefone",
        "include": "departamento",
        "sort": "codigo",
        "page[limit]": "100"
    }
    print(f"Filtro de empresa ativo: {descrever_filtro_empresa()}")
    depts_ignorar = ler_departamentos_ignorar()
    if depts_ignorar:
        print(f"Departamentos ignorados: {', '.join(depts_ignorar)}")

    todos_demitidos = []
    for empresa_id in empresas_para_consultar():
        params = dict(params_base)
        if empresa_id:
            params["filter[empresa.id]"] = empresa_id
            print(f"  Empresa {empresa_id}...")
        for pagina, _data, demitidos_pagina in get_jsonapi_paginado(
            base_url, headers, params=params, page_limit=100, pausa=0.3
        ):
            if depts_ignorar:
                demitidos_pagina = [
                    f for f in demitidos_pagina
                    if not funcionario_departamento_ignorado(f)
                ]
            print(f"  📄 Coletando página {pagina}... {len(demitidos_pagina)} funcionários demitidos")
            todos_demitidos.extend(demitidos_pagina)

    print(f"\n✅ Total coletado: {len(todos_demitidos)} funcionários demitidos")
    return todos_demitidos, headers

def buscar_funcionario_matricula(funcionario_id, headers):
    """
    Busca a matrícula (código) do funcionário através do ID
    ATUALIZADO: Agora os dados já vêm completos da consulta principal
    """
    # Não precisa mais buscar, os dados já vêm na consulta principal
    return str(funcionario_id).zfill(6)

def formatar_data_brasileira(data_iso):
    """
    Converte data ISO para formato brasileiro DD/MM/AAAA
    """
    if not data_iso:
        return ""
    
    try:
        # Remove timezone e converte
        data_str = data_iso.replace('Z', '').split('T')[0]
        data_obj = datetime.strptime(data_str, '%Y-%m-%d')
        return data_obj.strftime('%d/%m/%Y')
    except:
        return ""

def calcular_datas_demissao(data_demissao_iso):
    """
    Calcula datas estimadas baseadas na data real de demissão da API
    """
    if not data_demissao_iso:
        # Se não tem data, usar data atual como base
        hoje = datetime.now()
        data_demissao = hoje.strftime('%d/%m/%Y')
        data_aviso = (hoje - timedelta(days=30)).strftime('%d/%m/%Y')
        data_ultimo_dia = hoje.strftime('%d/%m/%Y')
        data_acerto = (hoje + timedelta(days=10)).strftime('%d/%m/%Y')
        return data_demissao, data_aviso, data_ultimo_dia, data_acerto
    
    try:
        # Converter data ISO para datetime
        data_obj = datetime.fromisoformat(data_demissao_iso.replace('Z', '+00:00'))
        
        # Usar a data real de demissão
        data_demissao = data_obj.strftime('%d/%m/%Y')
        data_aviso = (data_obj - timedelta(days=30)).strftime('%d/%m/%Y')  # 30 dias antes
        data_ultimo_dia = data_obj.strftime('%d/%m/%Y')  # Mesmo dia da demissão
        data_acerto = (data_obj + timedelta(days=10)).strftime('%d/%m/%Y')  # 10 dias após
        
        return data_demissao, data_aviso, data_ultimo_dia, data_acerto
    except:
        # Fallback se der erro na conversão
        hoje = datetime.now()
        data_demissao = hoje.strftime('%d/%m/%Y')
        data_aviso = (hoje - timedelta(days=30)).strftime('%d/%m/%Y')
        data_ultimo_dia = hoje.strftime('%d/%m/%Y')
        data_acerto = (hoje + timedelta(days=10)).strftime('%d/%m/%Y')
        return data_demissao, data_aviso, data_ultimo_dia, data_acerto

def mapear_demissao_para_csv(funcionario_demitido, headers=None):
    """
    Mapeia funcionario demitido da API para o CSV de demissao (REST ifPonto).
    Chave de integracao no CSV: cpf. Matricula fica so no controle interno/historico.
    """
    attributes = funcionario_demitido.get("attributes", {})
    funcionario_id = funcionario_demitido.get("id", "")

    codigo = attributes.get("codigo", funcionario_id)
    matricula = formatar_matricula_simples(codigo)
    data_demissao_iso = attributes.get("demissao", "")
    campo_chave = ler_campo_chave_config()

    data_demissao, data_aviso, data_ultimo_dia, data_acerto = calcular_datas_demissao(data_demissao_iso)

    demissao_csv = {
        "campo_chave": campo_chave,
        "cpf": formatar_cpf_com_mascara_csv(attributes.get("cpf", "")),
        "matricula": matricula,
        "nome": (attributes.get("nome") or "").strip(),
        "DATA_DEMISSAO": data_demissao,
        "obs": "Demissao",
        "data_aviso": "",
        "data_ultimo_dia_trabalhado": data_ultimo_dia,
        "data_acerto": "",
        "motivo": "Demissao",
        "local_exame": "",
        "opcao_empregado": "",
        "tipo_aviso": "",
        "devolveu_cracha": "Sim",
        "dias_indenizados": 0,
        "data_exame": "",
    }

    return demissao_csv

def filtrar_demissoes_recentes(funcionarios_demitidos, data_limite='2025-01-01'):
    """
    Filtra demissões a partir de uma data específica
    ATUALIZADO: Agora trabalha com funcionários demitidos diretamente
    """
    demissoes_filtradas = []
    data_limite_obj = datetime.strptime(data_limite, '%Y-%m-%d')
    
    for funcionario in funcionarios_demitidos:
        attributes = funcionario.get('attributes', {})
        data_demissao = attributes.get('demissao', '')
        
        if data_demissao:
            try:
                data_demissao_obj = datetime.fromisoformat(data_demissao.replace('Z', '+00:00'))
                data_demissao_sem_tz = data_demissao_obj.replace(tzinfo=None)
                
                if data_demissao_sem_tz >= data_limite_obj:
                    demissoes_filtradas.append(funcionario)
            except:
                # Se der erro na conversão, incluir mesmo assim
                demissoes_filtradas.append(funcionario)
    
    return demissoes_filtradas

# =================== FUNÇÕES SOAP ===================

def construir_xml_demissao(matricula, data_demissao, soap_config):
    """Constrói o XML de demissão no formato SOAP para um único funcionário"""
    soap_xml = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:ifPonto">
    <soapenv:Header/>
    <soapenv:Body>
        <urn:demissao>
            <urn:pack>
                <urn:clientId>{soap_config['client_id']}</urn:clientId>
                <urn:user>{soap_config['usuario']}</urn:user>
                <urn:pass>{soap_config['senha']}</urn:pass>
                <urn:funcionario>
                    <urn:matricula>{matricula}</urn:matricula>
                    <urn:dtdemissao>{data_demissao}</urn:dtdemissao>
                </urn:funcionario>
            </urn:pack>
        </urn:demissao>
    </soapenv:Body>
</soapenv:Envelope>"""
    return soap_xml

def enviar_demissao_soap(xml_data, soap_url):
    """Envia o XML para o webservice SOAP"""
    headers = {'Content-Type': 'text/xml; charset=utf-8'}
    try:
        response = requests.post(
            soap_url,
            data=xml_data,
            headers=headers,
            timeout=10
        )
        return response
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro na comunicação com o webservice SOAP: {str(e)}")
        return None

def salvar_xml_demissao(xml_data, matricula, tipo="request"):
    """Salva o XML de demissão localmente para registro"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"demissao_{tipo}_{matricula}_{timestamp}.xml"
    
    # Criar diretório se não existir
    os.makedirs('logs_demissao', exist_ok=True)
    filepath = os.path.join('logs_demissao', filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(xml_data)
    
    print(f"📄 XML de demissão ({tipo}) salvo em: {filepath}")
    return filepath

def _extrair_resultado_soap(root):
    """Extrai descricao e codigo-retorno do XML de resposta ifPonto."""
    descricao = None
    codigo_retorno = None

    for elem in root.iter():
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'descricao' and elem.text:
            descricao = elem.text.strip()
        elif tag == 'codigo-retorno' and elem.text:
            codigo_retorno = elem.text.strip()

    return descricao, codigo_retorno

def analisar_resposta_soap(resposta_xml):
    """
    Analisa a resposta XML do SOAP.

    Retorna tupla (status, mensagem):
      - 'sucesso'  -> demissão cadastrada agora
      - 'ja_existe' -> já estava no ifPonto (não é falha de integração)
      - 'erro'     -> falha real (funcionário não encontrado, etc.)
    """
    try:
        root = ET.fromstring(resposta_xml)

        namespaces = {
            'soap-env': 'http://schemas.xmlsoap.org/soap/envelope/',
            'SOAP-ENV': 'http://schemas.xmlsoap.org/soap/envelope/',
            'ns1': 'urn:ifPonto'
        }

        soap_fault = (
            root.find('.//soap-env:Fault', namespaces)
            or root.find('.//SOAP-ENV:Fault', namespaces)
            or root.find('.//Fault')
        )
        if soap_fault is not None:
            fault_string = soap_fault.find('faultstring')
            fault_msg = fault_string.text if fault_string is not None else "Erro SOAP desconhecido"
            return 'erro', f"SOAP Fault: {fault_msg}"

        descricao, codigo_retorno = _extrair_resultado_soap(root)

        if descricao:
            descricao_lower = descricao.lower()

            if any(p in descricao_lower for p in ['já cadastrada', 'ja cadastrada', 'já existe', 'ja existe']):
                return 'ja_existe', descricao

            if any(p in descricao_lower for p in [
                'nao encontrado', 'não encontrado', 'nao localizado', 'não localizado',
                'erro', 'falha', 'inválido', 'invalido', 'negado', 'rejeitado'
            ]):
                return 'erro', descricao

            if any(p in descricao_lower for p in [
                'sucesso', 'ok', 'processado', 'realizado', 'concluido', 'concluído',
                'gravado', 'salvo', 'cadastrada com', 'demissão cadastrada', 'demissao cadastrada'
            ]):
                return 'sucesso', descricao

        if codigo_retorno:
            codigo = codigo_retorno.strip()
            if codigo in ('0', '200', '201'):
                return 'sucesso', descricao or f"Código {codigo}"
            if codigo == '303' and descricao:
                return 'ja_existe', descricao

        return 'erro', descricao or "Resposta SOAP sem descrição reconhecida"

    except ET.ParseError as e:
        return 'erro', f"Erro de parse XML: {e}"
    except Exception as e:
        return 'erro', f"Erro na análise: {e}"

def enviar_demissoes_via_soap(demissoes_csv):
    """
    Envia as demissões via SOAP
    """
    print("\n" + "="*60)
    print("📤 ENVIANDO DEMISSÕES VIA SOAP")
    print("="*60)
    
    # Carregar configurações SOAP
    soap_config = carregar_configuracoes_soap()
    if not soap_config:
        print("❌ Falha ao carregar configurações SOAP")
        return False
    
    print(f"🔧 Configurações SOAP:")
    print(f"   URL: {soap_config['url']}")
    print(f"   Client ID: {soap_config['client_id']}")
    print(f"   Usuário: {soap_config['usuario']}")
    
    sucessos = 0
    ja_cadastrados = 0
    erros = 0
    
    print(f"\n📤 Processando {len(demissoes_csv)} demissões via SOAP...")
    print("-" * 50)
    
    for i, demissao in enumerate(demissoes_csv, 1):
        matricula = demissao.get('matricula')
        data_demissao = demissao.get('DATA_DEMISSAO')
        
        if not matricula or not data_demissao:
            print(f"❌ Demissão {i}: Dados incompletos - Matrícula: {matricula}, Data: {data_demissao}")
            erros += 1
            continue
        
        print(f"\n📤 Processando demissão {i}/{len(demissoes_csv)}:")
        print(f"   Matrícula: {matricula}")
        print(f"   Data: {data_demissao}")
        
        # Construir XML de requisição
        xml_demissao = construir_xml_demissao(matricula, data_demissao, soap_config)
        
        # Salvar XML da requisição
        salvar_xml_demissao(xml_demissao, matricula, "request")
        
        # Enviar via SOAP
        resposta = enviar_demissao_soap(xml_demissao, soap_config['url'])
        
        if resposta and resposta.status_code == 200:
            print(f"✅ Requisição enviada (HTTP {resposta.status_code})")
            
            # Salvar XML da resposta
            salvar_xml_demissao(resposta.text, matricula, "response")
            
            status, mensagem = analisar_resposta_soap(resposta.text)
            
            if status == 'sucesso':
                sucessos += 1
                print(f"🎉 Demissão da matrícula {matricula} cadastrada com sucesso!")
                print(f"✅ Mensagem: {mensagem}")
            elif status == 'ja_existe':
                ja_cadastrados += 1
                print(f"ℹ️  Matrícula {matricula} já estava cadastrada no ifPonto")
                print(f"   Mensagem: {mensagem}")
            else:
                erros += 1
                print(f"❌ Erro no processamento da matrícula {matricula}")
                print(f"❌ Mensagem: {mensagem}")
                
        else:
            print(f"❌ Erro ao enviar demissão {i}")
            if resposta:
                print(f"Status HTTP: {resposta.status_code}")
                print(f"Resposta: {resposta.text[:200]}...")
            erros += 1
        
        print("-" * 30)
        time.sleep(1)  # Pausa entre requisições
    
    # Resumo final
    print(f"\n📊 RESUMO DO ENVIO SOAP:")
    print(f"🎉 Novas demissões cadastradas: {sucessos}")
    print(f"ℹ️  Já cadastradas (sem ação): {ja_cadastrados}")
    print(f"❌ Erros: {erros}")
    print(f"📊 Total processadas: {len(demissoes_csv)}")
    
    return erros == 0 or (sucessos + ja_cadastrados) > 0

# =================== FUNÇÃO PRINCIPAL ===================

def gerar_csv_demissoes():
    """
    Função principal para gerar o CSV das demissões
    """
    print("=" * 80)
    print("         📋 GERAÇÃO DE CSV DE DEMISSÕES - API eContador")
    print("=" * 80)
    
    # Verificar se token está disponível
    token = ler_token_config()
    if not token:
        print("❌ Falha ao carregar token do arquivo .config")
        return None
    
    # Coletar funcionários demitidos da API (ENDPOINT CORRETO)
    funcionarios_demitidos, headers = consultar_funcionarios_demitidos()
    
    if not funcionarios_demitidos:
        print("❌ Nenhum funcionário demitido foi coletado da API")
        return None
    
    # Filtrar demissões recentes (desde janeiro de 2025)
    demissoes_filtradas = filtrar_demissoes_recentes(funcionarios_demitidos, '2025-01-01')
    print(f"📅 Demissões filtradas desde 01/01/2025: {len(demissoes_filtradas)}")
    
    if not demissoes_filtradas:
        print("❌ Nenhuma demissão recente encontrada")
        print("💡 Tentando processar todas as demissões disponíveis...")
        demissoes_filtradas = funcionarios_demitidos
    
    print(f"\n🔄 Convertendo {len(demissoes_filtradas)} demissões para formato CSV...")
    print(f"   Chave de integracao no CSV: {ler_campo_chave_config()} (sem coluna matricula)")

    matriculas_ja_exportadas = carregar_matriculas_demissoes_processadas()
    print(
        f"\nHistorico de matriculas ja processadas ({ARQUIVO_HISTORICO_MATRICULAS}): "
        f"{len(matriculas_ja_exportadas)} registro(s)."
    )

    # Converter para formato CSV
    demissoes_csv = []
    matriculas_para_registrar = []
    erros = []
    funcionarios_processados = set()
    ignorados_historico = 0

    for i, funcionario_demitido in enumerate(demissoes_filtradas, 1):
        try:
            demissao_csv = mapear_demissao_para_csv(funcionario_demitido, headers)
            matricula = demissao_csv["matricula"]

            if matricula and matricula in matriculas_ja_exportadas:
                ignorados_historico += 1
                continue

            cpf_ok = formatar_cpf_11_digitos(demissao_csv.get("cpf", ""))
            if cpf_ok or matricula:
                demissoes_csv.append(demissao_csv)
                funcionarios_processados.add(cpf_ok or matricula)
                if matricula:
                    matriculas_para_registrar.append(matricula)

            if i % 10 == 0:
                print(
                    f"  ✅ Processadas {i}/{len(demissoes_filtradas)} demissões... "
                    f"(Novas no CSV: {len(demissoes_csv)})"
                )

        except Exception as e:
            erros.append({"id": funcionario_demitido.get("id", "N/A"), "erro": str(e)})
            print(f"  ❌ Erro ao processar funcionário {funcionario_demitido.get('id', 'N/A')}: {e}")

    print(f"\nFiltro de historico: {ignorados_historico} ignorado(s) (matricula ja exportada).")

    if not demissoes_csv:
        print("ℹ️  Nenhuma demissao nova para exportar (todas ja constam no historico).")
        df_vazio = pd.DataFrame(columns=COLUNAS_CSV_DEMISSOES)
        df_vazio.to_csv(NOME_ARQUIVO_CSV, index=False, encoding="utf-8-sig", sep=";")
        print(f"✅ CSV vazio gerado: {NOME_ARQUIVO_CSV}")
        return []

    # Criar DataFrame
    print(f"\n📊 Criando DataFrame com {len(demissoes_csv)} demissões...")
    print(f"   👥 Funcionários únicos demitidos: {len(funcionarios_processados)}")

    df = pd.DataFrame(demissoes_csv, columns=COLUNAS_CSV_DEMISSOES)

    # Gerar arquivo CSV
    nome_arquivo = NOME_ARQUIVO_CSV
    
    try:
        df.to_csv(nome_arquivo, index=False, encoding='utf-8-sig', sep=';')
        print(f"✅ CSV gerado com sucesso: {nome_arquivo}")
        
        # Estatísticas
        print(f"\n📈 ESTATÍSTICAS:")
        print(f"  📋 Total de demissões: {len(demissoes_csv)}")
        print(f"  👥 Funcionários únicos: {len(funcionarios_processados)}")
        print(f"  ❌ Erros de conversão: {len(erros)}")
        print(f"  📋 Colunas no CSV: {len(df.columns)}")
        print(f"  💾 Arquivo gerado: {nome_arquivo}")
        
        # Aviso sobre datas estimadas
        print(f"\n⚠️  ATENÇÃO:")
        print(f"  📅 As datas foram ESTIMADAS baseadas na data de solicitação")
        print(f"  ✏️  Recomenda-se verificar e ajustar as datas conforme necessário")
        print(f"  📋 Dados baseados apenas nas notificações de rescisão da API")
        
        # Mostrar preview dos dados
        print(f"\n👁️  PREVIEW DOS DADOS (primeiras 3 linhas):")
        print(df.head(3).to_string())
        
        # Salvar relatório de erros se houver
        if erros:
            arquivo_erros = "erros_demissoes.json"
            with open(arquivo_erros, "w", encoding="utf-8") as f:
                json.dump(erros, f, indent=2, ensure_ascii=False)
            print(f"\n⚠️  Relatório de erros salvo em: {arquivo_erros}")

        return demissoes_csv
        
    except Exception as e:
        print(f"❌ Erro ao gerar CSV: {e}")
        return None

def validar_dados_demissoes_csv(nome_arquivo):
    """
    Valida os dados do CSV de demissões gerado
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
        campos_obrigatorios = ['cpf', 'DATA_DEMISSAO']
        
        for campo in campos_obrigatorios:
            if campo in df.columns:
                vazios = df[campo].isna().sum() + (df[campo] == '').sum()
                if vazios > 0:
                    print(f"  ⚠️  Campo '{campo}': {vazios} registros vazios")
                else:
                    print(f"  ✅ Campo '{campo}': todos preenchidos")
            else:
                print(f"  ❌ Campo obrigatório '{campo}' não encontrado")
        
        # Verificar consistência de datas
        campos_data = ['DATA_DEMISSAO', 'data_aviso', 'data_ultimo_dia_trabalhado', 'data_acerto']
        for campo in campos_data:
            if campo in df.columns:
                registros_com_data = (df[campo] != '').sum()
                print(f"  📅 {campo}: {registros_com_data} registros com data")
        
        # Verificar funcionários únicos
        if "cpf" in df.columns:
            funcionarios_unicos = df["cpf"].nunique()
            print(f"  👥 Funcionários únicos demitidos (CPF): {funcionarios_unicos}")

        if "campo_chave" in df.columns:
            chaves = df["campo_chave"].fillna("").astype(str).str.strip().unique()
            print(f"  🔑 campo_chave no CSV: {', '.join(ch for ch in chaves if ch) or 'cpf'}")
        
        print(f"  ✅ Validação concluída")
        
    except Exception as e:
        print(f"  ❌ Erro na validação: {e}")

def processar_apenas_exportacao_csv():
    """Gera demissoes_api.csv sem enviar via REST/SOAP."""
    print("=" * 80)
    print("   EXPORTAR APENAS CSV DE DEMISSOES (sem envio)")
    print("=" * 80)
    demissoes_csv = gerar_csv_demissoes()
    if demissoes_csv is None:
        print("Falha na geracao do CSV.")
        return False
    validar_dados_demissoes_csv(NOME_ARQUIVO_CSV)
    print(f"\nArquivo pronto: {NOME_ARQUIVO_CSV} ({len(demissoes_csv)} linha(s) nova(s))")
    return True


def processar_integracao_soap():
    """Fluxo legado: API -> CSV -> SOAP (um a um)."""
    print("=" * 80)
    print("    INTEGRACAO DE DEMISSOES - eContador -> CSV -> SOAP (legado)")
    print("=" * 80)

    demissoes_csv = gerar_csv_demissoes()
    if demissoes_csv is None:
        print("Falha na geracao dos dados. Processo interrompido.")
        return False

    validar_dados_demissoes_csv(NOME_ARQUIVO_CSV)

    if len(demissoes_csv) == 0:
        print("\nNenhuma demissao nova no CSV; envio SOAP ignorado.")
        return True

    sucesso_soap = enviar_demissoes_via_soap(demissoes_csv)
    if sucesso_soap:
        print("\nIntegracao SOAP finalizada.")
        return True

    print("\nFalha no envio via SOAP.")
    return False


def processar_integracao_completa():
    """
    Fluxo principal: API eContador -> CSV -> REST ifPonto (importar_cad).
    """
    print("=" * 80)
    print("    INTEGRACAO DE DEMISSOES - eContador -> CSV -> REST (ifPonto)")
    print("=" * 80)
    
    # Etapa 1: Gerar CSV das demissões
    print("\n📋 ETAPA 1: Coletando demissões da API eContador...")
    demissoes_csv = gerar_csv_demissoes()
    
    if demissoes_csv is None:
        print("❌ Falha na geração dos dados. Processo interrompido.")
        return False
    
    # Etapa 2: Validar dados do CSV
    print("\n🔍 ETAPA 2: Validando dados...")
    validar_dados_demissoes_csv(NOME_ARQUIVO_CSV)

    if len(demissoes_csv) == 0:
        print("\nℹ️  Nenhuma demissao nova no CSV; envio REST ignorado.")
        print(
            f"   Matriculas ja constam em {ARQUIVO_HISTORICO_MATRICULAS}. "
            "Remova linha(s) do historico para reprocessar."
        )
        return True
    
    # Etapa 3: Enviar via REST
    print("\n📤 ETAPA 3: Enviando CSV de demissões via REST...")
    pag_atual = ler_pag_demissao_rest()
    print(f"   pag (configuravel em [APITARGET] pag_demissao): {pag_atual}")
    sucesso_rest = enviar_csv_demissoes_rest(NOME_ARQUIVO_CSV)
    
    if sucesso_rest:
        registrar_matriculas_demissoes_processadas(
            [d["matricula"] for d in demissoes_csv if d.get("matricula")]
        )
        print("\n🎉 INTEGRAÇÃO COMPLETA FINALIZADA COM SUCESSO!")
        print("✅ Demissões coletadas da API eContador")
        print(f"✅ CSV gerado: {NOME_ARQUIVO_CSV}")
        print(f"✅ Arquivo enviado via REST (pag={pag_atual})")
        return True

    print("\n💥 FALHA NA INTEGRAÇÃO!")
    print(f"✅ CSV gerado: {NOME_ARQUIVO_CSV}")
    print("❌ Falha no envio via REST — confira pag_demissao em [APITARGET]")
    return False

# Exemplo de uso
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        comando = sys.argv[1].lower()

        if comando in ("csv", "somente-csv", "export", "exportar"):
            ok = processar_apenas_exportacao_csv()
            sys.exit(0 if ok else 1)

        if comando in ("enviar", "rest", "upload"):
            nome_arquivo = sys.argv[2] if len(sys.argv) > 2 else NOME_ARQUIVO_CSV
            if not os.path.exists(nome_arquivo):
                print(f"Arquivo {nome_arquivo} nao encontrado!")
                sys.exit(1)
            pag_atual = ler_pag_demissao_rest()
            print(f"Enviando {nome_arquivo} via REST (pag={pag_atual})")
            ok = enviar_csv_demissoes_rest(nome_arquivo)
            if ok:
                df = pd.read_csv(nome_arquivo, sep=";", encoding="utf-8-sig", dtype=str)
                if "matricula" in df.columns:
                    registrar_matriculas_demissoes_processadas(df["matricula"].tolist())
            sys.exit(0 if ok else 1)

        if comando == "soap":
            ok = processar_integracao_soap()
            sys.exit(0 if ok else 1)

        print("Comando invalido. Use: csv | enviar [arquivo.csv] | soap")
        sys.exit(1)

    print("Executando integracao completa de demissoes (REST)...")
    sucesso = processar_integracao_completa()

    if sucesso:
        print("\nIntegracao finalizada com sucesso!")
    else:
        print("\nIntegracao finalizada com erros!")
    sys.exit(0 if sucesso else 1)