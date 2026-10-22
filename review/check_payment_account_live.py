"""Opt-in signed-in browser check against the running local payments stack.

Uses the browser's real page requests; never reads or prints session credentials.
Run only with owner permission for live payments calls. No account changes are made.
"""
import json
import os
import subprocess

SESSION = 'school-payments-route-check'
BASE = os.environ.get('PAYMENTS_CHECK_URL', 'http://127.0.0.1:18176')


def browser(*args):
    result = subprocess.run(
        ['agent-browser', '--session', SESSION, '--idle-timeout', '0', *args],
        capture_output=True, text=True, check=True)
    return result.stdout


try:
    browser('open', BASE + '/login')
    login = browser('eval', '''fetch('/api/method/login', {
      method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({usr:'Administrator',pwd:'fixture-local-only'})
    }).then(r=>r.status)''')
    assert login.strip() == '200', 'Administrator login failed'
    for attempt in range(3):
        browser('open', BASE + '/student-portal/payments-account')
        browser('wait', '--fn', "document.querySelector('.payment-account') && performance.getEntriesByType('resource').some(x=>x.name.endsWith('payment_account.session'))")
        result = json.loads(browser('eval', '''JSON.stringify({path:location.pathname,
          panel:!!document.querySelector('.payment-account'),
          calls:performance.getEntriesByType('resource')
            .filter(x=>x.name.includes('payment_account.'))
            .map(x=>({method:x.name.split('.').at(-1),status:x.responseStatus}))})'''))
        if isinstance(result, str):
            result = json.loads(result)
        assert result['path'] == '/student-portal/payments-account', 'Administrator redirected away'
        assert result['panel'], 'Payments panel did not mount'
        for method in ('status', 'session'):
            assert any(x['method'] == method and x['status'] == 200 for x in result['calls']), method + ' failed'
    print('PASS: Administrator stayed on Payments account on three visits; status and session returned 200')
finally:
    browser('close')
