import { refusedAnonymised } from '../api/people'
import { t } from '../i18n/es'

/**
 * What a ficha's form says when its write failed (#581): `message`, unless the API
 * refused it because the person is an anonymous record (#372), which no retry changes.
 * The ficha offers no forms for one; this covers a write that reaches it anyway.
 */
export function failedMessage(error: unknown, message: string): string {
  return refusedAnonymised(error) ? t.admin.member.anonymisedRefused : message
}
