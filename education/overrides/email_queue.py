"""Block the framework SMTP path; queued mail rides the Pramaan boundary."""
from email import message_from_string

import frappe
from frappe.email.doctype.email_queue.email_queue import EmailQueue

from education.integrations.pramaan_mail import marker_from, sendmail


class PramaanEmailQueue(EmailQueue):
    def send(self, **kwargs):
        if not self.can_send_now() and not kwargs.get("force_send"):
            return
        if self.get("pramaan_outbox"):
            return
        parsed = message_from_string(self.message)
        if parsed.is_multipart():
            self.db_set({"status": "Error", "error": "Recreate this queued email with its editor."})
            return
        content = parsed.get_payload(decode=True) or b""
        result = sendmail(sender=self.sender, recipients=[r.recipient for r in self.recipients if not r.is_mail_sent()],
                          subject=parsed.get("Subject", "Message"), message=content.decode(parsed.get_content_charset() or "utf-8", "replace"),
                          communication=self.communication,
                          auto_submitted=marker_from(parsed.get("Auto-Submitted") or parsed.get("X-Auto-Generated")))
        self.db_set({"pramaan_outbox": result.name, "status": "Sending"})
