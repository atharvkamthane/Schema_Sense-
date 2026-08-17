import API from "./axios"

const INGEST_CLEAR_TIMEOUT_MS = 60_000
const INGEST_UPLOAD_TIMEOUT_MS = 300_000
const SCHEMA_TIMEOUT_MS = 45_000
const ANALYSIS_TIMEOUT_MS = 45_000
const SUMMARY_TIMEOUT_MS = 60_000
export const QUERY_TIMEOUT_MS = 60_000

export default API

let authGetter = null
export const setTokenGetter = (getter) => {
  authGetter = getter
}

const AUTH_TOKEN_TIMEOUT_MS = 8000

async function getAuthTokenWithTimeout() {
  if (!authGetter) return null

  try {
    const token = await Promise.race([
      authGetter(),
      new Promise((resolve) => {
        setTimeout(() => resolve(null), AUTH_TOKEN_TIMEOUT_MS)
      }),
    ])

    return token || null
  } catch (err) {
    console.warn("Failed to retrieve Clerk token for API request", err)
    return null
  }
}

const RETRYABLE_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504])

function wait(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

export function isRetryableRequestError(error) {
  const status = error?.response?.status
  const code = error?.code

  if (code === "ECONNABORTED") return true
  if (code === "ERR_NETWORK") return true
  if (code === "ECONNRESET") return true

  if (status && RETRYABLE_STATUS_CODES.has(status)) {
    return true
  }

  return false
}

export async function requestWithRetry(
  requestFactory,
  {
    retries = 2,
    baseDelayMs = 600,
    shouldRetry = isRetryableRequestError,
  } = {}
) {
  let attempt = 0
  let lastError = null

  while (attempt <= retries) {
    try {
      return await requestFactory()
    } catch (error) {
      lastError = error

      const canRetry = attempt < retries && shouldRetry(error)
      if (!canRetry) {
        throw error
      }

      const delayMs = baseDelayMs * Math.pow(2, attempt)
      await wait(delayMs)
      attempt += 1
    }
  }

  throw lastError
}

API.interceptors.request.use(async (config) => {
  const token = await getAuthTokenWithTimeout()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

API.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status
    const originalConfig = error?.config

    if (status === 401 && originalConfig && !originalConfig.__authRetried) {
      const token = await getAuthTokenWithTimeout()
      if (token) {
        originalConfig.__authRetried = true
        originalConfig.headers = {
          ...(originalConfig.headers || {}),
          Authorization: `Bearer ${token}`,
        }
        return API.request(originalConfig)
      }
    }

    return Promise.reject(error)
  }
)

let schemaCache = null
let schemaCacheTime = 0
const SCHEMA_CACHE_TTL_MS = 60_000

// API FUNCTIONS
export const getSchema = () => API.get(`/schema?t=${Date.now()}`, { timeout: SCHEMA_TIMEOUT_MS })
export const getSchemaWithCache = async ({ force = false } = {}) => {
  const age = Date.now() - schemaCacheTime
  if (!force && schemaCache && age < SCHEMA_CACHE_TTL_MS) {
    return schemaCache
  }

  const res = await API.get(`/schema?t=${Date.now()}`, { timeout: SCHEMA_TIMEOUT_MS })
  schemaCache = res
  schemaCacheTime = Date.now()
  return res
}

export const bustSchemaCache = () => {
  schemaCache = null
  schemaCacheTime = 0
}

export const getQuality = () => API.get(`/quality?t=${Date.now()}`)
export const getTableQuality = (tableName) => API.get(`/quality/${tableName}?t=${Date.now()}`)
export const getTableAnalysis = (tableName, config = {}) =>
  API.get(`/analysis/${encodeURIComponent(tableName)}?t=${Date.now()}`, {
    timeout: ANALYSIS_TIMEOUT_MS,
    ...config,
  })
export const getSummaryNarrative = (payload = {}, config = {}) =>
  API.post(
    "/api/generate-summary",
    {
      schema_data: payload?.schema_data ?? payload?.schemaData ?? { tables: [] },
      user_context: payload?.user_context ?? payload?.userContext ?? "",
    },
    {
      timeout: SUMMARY_TIMEOUT_MS,
      ...config,
    }
  )
export const getRelationships = () => API.get(`/relationships?t=${Date.now()}`)
export const getGraphData = (payload = {}) => API.post("/graph-data", payload)
export const postQueryPayload = (payload = {}, config = {}) =>
  requestWithRetry(
    () =>
      API.post("/query", payload, {
        timeout: QUERY_TIMEOUT_MS,
        ...config,
      }),
    {
      retries: 1,
    }
  )

export const postQuery = (query, config = {}) => postQueryPayload({ query }, config)
export const analyzeTableWithAI = (prompt, config = {}) => postQuery(prompt, config)

export const postNL2SQLQuery = (payload = {}, config = {}) =>
  API.post("/nl2sql/query", payload, {
    timeout: 120_000,
    ...config,
  })

export const nl2sqlQuery = (question, maxRetries = 2, topK = 8, config = {}) =>
  postNL2SQLQuery({ question, max_retries: maxRetries, top_k: topK }, config)

export const postColumnChat = (payload) => API.post("/column-chat", payload)
export const clearDatabase = () =>
  API.post("/ingest/clear", undefined, {
    timeout: INGEST_CLEAR_TIMEOUT_MS,
  })

export async function streamColumnChat(
  { table, column, question },
  { onMeta, onDelta, onDone, onError, signal } = {}
) {
  const headers = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true",
  }

  const token = await getAuthTokenWithTimeout()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API.defaults.baseURL}/query/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ mode: "column_chat", table, column, question }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`Streaming request failed (${response.status})`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder("utf-8")
  let buffer = ""

  const emitEvent = (eventName, payload) => {
    const type = payload?.type || eventName || ""
    if (type === "meta") {
      onMeta?.(payload?.context || payload)
      return
    }
    if (type === "delta") {
      onDelta?.(payload?.chunk || payload?.delta || payload?.token || payload?.content || "")
      return
    }
    if (type === "done") {
      onDone?.(payload?.payload || payload)
      return
    }
    if (type === "error") {
      onError?.(payload?.message || "Streaming failed")
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split("\n\n")
    buffer = chunks.pop() || ""

    for (const chunk of chunks) {
      if (!chunk.trim()) continue
      let eventName = "message"
      const dataLines = []

      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim()
        }
        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim())
        }
      }

      if (!dataLines.length) continue
      const dataString = dataLines.join("\n")

      try {
        const payload = JSON.parse(dataString)
        emitEvent(eventName, payload)
      } catch {
        emitEvent(eventName, { type: eventName, delta: dataString })
      }
    }
  }
}

export const uploadFile = async (file) => {
  const formData = new FormData()
  formData.append("file", file)

  try {
    const res = await API.post("/ingest/file", formData, {
      // File ingest can take longer than regular metadata requests.
      timeout: INGEST_UPLOAD_TIMEOUT_MS,
    })
    return res
  } catch (err) {
    throw err
  }
}