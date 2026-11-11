/**
 * A gym's logo (#223). The API names it by where its files are, `/api/logos/<gym>/<version>`
 * (`null` with no logo), and each file by its width: WebP squares of 64, 128 and 512 px.
 * A new logo is a new address, so the browser keeps each file for good.
 */

/** The logo's files, for an image `px` CSS pixels wide on any screen density. */
export function logoImage(logo: string, px: number): { src: string; srcSet: string; sizes: string } {
  const file = (width: number) => `${logo}/${width}.webp`
  return {
    src: file(px <= 32 ? 64 : px <= 64 ? 128 : 512),
    srcSet: [64, 128, 512].map((width) => `${file(width)} ${width}w`).join(', '),
    sizes: `${px}px`,
  }
}

/** The file the browser tab shows. */
export function logoIcon(logo: string): string {
  return `${logo}/64.webp`
}

/** What the owner may pick, before anything is sent: the API refuses the rest too. */
export const LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const
export const MAX_LOGO_BYTES = 5 * 1024 * 1024
