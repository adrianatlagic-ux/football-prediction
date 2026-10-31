import { useEffect, useState } from 'react'
import { parseRoute } from './navigation.js'

function currentRoute() {
  const parsed = parseRoute(window.location.pathname, window.location.hash)
  const remembered = window.history.state?.competition
  return parsed.page === 'how-it-works' && ['cl', 'bl', 'nl'].includes(remembered)
    ? { ...parsed, competition: remembered } : parsed
}

export function useSiteRoute() {
  const [route, setRoute] = useState(currentRoute)
  useEffect(() => {
    const onBackOrForward = () => setRoute(currentRoute())
    window.addEventListener('popstate', onBackOrForward)
    return () => window.removeEventListener('popstate', onBackOrForward)
  }, [])
  function navigate(path) {
    if (window.location.pathname + window.location.hash === path) return
    // Actual navigation, also observed by the existing Cloudflare SPA beacon.
    window.history.pushState({ competition: route.competition || 'cl' }, '', path)
    setRoute(currentRoute())
  }
  return [route, navigate]
}
