# main.py

import functions_framework
import json
import requests
import os
import copy
import logging

# --- Importação para autenticação segura no GCP (REST API) ---

from google.auth import default
from google.auth.transport.requests import Request as GoogleAuthRequest


#logging.basicConfig(level=logging.)

# Variável global para o caminho do arquivo de exemplos
FEW_SHOT_FILE = "few_shot_examples.json"

# --- Constante de Paginação ---

PAGE_LIMIT = 50

# --- Configurações da API do GLPI (Lidas das Variáveis de Ambiente) ---

GLPI_BASE_URL = os.environ.get("GLPI_BASE_URL")
GLPI_APP_TOKEN = os.environ.get("GLPI_APP_TOKEN")
GLPI_USER_TOKEN = os.environ.get("GLPI_USER_TOKEN")


# --- CONFIGURAÇÃO DO VERTEX AI (REST API) ---

VERTEX_REGION = os.environ.get("GCP_REGION", "us-central1")
VERTEX_PROJECT = os.environ.get("GCP_PROJECT", "SEU_ID_DO_PROJETO")

# Endpoint REST do Gemini 2.5 Flash

GEMINI_API_ENDPOINT = "https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/publishers/google/models/gemini-2.5-flash:generateContent"


# --- CORPO BASE DA REQUISIÇÃO POST PARA FILTRAGEM DE CATEGORIAS ---

CATEGORY_SEARCH_BODY_BASE = {
    "criteria": [
        {
            "link": "OR",
            "itemtype": "ITILCategory",
            "field": "1",
            "searchtype": "contains",
            "value": "TECNOLOGIA"
        },
        {
            "link": "OR",
            "itemtype": "ITILCategory",
            "field": "1",
            "searchtype": "contains",
            "value": "SERVICE DESK"
        }
    ],

    "forcedisplay": [
        1,  # NOME da Categoria (Corresponde a '1' no output)
        2,  # ID da Categoria (Corresponde a '2' no output)
        74,
        75  
    ]
}



def mapear_impacto(impacto_nome: str) -> int:
    """Mapeia o nome do impacto retornado pela IA para o ID numérico do GLPI."""
    impacto_map = {
        "Baixo": 2,
        "Médio": 3,
        "Alto": 4,
        "Muito Alto": 5,
    }
    # Retorna o ID mapeado ou 1 (Baixo) como padrão de segurança
    return impacto_map.get(impacto_nome, 1)

def mapear_tipo(tipo_nome: str) -> int:
    """Mapeia o nome do tipo retornado pela IA para o ID numérico do GLPI."""
    tipo_map = {
        "Incidente": 1,
        "Requisição": 2,
    }
    # Retorna o ID mapeado (se a IA classificar Incidente/Requisição)
    return tipo_map.get(tipo_nome, 1)

# --- FUNÇÃO DE MAPEAR GRUPO TÉCNICO PARA ID (EXEMPLO) ---
def mapear_grupo_para_id(nome_grupo: str) -> int:
    """
    Mapeia o nome do grupo retornado pela IA para o ID interno do GLPI.
    NOTA: ESTE É UM EXEMPLO. Você deve implementar a busca na API ou um dicionário.
    """
    mapping = {
        "kedu - tecnologia > service desk": 126,        
        "kedu - tecnologia > sistemas internos": 152,        
        "kedu - tecnologia > segurança da informação": 120,
        "kedu - tecnologia > automação": 188,
        "kedu - tecnologia > sistemas": 196,
        "kedu - tecnologia > bi": 184,
        "kedu - tecnologia > infraestrutura": 2,
        "kedu - tecnologia > cloud e devOps": 85,
    }
    return mapping.get(nome_grupo, 0) # Retorna 0 (Grupo Padrão) se não encontrar

