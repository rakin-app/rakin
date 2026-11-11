"""Every external service behind an interface, chosen by settings.

Each interface has a default that needs no network and no account: the console
mailer, `wa.me` links, files on local disk, no payment rail or bank feed, and no human
check on public forms. So a self-hosted instance works offline with none configured,
and a plugin is one more implementation selected by name (`MAILER=smtp`,
`BLOB_STORE=s3`, ...).
`tests/integrations` holds the contract every implementation passes.
"""

from dataclasses import dataclass

from fastapi import Request

from app.integrations.bankfeed import BankFeed, NoBankFeed
from app.integrations.blobstore import BlobStore, LocalBlobStore, S3BlobStore
from app.integrations.humancheck import HumanCheck, NoHumanCheck, TurnstileCheck
from app.integrations.mailer import ConsoleMailer, Mailer, SmtpMailer
from app.integrations.messenger import Messenger, WaMeMessenger
from app.integrations.payments import NoPaymentRail, PaymentRail
from app.settings import Settings


@dataclass(frozen=True)
class Integrations:
    mailer: Mailer
    messenger: Messenger
    blob_store: BlobStore
    payment_rail: PaymentRail
    bank_feed: BankFeed
    human_check: HumanCheck


def build_mailer(settings: Settings) -> Mailer:
    match settings.mailer:
        case "console":
            return ConsoleMailer()
        case "smtp":
            return SmtpMailer(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.mail_from,
                security=settings.smtp_security,
                username=settings.smtp_username,
                password=settings.smtp_password,
                timeout=settings.smtp_timeout_seconds,
            )


def build_blob_store(settings: Settings) -> BlobStore:
    match settings.blob_store:
        case "local":
            return LocalBlobStore(
                root=settings.blob_local_dir,
                secret_key=settings.secret_key,
                ttl_seconds=settings.blob_url_ttl_seconds,
            )
        case "s3":
            return S3BlobStore(
                endpoint_url=settings.s3_endpoint_url,
                public_endpoint_url=settings.s3_public_endpoint_url,
                region=settings.s3_region,
                bucket=settings.s3_bucket,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key,
                ttl_seconds=settings.blob_url_ttl_seconds,
            )


# One implementation each so far; a plugin adds a settings value and a `match` arm.
def build_messenger(settings: Settings) -> Messenger:
    match settings.messenger:
        case "wame":
            return WaMeMessenger()


def build_payment_rail(settings: Settings) -> PaymentRail:
    match settings.payment_rail:
        case "none":
            return NoPaymentRail()


def build_bank_feed(settings: Settings) -> BankFeed:
    match settings.bank_feed:
        case "none":
            return NoBankFeed()


def build_human_check(settings: Settings) -> HumanCheck:
    match settings.human_check:
        case "none":
            return NoHumanCheck()
        case "turnstile":
            return TurnstileCheck(
                site_key=settings.turnstile_site_key, secret_key=settings.turnstile_secret_key
            )


def build_integrations(settings: Settings) -> Integrations:
    return Integrations(
        mailer=build_mailer(settings),
        messenger=build_messenger(settings),
        blob_store=build_blob_store(settings),
        payment_rail=build_payment_rail(settings),
        bank_feed=build_bank_feed(settings),
        human_check=build_human_check(settings),
    )


def get_integrations(request: Request) -> Integrations:
    """FastAPI dependency: the integrations `create_app` built from its settings."""
    integrations: Integrations = request.app.state.integrations
    return integrations
