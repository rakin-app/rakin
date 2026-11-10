import type { SVGProps } from 'react'

// Stroke icons from docs/design/ui-design.html (24×24 grid, 2px stroke).
function Icon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={22}
      height={22}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    />
  )
}

export function TodayIcon() {
  return (
    <Icon>
      <path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1z" />
    </Icon>
  )
}

export function StudentsIcon() {
  return (
    <Icon>
      <circle cx="9" cy="8" r="4" />
      <path d="M2 21a7 7 0 0 1 14 0M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-5-6.7" />
    </Icon>
  )
}

export function ClassesIcon() {
  return (
    <Icon>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </Icon>
  )
}

export function PaymentsIcon() {
  return (
    <Icon>
      <path d="M4 4h16v16H4zM4 9h16M9 4v16" />
    </Icon>
  )
}

export function SettingsIcon() {
  return (
    <Icon>
      <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="10" cy="12" r="2" />
      <circle cx="18" cy="18" r="2" />
    </Icon>
  )
}

export function ChevronLeftIcon() {
  return (
    <Icon width={20} height={20}>
      <path d="M15 18l-6-6 6-6" />
    </Icon>
  )
}

export function ChevronRightIcon() {
  return (
    <Icon width={20} height={20}>
      <path d="M9 18l6-6-6-6" />
    </Icon>
  )
}

export function ChevronUpIcon() {
  return (
    <Icon width={20} height={20}>
      <path d="M6 15l6-6 6 6" />
    </Icon>
  )
}

export function ChevronDownIcon() {
  return (
    <Icon width={20} height={20}>
      <path d="M6 9l6 6 6-6" />
    </Icon>
  )
}

export function CloseIcon() {
  return (
    <Icon width={20} height={20}>
      <path d="M18 6L6 18M6 6l12 12" />
    </Icon>
  )
}