def iniciar_sessao_glpi():
    """Inicia uma sessão na API do GLPI e retorna o Session-Token."""
    if not all([GLPI_BASE_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN]):
        logging.error("ERRO DE CONFIGURAÇÃO: Variáveis de ambiente da API do GLPI estão faltando.")
        return None
    headers = {
        "Content-Type": "application/json",
        "App-Token": GLPI_APP_TOKEN,
        "Authorization": f"user_token {GLPI_USER_TOKEN}"
    }
    try:
        endpoint = f"{GLPI_BASE_URL}/initSession"
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        session_token = response.json().get('session_token')
        if session_token:
            #logging.info("Sessão GLPI iniciada com sucesso.")
            return session_token
        else:
            logging.error("initSession bem-sucedido, mas 'session_token' não encontrado.")
            return None
    except requests.exceptions.RequestException as err:
        logging.error(f"ERRO de Conexão/HTTP ao iniciar sessão GLPI: {err}")
        if 'response' in locals() and response.text:
            logging.error(f"Resposta da API: {response.text}")
        return None
    except Exception as e:
        logging.error(f"ERRO Inesperado ao iniciar sessão: {e}")
        return None

def encerrar_sessao_glpi(session_token):
    """Encerra a sessão da API para liberar recursos."""
    if not session_token: return
    headers = {
        "Content-Type": "application/json",
        "App-Token": GLPI_APP_TOKEN,
        "Session-Token": session_token
    }
    try:
        endpoint = f"{GLPI_BASE_URL}/killSession"
        requests.get(endpoint, headers=headers, timeout=5)
        #logging.info("Sessão GLPI encerrada.")
    except Exception as e:
        logging.warning(f"Falha ao encerrar sessão GLPI: {e}")
        pass

def obter_categorias_glpi(session_token):
    """
    Obtém a lista COMPLETA de categorias filtradas usando POST /search/ITILCategory
    e retorna um dicionário de mapeamento {Nome: ID}. (AJUSTADA)
    """
    headers = {
        "Content-Type": "application/json",
        "App-Token": GLPI_APP_TOKEN,
        "Session-Token": session_token
    }
    endpoint_base = f"{GLPI_BASE_URL}/search/ITILCategory"
    todas_categorias_data = []
    start = 0
   
    while True:
        search_body = copy.deepcopy(CATEGORY_SEARCH_BODY_BASE)
        end_index = start + PAGE_LIMIT - 1
        search_body["range"] = f"{start}-{end_index}"
        try:
            response = requests.post(endpoint_base, headers=headers, json=search_body)
            response.raise_for_status()
            search_result = response.json()
            categorias_pagina = search_result.get('data', [])
            todas_categorias_data.extend(categorias_pagina)
            count_returned = search_result.get('count', len(categorias_pagina))
            if count_returned < PAGE_LIMIT: break
            start = start + PAGE_LIMIT
        except requests.exceptions.RequestException as err:
            logging.error(f"ERRO na Paginação na Requisição POST: {err}")
            return None
        except Exception as e:
            logging.error(f"ERRO Inesperado durante a paginação: {e}")
            return None

    categoria_id_map = {
        cat.get('1'): cat.get('2')
        for cat in todas_categorias_data if cat.get('1') and cat.get('2')
    }   
    return categoria_id_map

import json
import os
import logging

# Variável global para o caminho do arquivo de exemplos
FEW_SHOT_FILE = "few_shot_examples.json"

def carregar_exemplos_few_shot() -> list:
    """
    Carrega os exemplos de Few-Shot de um arquivo JSON externo.
    Se o arquivo não existir, retorna uma lista vazia.
    """
    if not os.path.exists(FEW_SHOT_FILE):
        logging.warning("Arquivo de exemplos Few-Shot não encontrado. Usando lista vazia.")
        return []
    try:
        with open(FEW_SHOT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"ERRO ao carregar exemplos Few-Shot: {e}")
        return []

def adicionar_exemplo_corrigido(descricao_chamado: str, categorias_viageis: list, classificacao_correta: dict):
    """
    Adiciona um novo exemplo (correção) à base de conhecimento para aprendizado futuro.
    """
    # 1. Cria o novo objeto de exemplo no formato 'input'/'output'
    novo_exemplo = {
        "input": f"Descrição: [{descricao_chamado}]\nCategorias: {categorias_viageis}",
        "output": classificacao_correta
    }
    
    # 2. Carrega todos os exemplos existentes
    exemplos_existentes = carregar_exemplos_few_shot()
    
    # 3. Adiciona o novo exemplo
    exemplos_existentes.append(novo_exemplo)
    
    # 4. Salva a lista atualizada de volta no arquivo
    try:
        with open(FEW_SHOT_FILE, 'w', encoding='utf-8') as f:
            json.dump(exemplos_existentes, f, indent=4, ensure_ascii=False)
        logging.info(f"Novo exemplo adicionado ao Few-Shot file para aprendizado: {descricao_chamado}")
    except Exception as e:
        logging.error(f"ERRO ao salvar novo exemplo Few-Shot: {e}")

