# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import base64
import json
from datetime import timedelta
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from education.education import pramaan_features as features
from education.pramaan import PramaanClient, PramaanError


class TestEducationSettings(FrappeTestCase):
    """Approved feature paths use only an in-memory capability transport."""

    def setUp(self):
        self.calls = []
        self.results = {}

        def transport(method, url, headers, body):
            capability = url.split('/capabilities/')[-1]
            self.calls.append((capability, body, headers))
            if capability.endswith('/estimate'):
                return 200, {'can_run': True}
            return 200, self.results.get(capability, {})

        self.fake = PramaanClient(api_key='fixture-only', transport=transport)
        self.enterContext(patch.object(features, 'client', return_value=self.fake))
        self.enterContext(patch.object(features, '_staff'))
        self.doc = Mock()
        self.doc.get.side_effect = lambda key: getattr(self.doc, key, None) if key in self.doc.__dict__ else None
        self.doc.name = 'fixture'
        self.doc.schedule_date = '2026-10-16'
        self.doc.from_time = timedelta(hours=9)
        self.doc.to_time = timedelta(hours=10, minutes=30)
        self.doc.student_batch = 'batch'
        self.doc.faculty = 'faculty'
        self.doc.title = 'Class'
        self.doc.subject = 'Math'
        self.doc.calendar_event_ref = None
        self.doc.meeting_room_ref = None
        self.doc.meeting_url = None
        self.doc.course = 'course'
        self.doc.payment_link_id = 'link_fixture'
        self.enterContext(patch.object(frappe, 'get_doc', return_value=self.doc))
        self.enterContext(patch.object(frappe.db, 'get_single_value', side_effect=lambda dt, field: {
            'meetings_app': 'connected-app', 'calendar_inbox': 'school@example.com',
            'time_zone': 'Europe/London',
        }.get(field)))

    def action(self):
        return self.enterContext(patch.object(features, '_action', side_effect=lambda capability, inputs, **kw:
            self.fake.call(capability, inputs, idempotency_key='saved-fixture')))

    def test_app_connection_uses_hosted_link_and_private_user_reference(self):
        self.action()
        self.doc.pramaan_app_id = 'calendar_app'
        self.results['apps.connection.start'] = {'connectUrl': 'https://connect.example/fixture'}
        result = features.start_app_connection('fixture')
        self.assertEqual(result['connectUrl'], 'https://connect.example/fixture')
        capability, body, headers = self.calls[-1]
        self.assertEqual(capability, 'apps.connection.start')
        self.assertNotIn('Pramaan-Approved-By', self.calls[-1][2])
        self.assertEqual(body['app'], 'calendar_app')
        self.assertTrue(body['endUserRef'].startswith('edu-'))
        self.assertNotIn('@', body['endUserRef'])
        self.assertTrue(body['redirectUrl'].endswith('/app/connected-app/fixture'))
        self.doc.check_permission.assert_called_once_with('write')

    def test_absence_lookup_uses_current_query_syntax(self):
        result = features.send_guardian_alerts('missing-qa-batch', '2026-10-17', 'QA absence', 'sms')
        self.assertEqual(result, {'queued': 0, 'skipped': 0})

    def test_meeting_has_duration_timezone_and_saved_reference(self):
        self.action()
        self.results['meetings.room.create'] = {'ref': 'meeting-ref', 'joinUrl': 'https://meeting.example/guest'}
        result = features.create_class_meeting('fixture')
        self.assertEqual(result['url'], 'https://meeting.example/guest')
        capability, body, _ = self.calls[-1]
        self.assertEqual(capability, 'meetings.room.create')
        self.assertEqual(body['durationMinutes'], 90)
        self.assertEqual(body['start'], '2026-10-16T09:00:00+01:00')
        self.doc.db_set.assert_called_once()
        self.doc.check_permission.assert_called_with('write')

    def test_existing_meeting_reads_without_creating_another(self):
        self.doc.meeting_room_ref = 'meeting-ref'
        self.results['meetings.room.get'] = {'joinUrl': 'https://meeting.example/guest', 'status': 'scheduled'}
        result = features.create_class_meeting('fixture')
        self.assertEqual(result['status'], 'scheduled')
        self.assertEqual([row[0] for row in self.calls], ['meetings.room.get'])

    def test_calendar_create_and_update_for_class_and_exam(self):
        self.action()
        guardian = frappe._dict(email_address='guardian@example.com')
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(student='student')]), \
             patch.object(features, '_guardians_of', return_value=[guardian]), \
             patch.object(frappe.db, 'get_value', return_value='teacher@example.com'):
            for doctype in ('Subject Schedule', 'Assessment Plan'):
                for ref in (None, 'event-ref'):
                    self.doc.calendar_event_ref = ref
                    capability = 'calendar.event.update' if ref else 'calendar.event.create'
                    self.results[capability] = {'ref': 'event-ref'}
                    self.assertEqual(features.sync_calendar_entry(doctype, 'fixture')['ref'], 'event-ref')
                    body = self.calls[-1][1]
                    self.assertEqual(body['inbox'], 'school@example.com')
                    self.assertEqual(body['end'], '2026-10-16T10:30:00')
                    self.assertEqual(body['attendees'], [{'email': 'guardian@example.com'}, {'email': 'teacher@example.com'}])
                    self.assertTrue(body['sendInvites'])

    def test_invalid_schedule_does_not_call_the_client(self):
        self.doc.to_time = timedelta(hours=8)
        with self.assertRaises(frappe.ValidationError):
            features.create_class_meeting('fixture')
        self.assertEqual(self.calls, [])

    def test_translation_is_returned_without_saving(self):
        self.results['text.translate'] = {'text': 'Bonjour'}
        self.assertEqual(features.translate_message('Hello', 'FR'), {'text': 'Bonjour'})
        self.assertEqual(self.calls[-1][1]['targetLanguage'], 'fr')
        self.doc.db_set.assert_not_called()

    def test_missing_key_is_added_to_the_visible_message_log(self):
        from education.education import billing
        with patch.object(billing, 'PramaanClient', return_value=PramaanClient(api_key='')):
            with self.assertRaises(frappe.ValidationError):
                billing.client()
        self.assertIn('Add PRAMAAN_API_KEY to .env', json.dumps(frappe.local.message_log))

    def test_document_result_is_reviewed_without_assuming_an_envelope(self):
        file_doc = Mock(file_name='form.pdf', attached_to_doctype='Student Applicant', attached_to_name='fixture')
        file_doc.get_content.return_value = b'fixture content'
        frappe.get_doc.side_effect = [self.doc, file_doc]
        self.results['document.extract'] = {'unpublished_envelope': {'first_name': 'Sample'}}
        result = features.prefill_applicant('fixture', 'file-fixture')
        self.assertEqual(result['extraction'], self.results['document.extract'])
        body = self.calls[-1][1]
        self.assertEqual(base64.b64decode(body['content']), b'fixture content')
        self.assertIn('email_address', body['schema']['properties'])
        self.assertIn('student_mobile_number', body['schema']['properties'])
        self.doc.db_set.assert_not_called()
        self.doc.save.assert_not_called()

    def test_document_must_belong_to_the_applicant(self):
        file_doc = Mock(attached_to_doctype='Student Applicant', attached_to_name='somebody-else')
        frappe.get_doc.side_effect = [self.doc, file_doc]
        with self.assertRaises(frappe.ValidationError):
            features.prefill_applicant('fixture', 'file-fixture')
        self.assertEqual(self.calls, [])

    def test_quiz_is_a_bounded_draft_without_saving(self):
        self.results['llm.complete'] = {'text': 'Draft question'}
        with patch.object(frappe.db, 'get_value', return_value='Math'):
            self.assertEqual(features.draft_quiz_questions('fixture', 100)['text'], 'Draft question')
        body = self.calls[-1][1]
        self.assertEqual(body['maxTokens'], 2560)
        self.assertIn('10 multiple-choice', body['messages'][1]['content'])
        self.doc.save.assert_not_called()

    def test_fee_reminder_uses_the_saved_link_and_real_delivery_state(self):
        self.action()
        self.results['payments.payment-link.notify'] = {'sent': False}
        self.assertFalse(features.send_fee_reminder('fixture')['sent'])
        self.assertEqual(self.calls[-1][1], {'paymentLinkId': 'link_fixture', 'channel': 'email'})
        self.doc.payment_link_id = 'ref_01ARZ3NDEKTSV4RRFFQ69G5FAV'
        features.send_fee_reminder('fixture')
        self.assertIn('ref', self.calls[-1][1])

    def test_guardian_sms_uses_only_mobile_and_deduplicates_recipients(self):
        action = self.action()
        guardians = [frappe._dict(mobile_number='+15550001111', email_address='g@example.com')]
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(student='a'), frappe._dict(student='b')]), \
             patch.object(features, '_guardians_of', return_value=guardians):
            result = features.send_guardian_alerts('batch', '2026-10-16', 'Absent today', 'sms')
        self.assertEqual(result, {'queued': 1, 'skipped': 0})
        action.assert_called_once()
        self.assertEqual(self.calls[-1][0], 'sms.send')

    def test_guardian_email_queues_instead_of_claiming_delivery(self):
        guardians = [frappe._dict(mobile_number='', email_address='g@example.com')]
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(student='a')]), \
             patch.object(features, '_guardians_of', return_value=guardians), \
             patch('education.integrations.pramaan_mail.sendmail') as sendmail:
            result = features.send_guardian_alerts('batch', '2026-10-16', '<Absent>', 'email')
        self.assertEqual(result, {'queued': 1, 'skipped': 0})
        self.assertIn('&lt;Absent&gt;', sendmail.call_args.kwargs['message'])

    def test_guardian_opt_out_is_respected(self):
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(guardian='g')]), \
             patch.object(frappe.db, 'get_value', return_value=frappe._dict(disable_school_messages=1)):
            self.assertEqual(list(features._guardians_of('student')), [])

    def test_action_saves_intent_before_effect_and_reuses_result(self):
        intent = Mock(idempotency_key='saved-key')
        self.doc.insert.return_value = intent
        self.results['sms.send'] = {'status': 'queued'}
        with patch.object(frappe, 'get_all', return_value=[]), patch.object(frappe.db, 'commit') as commit:
            def check_intent(*args, **kw):
                self.assertEqual(commit.call_count, 1)
                self.assertEqual(kw['idempotency_key'], 'saved-key')
                return {'status': 'queued'}
            with patch.object(self.fake, 'call', side_effect=check_intent):
                self.assertEqual(features._action('sms.send', {'to': '+15550001111', 'body': 'Absent'}), {'status': 'queued'})
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(state='Accepted', result='{"status":"queued"}')]):
            self.assertEqual(features._action('sms.send', {}, reuse=True), {'status': 'queued'})

    def test_uncertain_action_is_saved_and_never_repeated(self):
        intent = Mock(idempotency_key='saved-key')
        self.doc.insert.return_value = intent
        with patch.object(frappe, 'get_all', return_value=[]), patch.object(frappe.db, 'commit'), \
             patch.object(self.fake, 'call', side_effect=PramaanError(uncertain=True)):
            with self.assertRaises(PramaanError):
                features._action('sms.send', {'body': 'Absent'})
        self.assertEqual(intent.db_set.call_args.args[0]['state'], 'Uncertain')
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(state='Uncertain')]):
            with self.assertRaises(frappe.ValidationError):
                features._action('sms.send', {'body': 'Absent'})


class TestMailQueueSchema(FrappeTestCase):
    def test_delivery_field_is_created_and_safe_to_reapply(self):
        from education.install import ensure_mail_fields
        from education.integrations.pramaan_mail import deliver

        ensure_mail_fields()
        ensure_mail_fields()
        self.assertTrue(frappe.db.has_column('Email Queue', 'pramaan_outbox'))
        outbox = frappe.get_doc({
            'doctype': 'Pramaan Outbox', 'capability': 'email.send',
            'payload': '{}', 'idempotency_key': frappe.generate_hash(),
            'state': 'Pending', 'requested_by': 'Administrator',
        }).insert(ignore_permissions=True)
        fake = Mock()
        fake.call.return_value = {'status': 'queued', 'ref': 'fixture-mail'}
        with patch('education.integrations.pramaan_mail.client', return_value=fake):
            deliver(outbox.name)
            deliver(outbox.name)
        self.assertEqual(frappe.db.get_value('Pramaan Outbox', outbox.name, 'state'), 'Accepted')
        fake.call.assert_called_once()
