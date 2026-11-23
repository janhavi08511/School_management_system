
const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  'http://127.0.0.1:8000'
).replace(/\/+$/, '')

const DEFAULT_TIMEOUT = 60000

/**
 * Common API request function.
 *
 * Supports:
 * - JWT authentication
 * - JSON and FormData requests
 * - AbortController cancellation
 * - Request timeout
 * - Development performance logging
 * - Better error handling
 */
export async function apiRequest(path, token, options = {}) {
  const {
    timeout = DEFAULT_TIMEOUT,
    signal: externalSignal,
    headers: customHeaders = {},
    body,
    ...fetchOptions
  } = options

  const headers = {
    Accept: 'application/json',
    ...customHeaders,
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const isFormData =
    typeof FormData !== 'undefined' &&
    body instanceof FormData

  let requestBody = body

  if (body !== undefined && body !== null && !isFormData) {
    if (
      typeof body === 'object' &&
      !(body instanceof Blob) &&
      !(body instanceof ArrayBuffer)
    ) {
      requestBody = JSON.stringify(body)
    }

    if (
      !headers['Content-Type'] &&
      !headers['content-type']
    ) {
      headers['Content-Type'] = 'application/json'
    }
  }

  const controller = new AbortController()

  let timedOut = false

  const abortFromExternalSignal = () => {
    controller.abort(externalSignal?.reason)
  }

  if (externalSignal) {
    if (externalSignal.aborted) {
      abortFromExternalSignal()
    } else {
      externalSignal.addEventListener(
        'abort',
        abortFromExternalSignal,
        { once: true }
      )
    }
  }

  const timeoutId = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)

  const startedAt = import.meta.env.DEV
    ? performance.now()
    : 0

  const method = (
    fetchOptions.method || 'GET'
  ).toUpperCase()

  try {
    const response = await fetch(
      `${API_BASE_URL}${path}`,
      {
        ...fetchOptions,
        method,
        body: requestBody,
        headers,
        signal: controller.signal,
      }
    )

    // Handle empty responses such as HTTP 204.
    if (response.status === 204) {
      return null
    }

    const contentType =
      response.headers.get('content-type') || ''

    let payload

    if (contentType.includes('application/json')) {
      try {
        payload = await response.json()
      } catch {
        throw new Error('Server returned invalid JSON.')
      }
    } else {
      const responseText = await response.text()

      payload = responseText
        ? { detail: responseText }
        : null
    }

    if (!response.ok) {
      const errorMessage =
        payload?.detail ||
        payload?.message ||
        `Request failed (${response.status})`

      const error = new Error(errorMessage)
      error.status = response.status
      error.data = payload

      throw error
    }

    // Development-only API performance monitoring.
    if (import.meta.env.DEV) {
      const elapsedMs = Math.round(
        performance.now() - startedAt
      )

      const responseSize =
        response.headers.get('content-length')

      console.debug(
        `[API] ${method} ${path}`,
        {
          status: response.status,
          time: `${elapsedMs} ms`,
          responseSize: responseSize
            ? `${responseSize} bytes`
            : 'Not provided',
        }
      )

      if (elapsedMs > 3000) {
        console.warn(
          `[SLOW API] ${method} ${path} took ${elapsedMs} ms`
        )
      }
    }

    return payload

  } catch (error) {
    if (error.name === 'AbortError') {
      if (timedOut) {
        throw new Error(
          `Request timed out after ${timeout / 1000} seconds: ${path}`,
          { cause: error },
        )
      }

      // Preserve cancellation for callers that need to ignore it.
      throw error
    }

    if (import.meta.env.DEV) {
      console.error(
        `[API ERROR] ${method} ${path}:`,
        error
      )
    }

    throw error

  } finally {
    clearTimeout(timeoutId)

    if (externalSignal) {
      externalSignal.removeEventListener(
        'abort',
        abortFromExternalSignal
      )
    }
  }
}

/**
 * Download a file from the backend.
 *
 * Supports JWT authentication and cancellation.
 */
export async function downloadFile(
  path,
  token,
  filename,
  options = {}
) {
  const {
    signal,
    timeout = DEFAULT_TIMEOUT,
  } = options

  const controller = new AbortController()

  let timedOut = false

  const abortFromExternalSignal = () => {
    controller.abort(signal?.reason)
  }

  if (signal) {
    if (signal.aborted) {
      abortFromExternalSignal()
    } else {
      signal.addEventListener(
        'abort',
        abortFromExternalSignal,
        { once: true }
      )
    }
  }

  const timeoutId = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)

  try {
    const response = await fetch(
      `${API_BASE_URL}${path}`,
      {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        signal: controller.signal,
      }
    )

    if (!response.ok) {
      let message = response.statusText

      try {
        const payload = await response.json()
        message =
          payload?.detail ||
          payload?.message ||
          message
      } catch {
        // Keep the HTTP status text.
      }

      const error = new Error(
        message || `Request failed (${response.status})`
      )

      error.status = response.status
      throw error
    }

    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)

    try {
      const link = document.createElement('a')

      link.href = objectUrl
      link.download = filename

      document.body.appendChild(link)
      link.click()
      link.remove()

    } finally {
      // Revoke after the browser has started the download.
      setTimeout(() => {
        URL.revokeObjectURL(objectUrl)
      }, 1000)
    }

  } catch (error) {
    if (error.name === 'AbortError' && timedOut) {
      throw new Error(
        `File download timed out after ${timeout / 1000} seconds.`,
        { cause: error },
      )
    }

    throw error

  } finally {
    clearTimeout(timeoutId)

    if (signal) {
      signal.removeEventListener(
        'abort',
        abortFromExternalSignal
      )
    }
  }
}