# Exemplo de como você usaria 'adicionar_exemplo_corrigido'
# Se a IA classificar errado, você pega a classificação correta do usuário/analista:
# classificacao_correta = { "tipo": "...", "categoria": "...", ... }
# adicionar_exemplo_corrigido("Descrição do chamado que a IA errou", categorias, classificacao_correta)

def categorizar_chamado_com_ia(descricao: str, categorias: list) -> dict:
    """
    Chama o modelo Gemini (via API REST) para categorizar o chamado.
    Unifica o Few-Shot e System Instruction em um único Prompt (para evitar erro 400).
    """
    global VERTEX_PROJECT, VERTEX_REGION, GEMINI_API_ENDPOINT
    if not all([VERTEX_PROJECT, VERTEX_REGION]):
        logging.error("ERRO DE CONFIGURAÇÃO: Variáveis GCP_PROJECT ou GCP_REGION estão faltando.")
        return None
    try:
        credentials, project = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(GoogleAuthRequest())
        access_token = credentials.token
        #logging.info("Token de acesso GCP obtido com sucesso.")
    except Exception as e:
        logging.error(f"ERRO DE AUTENTICAÇÃO GCP: Falha ao obter token de acesso: {e}")
        return None

    # 1. CARREGA OS EXEMPLOS DINAMICAMENTE
    few_shot_examples = carregar_exemplos_few_shot()
    
    # 2. GERA O BLOCO DE EXEMPLOS PARA O PROMPT
    few_shot_block = ""
    for i, example in enumerate(few_shot_examples):
        # Gera o bloco de treinamento com base na Base de Conhecimento
        ex_input = example["input"]
        ex_output = example["output"]
        few_shot_block += f"""
        [EXEMPLO {i+1} - INPUT]: {ex_input}
        [EXEMPLO {i+1} - OUTPUT JSON]: {json.dumps(ex_output, ensure_ascii=False)} 
        """
    SYSTEM_INSTRUCTION_TEXT = """
Papel
Você é um Ticket Manager de TI e sua responsabilidade é fazer a classificação dos chamados gerados pelos colaboradores da Kedu para a equipe de TI. Sua missão é analisar a descrição do chamado e, com base nas regras abaixo, classificar o ticket de forma precisa e objetiva.
1. TIPO: Determine se o chamado é um `Incidente` ou uma `Requisição`.
- Incidente: Interrupção inesperada ou degradação de um serviço.
- Requisição: Pedido de recurso, alteração ou informação que não é uma falha.
2. CATEGORIA: Classifique o chamado em uma das categorias da lista fornecida. Use a categoria mais específica possível.
3. GRUPO TÉCNICO: Atribua o chamado ao grupo técnico mais adequado.
- tecnologia > service desk, tecnologia > sistemas internos, tecnologia > segurança da informação, tecnologia > automação, tecnologia > sistemas, tecnologia > dados e bi, tecnologia > infraestrutura, tecnologia > cloud e devOps.
4. IMPACTO: Defina o impacto commo:
 - Muito Alto: indisponibilidade total de serviços do sistema A, Sistema B, Sistema C, DW ou grande prejuízo financeiro que pode inviabilizar o negócio, 
 - Alto: indisponibilidade parcial, falhas de funcionalidades criticas como geração de boletos ou impossibilidade de realizar matricula, extrema lentidão na conexão. 
 - Médio: para chamados de casos pontuais que afetem 1 escola ou um responsavel financeiro, falha de permissão, erro ao realizar uma atividade específica, falhas que afetam apenas 1 usuario ou equipamento ou uma parte do grupo     
 - Baixo: incidentes que podem ser contingenciados, que afetam uma funcionalidade não crítica como formatação do contrato, ou que não são relacionados a boletos ou matriculas
5. DIAGNOSTICO: Forneça uma análise detalhada e a justificativa para a classificação e proponha uma nova categoria para o chamado caso não localize uma categoria adequada ou que seja muito genérioca.
6. ACOMPANHAMENTO: Gere um comentário personalizado, use emojis, mostre que a solicitação foi entendida, que estamos cientes dos prazos e que faremos o possivel para atende-lo de forma ágil e acertiva. Pode ser um pouco criativo.
Formato de Saída
Sua resposta deve ser um único objeto JSON válido, sem nenhum texto, comentários ou formatação adicional.
"""
    msg1_user = f"Descrição: [Falha no cancelamento de boleto em KeduCore]]\nCategorias: {categorias}"
    msg1_model = {
        "tipo": "Requisição",
        "categoria": "TECNOLOGIA > SISTEMAS KEDU > OUTROS SISTEMAS > GOOGLE WORKSPACE",
        "grupo_tecnico": "Service Desk",
        "impacto": "Baixo",
        "diagnostico": "Classificado como Requisição e baixo devido à solicitação não apresentar falha sistemica nem impedir a realização do trabalho de nenhuma área.",
        "acompanhamento": "Recebemos a sua solicitação. Vamos analisar e retornar com a solução o mais rápido possível./n🕒 Por favor acompanhe o SLA na sessão nível de serviço, ao lado 👉\nCaso tenha alguma dúvida ou precise de informação adicional, estamos à disposição! 😊\n📌 Por favor, acompanhe as próximas interações no chamado para atualizações.\nObrigado pelo contato! 🎯"
    }
    # CRIA O PROMPT UNIFICADO COM O BLOCO DINÂMICO DE EXEMPLOS
    unified_prompt = f"""
    ### INSTRUÇÃO DE SISTEMA (PAPEIS E REGRAS) ###
    {SYSTEM_INSTRUCTION_TEXT}
    ### EXEMPLOS DE TREINAMENTO (FEW-SHOT) ###
    {few_shot_block}
    ### CHAMADO PARA ANÁLISE ###
    [CHAMADO ATUAL - INPUT]:
    Descrição do chamado: [{descricao}]\n\nCategorias viáveis: {categorias}
    [CHAMADO ATUAL - OUTPUT JSON]:
    """
     # 3. CORPO DA REQUISIÇÃO REST
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": unified_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string"},
                    "categoria": {"type": "string"},
                    "grupo_tecnico": {"type": "string"},
                    "impacto": {"type": "string"},
                    "diagnostico": {"type": "string"},
                    "acompanhamento": {"type": "string"}
                },
                "required": ["tipo", "categoria", "grupo_tecnico", "impacto", "diagnostico", "acompanhamento"]
            }
        },
    }

    # 4. CONSTRÓI O ENDPOINT FINAL
    endpoint = GEMINI_API_ENDPOINT.format(project=VERTEX_PROJECT, region=VERTEX_REGION)

    # 5. EXECUTA A CHAMADA COM O TOKEN
    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=request_body
        )
        response.raise_for_status()
        api_response = response.json()
        response_text = api_response["candidates"][0]["content"]["parts"][0]["text"]
        # Remove formatação Markdown de código se presente
        if response_text.strip().startswith('```json'):
            response_text = response_text.strip()[7:-3].strip()
        sugestao_json = json.loads(response_text)
        #logging.info(f"Sugestão de IA recebida: Diagnóstico={sugestao_json.get('diagnostico')},Acompanhamento={sugestao_json.get('acompanhamento')}")
        return sugestao_json
    except requests.exceptions.RequestException as e:
        logging.error(f"ERRO de Conexão/HTTP à API REST do Gemini: {e}")
        if 'response' in locals() and response.text:
            logging.error(f"Resposta da API: {response.text}")
        return None
    except Exception as e:
        logging.error(f"ERRO ao processar a resposta da IA: {e}")
        return None

