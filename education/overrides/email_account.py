"""The framework's mail accounts hold owned addresses, never server credentials."""
from frappe.email.doctype.email_account.email_account import EmailAccount
from education.pramaan import PramaanError


class DisabledMailTransport:
    """An inert compatibility handle; no socket or SMTP object is created."""

    def quit(self):
        return None

    @property
    def session(self):
        raise PramaanError("unsupported_transport")


class SchoolEmailAccount(EmailAccount):
    def validate(self):
        from frappe.utils import validate_email_address
        validate_email_address(self.email_id, True)
        # These records hold owned mailbox addresses, never credentials.
        self.service = ""
        self.auth_method = "Basic"
        self.password = None
        self.api_key = None
        self.api_secret = None
        self.frappe_mail_site = None
        self.email_server = None
        self.smtp_server = None
        self.use_imap = 0
        self.use_pop = 0
        self.enable_incoming = 0
        self.connected_app = None
        self.connected_user = None
        self.track_email_status = 0
        self.append_emails_to_sent_folder = 0
        self.append_to = None

    def get_smtp_server(self):
        return DisabledMailTransport()

    def get_incoming_server(self, **kwargs):
        raise PramaanError("unsupported_transport")

    def get_frappe_mail_client(self):
        raise PramaanError("unsupported_transport")
