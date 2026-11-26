/**
 * OmniRoute for Hermes Desktop — native Settings → Plugins integration.
 *
 * This ESM file runs on the Desktop computer, even when Hermes serves from a
 * remote CT. It NEVER accesses the OmniRoute API directly, stores credentials,
 * or reads files in the remote Hermes home. The only backend surface is the
 * profile-scoped and authenticated ctx.rest('/...') SDK door.
 */
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'
import * as sdk from '@hermes/plugin-sdk'

const CATEGORIES = Object.freeze([
  ['chat', 'LLM / Chat'],
  ['image', 'Imagens'],
  ['video', 'Vídeos'],
  ['tts', 'Síntese de voz (TTS)'],
  ['stt', 'Transcrição de voz (STT)'],
])

const PREFERENCES = Object.freeze([
  ['tts_voice', 'Voz TTS específica do provedor'],
  ['search_provider', 'Provedor de pesquisa (opcional)'],
  ['fetch_provider', 'Provedor de extração web (opcional)'],
])

// Only the route prefix is authoritative here: the native picker supplies
// IDs, not OmniRoute's owned_by/root metadata. Never guess a vendor for a bare
// ID or replace a routing ID with a display label.
function decorateOmniRouteRow(row) {
  if (!row || !['omniroute', 'omni-route'].includes(String(row.provider || '').toLowerCase())) return null
  if (typeof row.model !== 'string' || !row.model.trim()) return null
  const id = row.model
  const slash = id.indexOf('/')
  const prefix = slash > 0 ? id.slice(0, slash) : ''
  return { badge: prefix || 'Sem prefixo' }
}

function errorText(error) {
  // Never show raw remote error bodies or echo arbitrary values from the server.
  const status = Number(error?.status ?? error?.statusCode ?? 0)
  if (status === 401 || status === 403) return 'Acesso ao backend negado; confira sua sessão e seu perfil do Hermes.'
  if (status === 404) return 'API OmniRoute não disponível no Hermes conectado. Verifique o plugin omniroute-media no perfil remoto.'
  if (status === 409) return 'Configure o endpoint, a credencial e o modelo antes de continuar.'
  if (status === 422) return 'Valor inválido. Confira a URL, o identificador e os campos informados.'
  if (status >= 500) return 'O servidor Hermes ou OmniRoute apresentou erro. Consulte os logs do backend.'
  return 'Não foi possível concluir a operação. Confira conexão, perfil e permissões.'
}

function Title({ children }) {
  return jsx('h3', { className: 'font-semibold text-sm mb-2', children })
}

function Section({ title, children }) {
  return jsxs('section', {
    className: 'rounded-lg border p-3 mb-4',
    style: { borderColor: 'var(--ui-stroke-secondary)' },
    children: [jsx(Title, { children: title }), children],
  })
}

function Field({ label, children }) {
  return jsxs('label', {
    className: 'block mb-3 text-sm',
    children: [
      jsx('span', { className: 'block mb-1', children: label }),
      children,
    ],
  })
}

function TextField(props) {
  const UIInput = sdk.Input || 'input'
  return jsx(UIInput, {
    ...props,
    className: 'w-full min-w-0 rounded border px-2 py-1.5 text-sm',
    style: { borderColor: 'var(--ui-stroke-secondary)' },
  })
}

function Action({ children, disabled, onClick }) {
  const UIButton = sdk.Button || 'button'
  return jsx(UIButton, {
    type: 'button',
    disabled: !!disabled,
    onClick,
    className: 'rounded border px-3 py-1.5 text-sm disabled:opacity-50',
    style: { borderColor: 'var(--ui-stroke-secondary)' },
    children,
  })
}

