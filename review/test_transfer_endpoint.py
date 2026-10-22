"""School payment authorization and accounting retry checks without a framework server."""
import ast
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_bank_transfer
from education.pramaan import PramaanError

SOURCE = Path(__file__).resolve().parents[1] / 'education/education/bank_transfer.py'
TREE = ast.parse(SOURCE.read_text())


class EndpointTests(unittest.TestCase):
    setUp = test_bank_transfer.TransferTests.setUp

    def load(self):
        from education.education.transfers import Transfer, request_body, EXPONENTS
        import hashlib
        self.doc = SimpleNamespace(name='invoice-fixture', doctype='Sales Invoice', student='student-fixture',
            outstanding_amount=10.75, currency='GBP', docstatus=1, reload=Mock(), check_permission=Mock())
        self.record = SimpleNamespace(name='local-record', bank_transfer_data='', status='Awaiting', reload=Mock())
        self.record.insert = lambda **kwargs: self.record
        self.record.db_set = lambda key, value: setattr(self.record, key, value)
        self.permission = Mock()
        self.settle = Mock()
        def get_doc(doctype, name=None):
            if isinstance(doctype, dict): return self.record
            return self.doc if doctype in {'Fees', 'Sales Invoice'} else self.record
        def fail(message, *args): raise ValueError(message)
        self.frappe = SimpleNamespace(session=SimpleNamespace(user='student-fixture'), PermissionError=ValueError,
            throw=fail, get_doc=get_doc, db=SimpleNamespace(sql=Mock(), exists=Mock(return_value=True), commit=Mock()))
        namespace = dict(frappe=self.frappe, json=json, hashlib=hashlib, client=lambda: self.client,
            get_details=lambda name: self.doc, _check_permission=self.permission, _settle=self.settle,
            Transfer=Transfer, request_body=request_body, EXPONENTS=EXPONENTS, PramaanError=PramaanError)
        fn = copy.deepcopy(next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'transfer'))
        fn.decorator_list = []
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        return namespace['transfer']

    def test_owner_check_and_paid_only_after_get(self):
        transfer = self.load()
        estimate = transfer('invoice-fixture', operation='create')
        transfer('invoice-fixture', operation='confirm', confirmation=estimate['confirmation'])
        self.settle.assert_not_called()
        self.status = 'paid'
        transfer('invoice-fixture')
        self.settle.assert_called_once()
        self.permission.assert_called()

    def test_other_student_denied_before_service_call(self):
        transfer = self.load()
        self.permission.side_effect = ValueError('Not permitted')
        with self.assertRaisesRegex(ValueError, 'Not permitted'): transfer('other-invoice', operation='create')
        self.assertFalse(self.calls)

    def test_guest_and_invalid_doctype_denied(self):
        transfer = self.load()
        with self.assertRaises(ValueError): transfer('fixture', doctype='User')
        self.frappe.session.user = 'Guest'
        with self.assertRaises(ValueError): transfer('fixture')
        self.assertFalse(self.calls)

    def test_fees_use_document_write_permission(self):
        transfer = self.load()
        transfer('fixture', doctype='Fees')
        self.doc.check_permission.assert_called_once_with('write')
        self.permission.assert_not_called()

    def test_bill_change_after_estimate_blocks_creation(self):
        transfer = self.load()
        estimate = transfer('invoice-fixture', operation='create')
        self.doc.outstanding_amount = 12
        with self.assertRaises(ValueError):
            transfer('invoice-fixture', operation='confirm', confirmation=estimate['confirmation'])
        self.assertEqual(len(self.calls), 1)