def atualizar_chamado_glpi(chamado_id: str, session_token: str, sugestao_ia: dict, categoria_id_map: dict):
    """
    Atualiza o chamado no GLPI com a categoria, grupo e adiciona o diagnóstico da IA como um follow-up.
    Agora usa os IDs numéricos mapeados.
    """
    headers = {
        "Content-Type": "application/json",
        "App-Token": GLPI_APP_TOKEN,
        "Session-Token": session_token
    }
    # 1. Mapeamento dos valores da IA para IDs numéricos do GLPI
    nome_categoria = sugestao_ia.get('categoria', '')
    nome_grupo = sugestao_ia.get('grupo_tecnico', '')
    nome_impacto = sugestao_ia.get('impacto', '')
    nome_tipo = sugestao_ia.get('tipo', 'Incidente') # Padrão para 1
    diagnostico = sugestao_ia.get('diagnostico', 'Diagnóstico não fornecido pela IA.')
    acompanhamento_msg = sugestao_ia.get('acompanhamento', 'Iniciamos o atendimento da sua solicitação. Vamos analisar o caso e retornar com mais informações o mais rápido possível.') # Mensagem pública
    itilcategories_id = categoria_id_map.get(nome_categoria, 0)
    groups_id = mapear_grupo_para_id(nome_grupo)
    impact_id = mapear_impacto(nome_impacto)
    type_id = mapear_tipo(nome_tipo)

    # 2. Preparar os dados para atualização do ticket (PUT /Ticket)
    ticket_payload = {
        "input": {
            "id": chamado_id,
            "itilcategories_id": itilcategories_id,
            "impact": impact_id, # Novo campo
            "type": type_id, # Novo campo
            "status": 2, # 'Em Atribuição' (ajuste conforme seu fluxo)
        }
    }

    # 3. Faz a atualização principal do Ticket (PUT)
    endpoint_ticket = f"{GLPI_BASE_URL}/Ticket/{chamado_id}"
    try:
        response = requests.put(endpoint_ticket, headers=headers, json=ticket_payload)
        response.raise_for_status()
        #logging.info(f"Chamado {chamado_id} atualizado com sucesso. Categoria ID: {itilcategories_id}, Grupo ID: {groups_id}.")
    except requests.exceptions.RequestException as e:
        logging.error(f"ERRO ao atualizar chamado {chamado_id} (PUT): {e}. Resposta: {response.text}")
        return False

    # 4. ATRIBUIÇÃO DO GRUPO TÉCNICO (POST /Group_Ticket)
    if groups_id > 0:
        group_payload = {
            "input": {
                "tickets_id": chamado_id,
                "groups_id": groups_id,
                "type": 2, # '2' é o tipo de ator para Atribuído (Assign)
                "use_notification": 1 # Notificar o grupo
            }
        }
        endpoint_group = f"{GLPI_BASE_URL}/Ticket/{chamado_id}/Group_Ticket"
        try:
            response = requests.post(endpoint_group, headers=headers, json=group_payload)
            response.raise_for_status()
            #logging.info(f"Grupo ID {groups_id} atribuído ao chamado {chamado_id} com sucesso via POST.")
        except requests.exceptions.RequestException as e:
            # Se a atribuição do grupo falhar, logamos mas podemos continuar o processo (retorna True)
            logging.error(f"AVISO: Falha ao atribuir grupo {groups_id} (POST Group_Ticket): {e}. Resposta: {response.text}")
    else:
        return ('O grupo técnico não foi mapeado (ID=0) e não será atribuído.', 200)
    # 5. Follow-up 1 (PÚBLICO) - Mensagem de acompanhamento para o requerente
    followup_publico = {
        "input": {
            "itemtype": "Ticket",
            "items_id": chamado_id,
            "content": acompanhamento_msg,
            "is_private": 0 # Público
        }
    }
    endpoint_followup = f"{GLPI_BASE_URL}/ITILFollowup"
    try:
        response = requests.post(endpoint_followup, headers=headers, json=followup_publico)
        response.raise_for_status()
        #logging.info("Follow-up público (Acompanhamento) adicionado com sucesso.")
    except requests.exceptions.RequestException as e:
        logging.error(f"ERRO ao adicionar Follow-up público (POST): {e}")
        # Falhar o follow-up público não deve falhar o processo inteiro.
        pass 

    # 6. Adicionar o Diagnóstico da IA como um Follow-up (POST /ITILFollowup)
    followup_payload = {
        "input": {
            "itemtype": "Ticket",
            "items_id": chamado_id,
            "content": f"Classificação Automática por IA (Gemini)\n\nTipo: {nome_tipo} ({type_id})\nCategoria: {nome_categoria} ({itilcategories_id})\nGrupo Atribuído: {nome_grupo} ({groups_id})\nImpacto: {nome_impacto} ({impact_id})\n\nDiagnóstico da IA: {diagnostico}\n\n---",
            "is_private": 1        
        }
    }

    endpoint_followup = f"{GLPI_BASE_URL}/ITILFollowup"
    try:
        response = requests.post(endpoint_followup, headers=headers, json=followup_payload)
        response.raise_for_status()
        #logging.info(f"Follow-up de diagnóstico da IA adicionado ao chamado {chamado_id} com sucesso.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"ERRO ao adicionar Follow-up ao chamado {chamado_id} (POST): {e}. Resposta: {response.text}")
        return False

