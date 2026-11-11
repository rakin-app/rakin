/** Class names joined with spaces, skipping the ones that are off. */
export const cx = (...names: (string | false | null | undefined)[]): string => names.filter(Boolean).join(' ')