function OmniRouteSettings({ rest }) {
  const [state, setState] = useState(null)
  const [url, setUrl] = useState('')
  // Never persist this field in browser-side caches or query parameters.
  const [replacementKey, setReplacementKey] = useState('')
  const [models, setModels] = useState({})
  const [preferences, setPreferences] = useState({})
  const [catalogs, setCatalogs] = useState({})
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState('')

  function incorporateStatus(next) {
    if (!next || typeof next !== 'object') throw new Error('Invalid server status')
    setState(next)
    setUrl(typeof next.base_url === 'string' ? next.base_url : '')
    setModels(next.models && typeof next.models === 'object' ? next.models : {})
    setPreferences(next.preferences && typeof next.preferences === 'object' ? next.preferences : {})
  }

  // The SDK scopes requests to the active gateway/profile. If the host changes,
  // remount/reload this page; never cache a remote credential or full response.
  useEffect(() => {
    let disposed = false
    rest('/status')
      .then(result => { if (!disposed) incorporateStatus(result) })
      .catch(error => { if (!disposed) setFeedback(errorText(error)) })
    return () => { disposed = true }
  }, [rest])

  async function submit(path, body, success) {
    if (busy) return
    setBusy(true)
    setFeedback('')
    try {
      const response = await rest(path, { method: 'POST', body })
      incorporateStatus(response)
      setReplacementKey('')
      setFeedback(success + ' Reinicie/recarregue o Hermes se necessário.')
    } catch (error) {
      setFeedback(errorText(error))
    } finally {
      // Also clear a failed replacement credential so it isn't kept in state.
      setReplacementKey('')
      setBusy(false)
    }
  }

  async function refreshStatus() {
    if (busy) return
    setBusy(true)
    setFeedback('')
    try {
      const result = await rest('/status')
      incorporateStatus(result)
      setFeedback('Estado atualizado a partir do Hermes conectado.')
    } catch (error) {
      setFeedback(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  async function discover(kind) {
    if (busy) return
    setBusy(true)
    setFeedback('')
    try {
      const response = await rest('/models?kind=' + encodeURIComponent(kind))
      if (!response || !Array.isArray(response.models)) throw new Error('Invalid models payload')
      const rows = response.models
        .filter(item => item && typeof item.id === 'string' && item.id.length <= 256)
        .map(item => ({
          id: item.id,
          label: typeof item.route_label === 'string' && item.route_label ? item.route_label : item.id,
        }))
      setCatalogs(previous => ({ ...previous, [kind]: rows }))
      const info = response.diagnostics
      const counts = info && info.classified
      setFeedback(info && counts
        ? 'Catálogo de ' + kind + ': ' + rows.length + ' exibidos; ' +
          info.received + ' recebidos; chat ' + counts.chat + ', imagem ' + counts.image +
          ', vídeo ' + counts.video + ', TTS ' + counts.tts + ', STT ' + counts.stt +
          ', combos ' + info.combos + ', outros ' + info.other +
          '; duplicatas ' + info.duplicates_removed + '; entregues pela API do plugin ' + info.delivered +
          '; ' + info.pages + ' páginas / ' + info.requests + ' requisições; ' +
          info.duration_ms + ' ms; origem ' + info.source + '.'
        : 'Catálogo de ' + kind + ': ' + rows.length + ' modelo(s).')
    } catch (error) {
      setFeedback(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  const configured = !!(state && state.api_key_configured)
  const selectedChat = !!(models.chat && String(models.chat).trim())

  return jsxs('div', {
    className: 'max-w-3xl p-3 text-sm',
    children: [
      jsx('p', {
        className: 'mb-3',
        style: { color: 'var(--ui-text-secondary)' },
        children: 'Configuração do OmniRoute mantida no perfil do Hermes conectado. A chave nunca é retornada ao Desktop.',
      }),
      jsx(Section, {
        title: 'Conexão',
        children: jsxs('div', { children: [
          jsx(Field, {
            label: 'API Base URL (/v1 ou /api/v1)',
            children: jsx(TextField, {
              value: url,
              onChange: e => setUrl(e.target.value),
              placeholder: 'https://router.example/api/v1',
              autoComplete: 'off',
            }),
          }),
          jsx(Field, {
            label: 'Substituir a chave de API (deixe vazia para manter a atual)',
            children: jsx(TextField, {
              type: 'password',
              value: replacementKey,
              onChange: e => setReplacementKey(e.target.value),
              placeholder: configured ? 'Chave configurada' : 'Chave não configurada',
              autoComplete: 'new-password',
            }),
          }),
          jsxs('div', {
            className: 'flex flex-wrap items-center gap-2',
            children: [
              jsx(Action, {
                disabled: busy || !(url.trim() || replacementKey),
                onClick: () => submit('/connection', { base_url: url.trim(), api_key: replacementKey }, 'Conexão salva.'),
                children: 'Salvar conexão',
              }),
              jsx(Action, {
                disabled: busy,
                onClick: refreshStatus,
                children: 'Atualizar estado',
              }),
              jsx('span', {
                style: { color: 'var(--ui-text-secondary)' },
                children: configured ? 'Credencial configurada' : 'Credencial ainda não configurada',
              }),
            ],
          }),
        ] }),
      }),
      jsx(Section, {
        title: 'Seleção de modelos',
        children: CATEGORIES.map(([kind, label]) => jsx('div', {
          className: 'mb-3',
          children: jsxs('div', { children: [
            jsx(Field, {
              label,
              children: jsx(TextField, {
                value: String(models[kind] || ''),
                onChange: event => setModels(previous => ({ ...previous, [kind]: event.target.value })),
                placeholder: 'Identificador de modelo',
              }),
            }),
            jsxs('div', {
              className: 'flex flex-wrap gap-2 mb-2',
              children: [
                jsx(Action, {
                  disabled: busy || !String(models[kind] || '').trim(),
                  onClick: () => submit('/model', { kind, model: String(models[kind]).trim() }, label + ' salvo.'),
                  children: 'Salvar',
                }),
                jsx(Action, {
                  disabled: busy,
                  onClick: () => discover(kind),
                  children: 'Buscar modelos',
                }),
              ],
            }),
            catalogs[kind] && jsx('select', {
              className: 'w-full rounded border px-2 py-1.5',
              style: { borderColor: 'var(--ui-stroke-secondary)' },
              defaultValue: '',
              'aria-label': 'Modelos disponíveis: ' + label,
              onChange: e => { if (e.target.value) setModels(old => ({ ...old, [kind]: e.target.value })) },
              children: [
                jsx('option', { value: '', children: 'Escolha um modelo (' + catalogs[kind].length + ')' }),
                ...catalogs[kind].map(item => jsx('option', { value: item.id, children: item.label }, item.id)),
              ],
            }),
          ] }),
        }, kind)),
      }),
      jsx(Section, {
        title: 'Preferências adicionais',
        children: PREFERENCES.map(([kind, label]) => jsx('div', {
          className: 'mb-3',
          children: jsxs('div', { children: [
            jsx(Field, {
              label,
              children: jsx(TextField, {
                value: String(preferences[kind] || ''),
                onChange: e => setPreferences(old => ({ ...old, [kind]: e.target.value })),
                placeholder: 'Opcional',
              }),
            }),
            jsx(Action, {
              disabled: busy,
              onClick: () => submit('/preference', { kind, value: String(preferences[kind] || '').trim() }, 'Preferência salva.'),
              children: 'Salvar preferência',
            }),
          ] }),
        }, kind)),
      }),
      jsx(Section, {
        title: 'Ativação do chat',
        children: jsxs('div', { children: [
          jsx('p', {
            className: 'mb-2',
            children: state?.native_chat_provider_active
              ? 'OmniRoute é o provedor de chat ativo deste perfil.'
              : 'OmniRoute ainda não foi ativado para chat neste perfil.',
          }),
          jsx(Action, {
            disabled: busy || !configured || !selectedChat || !url.trim(),
            onClick: () => submit('/activate-chat', {}, 'OmniRoute ativado como provedor de chat.'),
            children: 'Ativar OmniRoute para chat',
          }),
        ] }),
      }),
      feedback && jsx('p', {
        role: 'status',
        className: 'my-3',
        style: { color: 'var(--ui-text-secondary)' },
        children: feedback,
      }),
    ],
  })
}

export default {
  id: 'omniroute-media',
  name: 'OmniRoute',
  defaultEnabled: false,
  register(ctx) {
    // Keep the SDK context as the call receiver; the wrapper is stable
    // across page re-renders so the initial GET effect runs only once.
    const scopedRest = (path, options) => ctx.rest(path, options)
    // Official SDK contribution: only a textual badge, no DOM patching.
    // Older Desktop versions simply retain the native unadorned menu.
    if (typeof sdk.MODEL_MENU_ROW_AREA === 'string') {
      ctx.register({
        id: 'omniroute-origin',
        area: sdk.MODEL_MENU_ROW_AREA,
        data: { decorate: decorateOmniRouteRow },
      })
    }
    const page = {
      id: 'settings',
      title: 'OmniRoute',
      icon: 'settings-gear',
      order: 50,
      render: () => jsx(OmniRouteSettings, { rest: scopedRest }),
    }
    if (typeof ctx.registerSettingsPage === 'function') {
      ctx.registerSettingsPage(page)
    } else {
      // Older Desktop SDKs: same Settings → Plugins contribution.
      ctx.register({
        area: sdk.SETTINGS_PLUGINS_AREA || 'settings.plugins',
        id: page.id,
        title: page.title,
        render: page.render,
        data: { icon: page.icon },
      })
    }
  },
}
