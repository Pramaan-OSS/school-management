"""Run inside a disposable fake-only school stack: python /app/review/check_bank_transfer_framework.py.
Creates synthetic records only; all service calls use the real client's fake transport.
"""
import os
if os.environ.get("PRAMAAN_FAKE") != "1":
    raise SystemExit("Run this check only in a disposable fake-only stack.")
from unittest.mock import Mock, patch
os.chdir('/app/.runtime/bench/sites')
import frappe
from education.pramaan import PramaanClient
from education.education import bank_transfer
from frappe.app import application
from werkzeug.test import Client
from werkzeug.wrappers import Response

site = os.environ['SCHOOL_SITE_NAME']
frappe.init(site=site); frappe.connect(); frappe.set_user('Administrator')
user = 'transfer-fixture@school.test'
if not frappe.db.exists('User', user):
    frappe.get_doc({'doctype':'User', 'email':user, 'first_name':'Transfer Fixture',
        'new_password':'fixture-local-only', 'send_welcome_email':0,
        'roles':[{'role':'Student'}]}).insert(ignore_permissions=True)
if not frappe.db.exists('Student','TRANSFER-STUDENT'):
    frappe.get_doc({'doctype':'Student','name':'TRANSFER-STUDENT','first_name':'Transfer',
        'student_name':'Transfer Fixture','student_email_id':user,'user':user}).db_insert()
for dt, name in [('Sales Invoice','TRANSFER-INVOICE'), ('Sales Invoice','TRANSFER-NOT-CONNECTED'), ('Fees','TRANSFER-FEE')]:
    if not frappe.db.exists(dt,name):
        frappe.get_doc({'doctype':dt,'name':name,'student':'TRANSFER-STUDENT', 'docstatus':1,
            'currency':'GBP','grand_total':10.75,'outstanding_amount':10.75,'status':'Unpaid',
            'posting_date':'2026-10-19','due_date':'2026-11-19'}).db_insert()
# Clear only this check's synthetic transfer records so the check can be rerun.
for name in frappe.get_all('Payment Record', filters={'transfer_document':['in',['TRANSFER-INVOICE','TRANSFER-NOT-CONNECTED','TRANSFER-FEE']]}, pluck='name'):
    frappe.delete_doc('Payment Record',name,ignore_permissions=True,force=True)
frappe.db.commit(); frappe.destroy()

calls=[]
connected=True
states={}
def transport(method,url,headers,body):
    global connected
    calls.append((url,headers,body))
    if url.endswith('/estimate'):
        return 200, {'can_run':connected,'reason':'connection_required' if not connected else None}
    if url.endswith('.create'):
        ref='fixture-'+str(len(states))
        states[ref]='awaiting_payment'
        return 200, {'ref':ref,'status':'awaiting_payment','amount':1075,'currency':'GBP',
            'reference':'QUOTE-THIS','bank':{'sortCode':'000000','accountNumber':'00000000'}}
    if url.endswith('.cancel'): states[body['ref']]='cancelled'
    if url.endswith('.list'):
        return 200, {'results':[{'ref':ref,'status':status,'amount':1075,'currency':'GBP'} for ref,status in states.items()]}
    status=states[body['ref']]
    return 200, {'status':status,'amount':1075,'currency':'GBP','amountReceived':1075 if status=='paid' else 0}

fake=PramaanClient(api_key='fixture-only',transport=transport)
c=Client(application,Response)
base='http://'+site
path='/api/method/education.education.bank_transfer.transfer'
def request(name,operation='status',doctype='Sales Invoice',**extra):
    r=c.post(path,base_url=base,data=dict(docname=name,operation=operation,doctype=doctype,**extra))
    assert r.status_code==200, (r.status_code,r.get_data(as_text=True))
    return r.get_json()['message']

with patch.object(bank_transfer,'client',return_value=fake):
    guest=c.post(path,base_url=base,data={'docname':'TRANSFER-INVOICE'})
    assert guest.status_code in {401,403}
    assert c.post('/api/method/login',base_url=base,data={'usr':user,'pwd':'fixture-local-only'}).status_code==200
    assert request('TRANSFER-INVOICE')['status']=='not_created'
    estimate=request('TRANSFER-INVOICE','create')
    assert not any(url.endswith('.create') for url,_,_ in calls)
    result=request('TRANSFER-INVOICE','confirm',confirmation=estimate['confirmation'])
    assert result['status']=='awaiting_payment' and result['reference']=='QUOTE-THIS'
    assert request('TRANSFER-INVOICE','list')[0]['status']=='awaiting_payment'
    states['fixture-0']='paid'
    entry=Mock()
    with patch('erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry',return_value=entry) as make_entry:
        assert request('TRANSFER-INVOICE')['status']=='paid'
        assert request('TRANSFER-INVOICE')['status']=='paid'
        entry.submit.assert_called_once()
        assert make_entry.call_args.kwargs['party_amount']==10.75
    # A payer cannot start a transfer on another student's bill.
    denied=c.post(path,base_url=base,data={'docname':'TRANSFER-FEE','doctype':'Fees','operation':'create'})
    assert denied.status_code==403
    c.post('/api/method/logout',base_url=base)
    assert c.post('/api/method/login',base_url=base,data={'usr':'Administrator','pwd':'fixture-local-only'}).status_code==200
    estimate=request('TRANSFER-FEE','create','Fees')
    assert request('TRANSFER-FEE','confirm','Fees',confirmation=estimate['confirmation'])['status']=='awaiting_payment'
    estimate=request('TRANSFER-FEE','cancel','Fees')
    assert request('TRANSFER-FEE','confirm','Fees',confirmation=estimate['confirmation'])['status']=='cancelled'
    connected=False
    rejected=c.post(path,base_url=base,data={'docname':'TRANSFER-NOT-CONNECTED','operation':'create'})
    assert rejected.status_code>=400
    assert 'Connect your payments account' in rejected.get_data(as_text=True)
print('PASS: real HTTP routes, guest/fee permission denial, create approval, bank details, awaiting/paid, one accounting submission, cancel, list and not-connected; fake service only.')
