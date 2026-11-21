# OmniRoute para Hermes — integração da comunidade

**Versão candidata:** `0.4.0-beta.1`. Este projeto ainda não foi submetido nem aceito pelo Marketplace oficial do Hermes.

[English README](README.md) · [Guia detalhado da interface Desktop](docs/DESKTOP.md)

Integração independente que conecta o [Hermes Agent](https://github.com/NousResearch/hermes-agent) a uma instância [OmniRoute](https://github.com/cheaper-inference/OmniRoute) configurada pelo usuário, por meio de uma API compatível com OpenAI.

> Projeto não afiliado nem endossado por Hermes, Nous Research ou OmniRoute. A implementação é original.

## Funcionalidades

| Função | Componente | Endpoint | Observações |
| --- | --- | --- | --- |
| Chat com LLM, ferramentas, streaming e modelos com visão | `model-provider/` | `POST /chat/completions` | Transporte nativo do Hermes; utiliza `model.provider=omniroute` |
| Descoberta dinâmica de modelos de chat | `model-provider/` | `GET /models?kind=chat&prefix=alias` | Exclui modelos tipados de mídia/embeddings; não inventa IDs |
| Geração de imagens | `backend/` | `POST /images/generations` | Só informa tamanho se houver dimensões compatíveis |
| Edição de imagens e referências | `backend/` | `POST /images/edits` | Limites de referências dependentes do modelo; download seguro pelo Hermes |
| Geração de vídeos | `backend/` | `GET/POST /videos/generations` | Catálogo especializado e metadados por modelo |
| Pesquisa na web | `backend/` | `POST /search` | Provedor de pesquisa opcional ou seleção pelo OmniRoute |
| Extração de páginas | `backend/` | `POST /web/fetch` | Falhas tratadas individualmente por URL |
| Síntese de fala (TTS) | `backend/` | `POST /audio/speech` | MP3/Opus; modelos do catálogo de áudio |
| Transcrição de fala (STT) | `backend/` | `POST /audio/transcriptions` | Envio multipart |
| Dashboard administrativo | `backend/` | API de extensões do Hermes | Configurações privadas, busca e seleção de modelos |
| Interface Desktop/Webapp | `backend/desktop/plugin.js` | API do plugin via `ctx.rest` | Página própria de configurações, quando suportada pelo host |

Todos os caminhos são relativos à URL-base da API **definida pelo usuário**, por exemplo `https://router.example/api/v1` ou `http://127.0.0.1:3000/api/v1`. O código não inclui endereços, senhas ou chaves específicos de um HomeLab.

## Arquitetura: dois pacotes e três partes funcionais

O Hermes descobre `kind: model-provider` pelo registro de provedores. Já o `kind: backend` usa o ciclo de registro de ferramentas, mídia e serviços. Para não modificar o núcleo do Hermes, distribuímos **dois pacotes instaláveis**:

- **`omniroute-model`** — diretório `model-provider/`, provedor nativo de modelos de chat.
- **`omniroute-media`** — diretório `backend/`, funcionalidades de mídia, pesquisa, voz e API do Dashboard. Sua pasta `desktop/` contém a **terceira parte funcional**, a interface Desktop/Webapp.

A instalação de um pacote **não instala o outro automaticamente**. O Marketplace oficial poderá exibi-los separadamente, caso sejam submetidos e aprovados.

## Instalação pela interface do Hermes Desktop — recomendada

Você pode instalar **diretamente do GitHub, sem clonar o repositório e sem usar terminal**.

1. Abra o **Hermes Desktop**.
2. Vá à página **Capabilities (Capacidades)** e selecione **Plugins**.
3. Clique em **Install from Git** (ou **Instalar a partir do Git**, conforme o idioma da interface).
4. Cole a URL do **primeiro pacote**, conclua a instalação e verifique o resultado:

   ```text
   https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#model-provider
   ```

5. Repita **Install from Git** com o **segundo pacote**:

   ```text
   https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#backend
   ```

6. Em **Capabilities → Plugins**, confira os componentes `omniroute-model` e `omniroute-media`, habilitando-os quando necessário.
7. Para a interface gráfica, abra **Settings → Plugins → OmniRoute**. Caso não apareça, verifique se a parte Desktop foi detectada e habilitada; use a opção de nova varredura (Rescan), quando disponível.

**Atenção ao local da instalação:** no Hermes Desktop nativo, a interface JavaScript deve estar instalada na máquina que executa o aplicativo. No **Hermes Webapp hospedado no servidor**, os plugins de interface são carregados no host que serve o Webapp. Instalar o backend remoto não garante, por si só, que a interface apareça em um aplicativo Desktop de outra máquina.

A origem do Git é a branch padrão `main`, atualmente com a v0.4.0-beta.1. Caso precise de reprodução exata, fixe uma referência/commit suportado pela sua versão do Hermes. Revise a fonte antes de autorizar código de terceiros.

## Instalação pelo terminal (alternativa)

Compatibilidade mínima declarada: **Hermes v0.23.2**. A compatibilidade efetiva depende de validação na versão instalada e no ambiente.

Para instalar diretamente pelo gerenciador do Hermes:

```bash
hermes plugins install \
  "https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#model-provider" \
  --enable

hermes plugins install \
  "https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git#backend" \
  --enable

hermes plugins list
```

Como alternativa para desenvolvedores, clone o repositório e execute o instalador, que utiliza o commit do checkout para fixar a instalação:

```bash
git clone https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git
cd Hermes-OmniRoute-Integration
python3 scripts/install_local.py
```

Esse instalador valida os manifests e busca ambos os componentes no GitHub. Ele exige um checkout Git, não um ZIP sem metadados `.git`. Não instala automaticamente o JavaScript Desktop no Windows.

## Configurar a conexão

No Dashboard autenticado do Hermes, abra a aba **OmniRoute**. Também é possível usar **Settings → Plugins → OmniRoute** no Desktop/Webapp, caso a interface esteja habilitada e sua API disponível.

Defina os parâmetros:

- `OMNIROUTE_BASE_URL` — URL completa da API, terminada em `/v1` ou `/api/v1`.
- `OMNIROUTE_API_KEY` — chave de inferência autorizada no OmniRoute.

Os segredos devem ser gerenciados pelos mecanismos de credenciais do Hermes, e não adicionados ao histórico do shell ou ao repositório Git.

Para usar o OmniRoute especificamente como provedor de chat, selecione um modelo e acione **Activate OmniRoute as Hermes chat provider** na interface, quando disponível. A escolha de um modelo isoladamente **não** muda o provedor ativo. Alternativamente, ajuste a configuração nativa:

```bash
hermes config set model.provider omniroute
hermes config set model.base_url https://router.example/api/v1
hermes config set model.default your-model-id
```

Um reload/reinício do processo Hermes pode ser necessário após mudanças de configuração.

Exemplo de seleção das outras capacidades em `~/.hermes/config.yaml` (configure somente o que a sua instância OmniRoute suporta):

```yaml
image_gen:
  provider: omniroute
video_gen:
  provider: omniroute
web:
  search_backend: omniroute
  extract_backend: omniroute
tts:
  provider: omniroute
stt:
  provider: omniroute
```

Outras variáveis opcionais disponíveis no painel: `OMNIROUTE_CHAT_MODEL`, `OMNIROUTE_IMAGE_MODEL`, `OMNIROUTE_VIDEO_MODEL`, `OMNIROUTE_TTS_MODEL`, `OMNIROUTE_STT_MODEL`, `OMNIROUTE_TTS_VOICE`, `OMNIROUTE_SEARCH_PROVIDER` e `OMNIROUTE_FETCH_PROVIDER`. Nenhum ID de modelo fictício é definido como fallback. O preset de chat só sincroniza com a seleção nativa quando o OmniRoute já está ativo.

## Interface Desktop/Webapp da v0.4

O arquivo `backend/desktop/plugin.js` registra uma página de configuração do `omniroute-media`. Ela usa `ctx.rest` para conversar com a API do plugin hospedada no Hermes: não acessa o OmniRoute diretamente do navegador e não cria um segundo depósito de credenciais. Permite configurar URL e chave mascarada, descobrir e selecionar modelos de chat, imagem, vídeo, TTS e STT, ajustar voz TTS, opções de pesquisa/extração e ativar explicitamente o provedor de chat.

Guia de instalação, diagnóstico, segurança e reversão: [docs/DESKTOP.md](docs/DESKTOP.md).

## Compatibilidade com OmniRoute 3.8.53

A implementação `0.4.0-beta.1` foi alinhada aos contratos do OmniRoute **3.8.53**:

- Chat usa `GET /v1/models?kind=chat&prefix=alias` e exclui entradas tipadas de imagem, vídeo, áudio e embeddings do seletor LLM.
- Áudio usa `type: audio` com `subtype: speech` para TTS ou `subtype: transcription` para STT.
- Imagens não recebem `size` arbitrário; dimensões explícitas em pixels são aceitas quando compatíveis.
- Edição envia imagens como data URLs base64 em JSON e verifica limites conhecidos de referências por modelo.
- Para vídeo a partir de imagem, o xAI usa o campo `image`; outras rotas usam `image_url`. Duração e outros atributos dependem dos metadados do modelo.
- Rejeições por permissões da API continuam sob responsabilidade do OmniRoute. O cliente preserva códigos HTTP e erros tipados seguros sem divulgar segredos.

Essas verificações decorrem de contratos de código-fonte e testes offline; **não garantem interoperabilidade ao vivo** com todos os modelos e provedores.

## Limitações e requisitos

A disponibilidade de cada operação depende da versão e dos provedores configurados no OmniRoute. Streaming, chamadas de ferramentas e visão são delegados ao transporte de chat nativo compatível com OpenAI do Hermes; o modelo de destino também precisa suportar a modalidade solicitada.

O OmniRoute 3.8.53 dispõe de `GET /v1/videos/generations` para descoberta de vídeo. Versões anteriores ou instalações sem provedores podem retornar catálogos vazios; alguns caminhos permitem informar um ID explícito. Teste primeiro com requisições pequenas.

O Dashboard usa a extensão autenticada e os mecanismos do Hermes para credenciais por perfil. Para TTS, configure a voz apropriada ao modelo; nem todos os provedores reconhecem as vozes padrão da OpenAI. HTTP sem TLS é permitido somente para endereços locais/privados e alguns nomes internos; **HTTPS é obrigatório para endpoints públicos**. Mesmo dentro da rede local, HTTP não fornece confidencialidade do transporte.

## Segurança e privacidade

- As chamadas externas vão para a URL-base OmniRoute escolhida pelo operador. Uma URL de terceiro poderá receber conteúdo; utilize apenas destinos confiáveis.
- Prompts, textos para síntese, gravações, URLs, imagens e demais entradas enviadas à API poderão ser encaminhados a provedores upstream pelo próprio OmniRoute.
- A geração de vídeo por referência aceita URLs HTTPS públicas sem credenciais embutidas, sujeitas à política do servidor. A edição de imagem pode ler arquivos escolhidos explicitamente (até 20 MiB) ou usar downloads seguros do Hermes. STT pode ler arquivos de áudio explicitamente escolhidos (até 25 MiB). Não há indexação geral do sistema de arquivos.
- Arquivos gerados podem ser armazenados no cache de mídia normal do Hermes; saídas TTS são gravadas no caminho solicitado.
- A chave é gravada pelas APIs de credenciais do Hermes e **não é devolvida à interface**.
- Redirecionamentos HTTP de chamadas com bearer token são recusados, para evitar encaminhar a chave a outro host; URLs com usuário/senha embutidos são rejeitadas.
- O instalador de desenvolvimento executa `hermes plugins install` duas vezes, mediante ação explícita. Os plugins instalados não oferecem atualizador próprio nem executam comandos de shell.
- Não há telemetria, analytics, scraping do navegador ou bypass automático de autorizações.

## Desenvolvimento, testes e publicação

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q backend model-provider
node --check backend/dashboard/dist/index.js
hermes plugins validate ./model-provider --install-deps
hermes plugins validate ./backend --install-deps
```

Os três primeiros testes podem ser executados offline. Os dois comandos `hermes plugins validate` exigem uma instalação compatível do Hermes. A integração ponta a ponta exige credenciais válidas e modelos disponíveis no OmniRoute; a versão ainda não está homologada no Marketplace oficial.

Para publicação no catálogo oficial, os dois manifests devem ser apresentados seguindo as regras de revisão e referência Git exata (SHA de 40 caracteres). Consulte as [regras oficiais de submissão](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/plugins/catalog-submission.md).

## Licença e créditos

Licença MIT. Implementação original baseada em contratos públicos de API e pontos de extensão oficiais do Hermes. 
