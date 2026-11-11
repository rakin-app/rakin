/**
 * The browser tab's icon: Rakin's (#224), or on a gym's own address the gym's logo once
 * it has one (#223). `index.html` declares Rakin's icons; this points every one of them
 * at the gym's logo, and back. #223 calls it with the logo's URL when the host says
 * which gym this is.
 */
export function setTabIcon(gymLogoUrl: string | null | undefined): void {
  for (const link of document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]')) {
    // Rakin's own values, kept on the element the first time they are replaced.
    if (link.dataset.rakinHref === undefined) {
      link.dataset.rakinHref = link.getAttribute('href') ?? ''
      link.dataset.rakinType = link.getAttribute('type') ?? ''
      link.dataset.rakinSizes = link.getAttribute('sizes') ?? ''
    }
    if (gymLogoUrl) {
      link.href = gymLogoUrl
      // The logo is whatever the gym uploaded: no type or sizes to promise.
      link.removeAttribute('type')
      link.removeAttribute('sizes')
    } else {
      restore(link, 'href', link.dataset.rakinHref)
      restore(link, 'type', link.dataset.rakinType)
      restore(link, 'sizes', link.dataset.rakinSizes)
    }
  }
}

function restore(link: HTMLLinkElement, name: string, value: string | undefined) {
  if (value) link.setAttribute(name, value)
  else link.removeAttribute(name)
}