# FUNÇÃO PRINCIPAL (@functions_framework.http)

@functions_framework.http
def processar_webhook_glpi(request):
    """
    Função principal acionada pelo webhook. Lógica de processamento e IA.
    """
    session_token = None
    # 0. Leitura do projeto (necessário para o endpoint da IA)
    global VERTEX_PROJECT, VERTEX_REGION
    VERTEX_PROJECT = os.environ.get("GCP_PROJECT", "ticket-manager-ti-ai")
    VERTEX_REGION = os.environ.get("GCP_REGION", "us-central1")
    try:
        # [CÓDIGO DE PROCESSAMENTO DO WEBHOOK]
        if request.method != 'POST': return ('Apenas requisições POST são aceites.', 405)
        payload = None
        try:
            json_text = request.data.decode('utf-8')
            payload = json.loads(json_text)
            if payload is None: return ('Corpo da requisição vazio.', 400)
        except json.JSONDecodeError as e:
            logging.error(f"ERRO: JSON do webhook inválido. Erro: {e}")
            return ('O corpo da requisição não é um JSON válido. Verifique o template do GLPI.', 400)
        except Exception as e:
            logging.error(f"ERRO ao processar o corpo do webhook: {e}")
            return (f'Erro interno ao processar requisição: {e}', 500)
        chamado_id = payload.get('chamado_id', 'Não Informado')
        descricao = payload.get('descricao', 'Sem Descrição')
        grupo_tecnico = payload.get('grupo_tecnico','Inválido')
        groups_id = mapear_grupo_para_id(grupo_tecnico.lower().strip())
        logging.info(f'----------> {chamado_id}-{grupo_tecnico}')
        if groups_id == 0:
            return (f"IA não autorizada a classificar chamados do grupo {grupo_tecnico}.", 200)
        # 1. INICIAR SESSÃO GLPI
        session_token = iniciar_sessao_glpi()
        if not session_token:
            return (f'Webhook Chamado ID {chamado_id} recebido, mas falha na autenticação GLPI. Verifique tokens.', 200)
        # 2. OBTER CATEGORIAS FILTRADAS
        categoria_id_map = obter_categorias_glpi(session_token)
        if categoria_id_map is None or not categoria_id_map:
            #logging.warning("Não há categorias válidas para a análise da IA.")
            return (f'Webhook Chamado ID {chamado_id} recebido, mas falha ao obter categorias filtradas da API.', 200)
        # 3. INTEGRAÇÃO DA IA GENERATIVA (CHAMADA REST SEGURA)
        lista_categorias_nomes = list(categoria_id_map.keys())
        #logging.info("--- INICIANDO ANÁLISE DE IA GENERATIVA ---")
        sugestao_ia = categorizar_chamado_com_ia(descricao, lista_categorias_nomes)
        if sugestao_ia:
            categoria_final = sugestao_ia.get('categoria', 'Não Sugerida')
            grupo_tecnico = sugestao_ia.get('grupo_tecnico', 'Não Sugerido')
            if atualizar_chamado_glpi(chamado_id, session_token, sugestao_ia, categoria_id_map):
                 return (f'Chamado {chamado_id} processado e atualizado no GLPI com sucesso! Categoria: {categoria_final}', 200)
            else:
                 return (f'Chamado {chamado_id} processado, mas falhou ao atualizar o GLPI.', 200)
        else:
            return (f'Webhook Chamado ID {chamado_id} processado, mas falha na categorização por IA.', 200)
    finally:
        # 4. GARANTIR ENCERRAMENTO DA SESSÃO
        encerrar_sessao_glpi(session_token)
