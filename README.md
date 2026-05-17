# GLPI Ticket Manager AI 🚀

Este projeto é um motor de classificação automática de chamados de TI para o **GLPI**, desenvolvido em **Python**, utilizando o framework **Functions Framework** e implantado na **Google Cloud Platform (GCP)** utilizando o **Cloud Run** (ou Cloud Functions). 

Ele atua como um webhook que intercepta novos chamados do GLPI, processa a descrição utilizando a API do **Gemini 2.5 Flash** no **Vertex AI**, e atualiza dinamicamente o ticket com a classificação correta de Tipo, Categoria, Grupo Técnico, Impacto, além de adicionar um diagnóstico interno (privado) e uma mensagem de acompanhamento amigável (pública) para o usuário.

---

## 📌 Funcionalidades

- **Autenticação Segura no GCP:** Utiliza `google.auth` com escopo de plataforma em nuvem para chamadas REST nativas e seguras na API do Vertex AI.
- **Integração Robusta com API GLPI:** Manipulação completa de ciclo de vida de sessão (`initSession` e `killSession`), paginação automatizada para leitura de categorias (`POST /search/ITILCategory`) e atualização de tickets (`PUT /Ticket`).
- **Classificação Inteligente por IA:**
  - **Tipo:** Identifica se é um *Incidente* ou uma *Requisição*.
  - **Categoria:** Mapeia dinamicamente contra a árvore real de categorias ativas do GLPI.
  - **Grupo Técnico:** Direciona para a equipe especialista (ex: *Service Desk*, *Infraestrutura*, *Sistemas*, *Cloud & DevOps*).
  - **Impacto:** Define a criticidade baseada no impacto ao negócio (*Baixo*, *Médio*, *Alto*, *Muito Alto*).
- **Abordagem Dynamic Few-Shot (Base de Conhecimento):** Permite o aprendizado contínuo guardando exemplos corrigidos em um arquivo estruturado (`few_shot_examples.json`). Se a IA falhar, novas correções retroalimentam o prompt automaticamente.
- **Interação Dupla (Follow-ups):**
  - **Público:** Mensagem humanizada e personalizada com emojis para o solicitante.
  - **Privado (Técnico):** Diagnóstico detalhado contendo a árvore de decisão da IA para os técnicos.

---

## 🛠️ Tecnologias Utilizadas

- **Linguagem:** Python 3.10+
- **Framework HTTP:** `functions-framework` (Compatível com Cloud Run e Cloud Functions)
- **IA Generativa:** Google Vertex AI API (Modelo: `gemini-2.5-flash`)
- **Orquestração de Nuvem:** Google Cloud Platform (GCP)

---

## 📋 Pré-requisitos e Variáveis de Ambiente

O serviço espera as seguintes variáveis de ambiente configuradas no seu container do Cloud Run ou função:

| Variável | Descrição | Exemplo |
| :--- | :--- | :--- |
| `GLPI_BASE_URL` | URL base da API REST do seu GLPI | `https://suaempresa.glpi-network.cloud/apirest.php` |
| `GLPI_APP_TOKEN` | Token de Aplicativo gerado no GLPI | `abcd1234XYZ...` |
| `GLPI_USER_TOKEN` | Token de usuário com permissão de escrita/atribuição | `user_token_hash...` |
| `GCP_PROJECT` | ID do projeto no Google Cloud Platform | `ticket-manager-ti-ai` |
| `GCP_REGION` | Região onde a API do Vertex AI será consumida | `us-central1` |

---

## 📂 Estrutura de Arquivos Opcional

Para o funcionamento do aprendizado contínuo, garanta que o arquivo de exemplos exista na raiz do projeto (ou será inicializado como vazio):

```json
// few_shot_examples.json
[
    {
        "input": "Descrição: [Falha no cancelamento de boleto]\\nCategorias: ['TECNOLOGIA > SISTEMAS', 'SERVICE DESK']",
        "output": {
            "tipo": "Requisição",
            "categoria": "TECNOLOGIA > SISTEMAS KEDU > OUTROS SISTEMAS",
            "grupo_tecnico": "Service Desk",
            "impacto": "Baixo",
            "diagnostico": "Classificado como Requisição devido à solicitação não apresentar falha sistêmica.",
            "acompanhamento": "Recebemos a sua solicitação! 🕒 Vamos analisar o caso..."
        }
    }
]
