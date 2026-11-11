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

export function CheckIcon() {
  return (
    <Icon width={16} height={16}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
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

export function MyPageIcon() {
  return (
    <Icon>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </Icon>
  )
}

export function SignOutIcon() {
  return (
    <Icon>
      <path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4M15 17l5-5-5-5M20 12H9" />
    </Icon>
  )
}

export function WhatsAppIcon() {
  return (
    <Icon>
      <path d="M21 12a9 9 0 0 1-13.3 7.9L3 21l1.1-4.6A9 9 0 1 1 21 12z" />
      <path d="M9 10a.5.5 0 0 0 .5.5h0A5.5 5.5 0 0 0 14 15h0a.5.5 0 0 0 .5-.5V13l-2-1-1 1a4 4 0 0 1-2-2l1-1-1-2H9.5a.5.5 0 0 0-.5.5z" />
    </Icon>
  )
}

export function SearchIcon() {
  return (
    <Icon width={18} height={18}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </Icon>
  )
}
