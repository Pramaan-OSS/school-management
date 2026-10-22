"""Check that portal requests still match the local application contracts."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortalContractTests(unittest.TestCase):
    def test_public_form_uses_current_applicant_fields(self):
        import json
        schema = json.loads((ROOT / 'education/education/doctype/student_applicant/student_applicant.json').read_text())
        allowed = {field['fieldname'] for field in schema['fields']}
        form = json.loads((ROOT / 'education/education/web_form/student_applicant/student_applicant.json').read_text())
        for field in form['web_form_fields']:
            if field.get('fieldname'):
                self.assertIn(field['fieldname'], allowed)

    def test_portal_methods_exist(self):
        module = ast.parse((ROOT / 'education/education/api.py').read_text())
        methods = {node.name for node in module.body if isinstance(node, ast.FunctionDef)}
        for source in (ROOT / 'frontend/src').rglob('*'):
            if source.suffix not in {'.vue', '.js'}:
                continue
            for method in re.findall(r'education\.education\.api\.([a-z_]+)', source.read_text()):
                with self.subTest(source=str(source.relative_to(ROOT)), method=method):
                    self.assertIn(method, methods, 'Portal calls a missing server method')

    def test_literal_local_queries_use_current_fields(self):
        import json
        schemas = {}
        for source in (ROOT / 'education/education/doctype').glob('*/*.json'):
            if source.stem == source.parent.name:
                schema = json.loads(source.read_text())
                schemas[schema['name']] = {field['fieldname'] for field in schema.get('fields', [])}
        standard = {'name', 'creation', 'modified', 'modified_by', 'owner', 'docstatus', 'idx', '*', 'parent', 'parenttype', 'parentfield'}
        module = ast.parse((ROOT / 'education/education/api.py').read_text())
        for call in ast.walk(module):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in {'get_list', 'get_all'} or not call.args:
                continue
            doctype = call.args[0]
            if not isinstance(doctype, ast.Constant) or doctype.value not in schemas:
                continue
            allowed = schemas[doctype.value] | standard
            for keyword in call.keywords:
                fields = []
                if keyword.arg == 'fields' and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    fields = [field.value for field in keyword.value.elts if isinstance(field, ast.Constant)]
                if keyword.arg == 'filters' and isinstance(keyword.value, ast.Dict):
                    fields = [field.value for field in keyword.value.keys if isinstance(field, ast.Constant)]
                for field in fields:
                    if isinstance(field, str) and field.replace('_', '').isalnum():
                        with self.subTest(doctype=doctype.value, field=field, line=call.lineno):
                            self.assertIn(field, allowed)

    def test_local_link_fetches_use_existing_fields(self):
        import json
        schemas = {}
        for source in (ROOT / 'education/education/doctype').glob('*/*.json'):
            if source.stem == source.parent.name:
                schema = json.loads(source.read_text())
                schemas[schema['name']] = {field['fieldname']: field for field in schema.get('fields', [])}
        standard = {'name', 'creation', 'modified', 'modified_by', 'owner', 'docstatus', 'idx'}
        for doctype, fields in schemas.items():
            for field in fields.values():
                fetch = field.get('fetch_from')
                if not fetch:
                    continue
                self.assertNotEqual(fetch, '.', f'{doctype}.{field["fieldname"]} has an empty fetch')
                link, _, target = fetch.partition('.')
                destination = fields.get(link, {}).get('options')
                if destination in schemas:
                    with self.subTest(doctype=doctype, field=field['fieldname']):
                        self.assertIn(target, schemas[destination].keys() | standard)
