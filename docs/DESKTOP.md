# OmniRoute no Hermes Desktop — 0.4.0-beta.1

**Estado:** interface Desktop implementada e testada em mocks; **não instalada nem homologada no Windows/CT221 de produção**.

## Por que a aba não apareceu no seu Desktop?

O `omniroute-model` e o `omniroute-media` executam no Hermes Agent remoto, no CT221. O dashboard web recebe os arquivos da pasta `backend/dashboard/`. Já o **Hermes Desktop executa plugins JS no computador onde o aplicativo está instalado**, não dentro do CT221. A versão 0.3.2 não possuía `desktop/plugin.js`. Não houve instalação incompleta do agente.

## O que a v0.4 acrescenta

A pasta `backend/desktop/plugin.js` registra uma **página de configurações** na seção Settings → Plugins do Hermes Desktop, usando o id `omniroute-media`, o mesmo id do plugin Python remoto.

O código **não** liga diretamente ao OmniRoute do CT222. Ele chama exclusivamente `ctx.rest('/status' | '/connection' | '/models?kind=…' | '/model' | '/preference' | '/activate-chat')`, que o Hermes direciona à API autenticada e vinculada ao perfil ativo em `/api/plugins/omniroute-media`. O token de inferência fica no armazenamento seguro do Hermes no CT221; não é retornado por `/status` e não é gravado no Desktop.

| Área da interface | Endpoint do backend |
| --- | --- |
| Estado, URL, modelos e presença de chave | `GET /status` |
| Salvar URL e substituição da chave | `POST /connection` |
| Descobrir modelos | `GET /models?kind=chat/image/video/tts/stt` |
| Salvar modelo selecionado | `POST /model` |
| Salvar voz TTS e outros overrides | `POST /preference` |
| Ativar OmniRoute para chat **sob ação explícita** | `POST /activate-chat` |

A página é opcional; não altera o comportamento de streaming, chat, áudio, imagem, vídeo ou o fluxo JIT.

## Instalação no HomeLab com o Desktop rodando no Windows

1. **Não reinstale o Python que já funciona no CT221.** Preserve os dois plugins do agente e o dashboard web atuais.
2. Baixe o ZIP `omniroute-hermes-marketplace-v0.4.0-beta.1.zip` no **notebook que executa Hermes Desktop**. Confirme o SHA-256 publicado com o arquivo.
3. Extraia o ZIP em uma pasta local no notebook.
4. Execute o PowerShell **no notebook**, a partir da raiz extraída, por exemplo:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_desktop_local.ps1
   ```

   O instalador local copia **somente** o JS para `%USERPROFILE%\.hermes\desktop-plugins\omniroute-media\plugin.js` (ou `$env:HERMES_HOME`), faz backup de um arquivo anterior e grava TXT em `C:\Users\lucas\OneDrive\Área de Trabalho\Registros` quando disponível. Não modifica o CT221 e não solicita credenciais.

5. Abra o Hermes Desktop e selecione a conexão com o Hermes remoto **CT221**.
6. Em **Capabilities → Plugins**, use **Rescan** e habilite `OmniRoute`/`omniroute-media`, que vem desabilitado por padrão. Abra **Settings → Plugins → OmniRoute**.
7. Confira se a interface carrega a URL e o estado da chave sem revelar o valor. Use **Buscar modelos** em `chat` e confirme que a lista corresponde à sua instância OmniRoute. Salve um modelo somente se pretender alterá-lo. A ativação como provedor de chat depende de clique explícito.
8. Faça um teste simples de leitura do catálogo, depois teste uma mudança não crítica em perfil de laboratório, se disponível. Confirme também que o dashboard web ainda mostra os mesmos valores.

**Distribuição definitiva pelo GitHub:** quando o repositório do plugin for publicado, prefira a função **Install from Git** do Hermes Desktop, com o alvo **Desktop** selecionado; em backend remoto o Hermes não transfere automaticamente o JS do CT221 para o notebook. Confirme as opções da versão instalada e revise o commit/fonte antes de habilitar. Nunca cole uma URL `file://` do CT221 no Windows: ela referencia o filesystem errado. Fonte: https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk.

## Testes mínimos de homologação

- O plugin aparece em Capabilities → Plugins **na máquina Desktop**; não há aba duplicada no menu lateral principal.
- `GET /status` retorna o estado do mesmo perfil do Hermes remoto; em outro perfil, dados não aparecem indevidamente.
- O campo da chave vem vazio, mesmo quando `api_key_configured=true`; apenas a indicação configurada é exibida.
- A descoberta de modelos usa o backend remoto e respeita `kind`.
- Alteração de modelo no Desktop aparece no painel web e vice-versa.
- O clique de ativação muda o provedor ativo; navegar pela página não muda provedor automaticamente.
- Falha de conexão/erro de permissão mostra mensagem genérica, sem imprimir segredos.
- Desabilitar a interface Desktop não desabilita os plugins Python no CT221.

## Erros frequentes

- **Plugin não aparece:** o arquivo JS provavelmente foi instalado somente no CT221 e não no notebook. Confirme a pasta local do Hermes Desktop e use Rescan. A versão do aplicativo Desktop precisa oferecer o SDK de plugins em disco.
- **Aba não aparece em Settings → Plugins:** verifique se o plugin Desktop está habilitado em Capabilities → Plugins. Em versões antigas pode existir somente a contribuição `settings.plugins`; confirme o SDK disponível.
- **Erro de API 404:** confirme que `omniroute-media` está habilitado no perfil Hermes conectado, que o `dashboard/manifest.json` aponta a `plugin_api.py` e que o gateway foi reiniciado após a instalação da parte Python.
- **Erro 401/403:** confira a conexão remota, a sessão autenticada e o perfil selecionado.
- **A chave não é exibida:** isso é proposital. Você só pode substituí-la; ela é armazenada pelo Hermes remoto.
- **Backend remanescente 0.3.2:** a página Desktop 0.4 utiliza exclusivamente os endpoints já presentes no backend 0.3.2; atualize o backend apenas se surgirem incompatibilidades comprovadas.

## Reversão

No Hermes Desktop, desabilite o plugin em Capabilities → Plugins. Para remover **só a UI do Desktop**, feche o aplicativo e renomeie/remova o arquivo ou diretório local `~/.hermes/desktop-plugins/omniroute-media/` (no Windows, `%USERPROFILE%\.hermes\desktop-plugins\omniroute-media\`). Se houver `plugin.js.backup-...`, restaure-o para `plugin.js`, reabra o Hermes Desktop e acione Rescan. **Não remova `omniroute-media` nem `omniroute-model` no CT221**: eles seguem em produção.

## Limitações atuais

- Testes automatizados são de lógica/SDK simulado; sem prova de execução na versão exata do Hermes Desktop do usuário ou gateway remoto.
- O recurso de `ctx.rest` depende da versão do Hermes Desktop, do gateway e do perfil habilitado. A interface não ignora restrições de autenticação.
- Em versões antigas, `registerSettingsPage` pode não existir: há fallback para `SETTINGS_PLUGINS_AREA`, cuja disponibilidade também deve ser confirmada na instalação real.
- Um plugin Desktop pode ter amplos privilégios de renderer; instale apenas fonte revisada e utilize o carregador oficial. Este código não chama APIs privilegiadas do Electron nem acessa arquivos locais.
