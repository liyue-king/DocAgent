/**
 * 文件下载工具：
 * - 同源地址（/api/v1/download/...）：fetch 为 blob 后触发浏览器下载，
 *   不依赖弹窗权限，也能拿到后端返回的正确文件名；
 * - 跨域地址（兼容旧版预签名 URL）：用隐藏 <a> 导航触发下载，避免弹窗拦截。
 */

function parseFilename(disposition, fallback) {
  if (!disposition) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      // 忽略解码失败，继续尝试普通 filename
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : fallback
}

export async function downloadFileFromUrl(url, fallbackName = 'download.docx') {
  if (!url) {
    throw new Error('下载地址不存在')
  }

  const sameOrigin = url.startsWith('/') || url.startsWith(window.location.origin)
  if (sameOrigin) {
    const resp = await fetch(url)
    if (!resp.ok) {
      let message = `下载失败（HTTP ${resp.status}）`
      try {
        const data = await resp.clone().json()
        if (data && data.msg) message = data.msg
      } catch {
        // 响应体不是 JSON，使用默认错误文案
      }
      throw new Error(message)
    }
    const blob = await resp.blob()
    const filename = parseFilename(resp.headers.get('content-disposition'), fallbackName)
    const objectUrl = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(objectUrl), 4000)
    return
  }

  const anchor = document.createElement('a')
  anchor.href = url
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}
