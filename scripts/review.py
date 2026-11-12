"""Interactive local review; no Outlook or payment writes."""
import json
from pathlib import Path
import httpx


if __name__=='__main__':
    root=Path(__file__).resolve().parent.parent
    token=next(line.split('=',1)[1] for line in (root/'.env').read_text().splitlines() if line.startswith('API_TOKEN='))
    with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,
                      headers={'Authorization':'Bearer '+token},timeout=30) as client:
        response=client.get('/monitor');response.raise_for_status()
        findings=response.json()['findings']
        if not findings: print('No high-value possible-overdue candidates currently require review.')
        for finding in findings:
            print('\nPOSSIBLE overdue — review source and your ledger before action.')
            print(f"{finding['vendor']}: {finding['currency']} {finding['amount']}; due {finding['due_date']}; reference {finding['reference']}")
            print('Outlook source:',finding['web_link'] or 'See source-evidence dashboard')
            print('Related payment evidence:',finding['related_payment_evidence'])
            choice=input('Skip [s], mark human-confirmed paid [p], dismiss [d], quit [q]: ').strip().lower()
            if choice=='q': break
            if choice not in ('p','d'): continue
            note=input('Reason (at least five characters): ').strip()
            if len(note)<5: print('No change saved: reason too short.');continue
            response=client.post('/review/'+finding['transaction_key'],json={'status':'paid' if choice=='p' else 'dismissed','note':note})
            response.raise_for_status();print('Local review saved. Outlook was not modified.')
