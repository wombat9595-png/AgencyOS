"""Explicit test-mode payment provider adapters. Live credentials are rejected."""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ProviderError(Exception):
    pass


def create_stripe_test_checkout(invoice, success_url, cancel_url, timeout=10):
    """Create a Stripe Checkout Session only with an sk_test_ key and synthetic invoice.

    The caller must opt in through AGENCYOS_PAYMENT_PROVIDER=stripe_test. No live key is accepted.
    """
    key=os.environ.get('AGENCYOS_STRIPE_TEST_SECRET_KEY','')
    if not key.startswith('sk_test_'):
        raise ProviderError('Stripe test mode requires an sk_test_ key. Live mode is disabled.')
    if not invoice['synthetic']:
        raise ProviderError('Stripe test checkout is limited to synthetic invoices.')
    amount=invoice['total_cents']
    if type(amount) is not int or amount<=0 or invoice['currency']!='AUD':
        raise ProviderError('Invalid AUD test invoice amount.')
    fields={
        'mode':'payment','success_url':success_url,'cancel_url':cancel_url,
        'client_reference_id':str(invoice['id']),
        'metadata[agencyos_invoice_id]':str(invoice['id']),
        'payment_intent_data[metadata][agencyos_invoice_id]':str(invoice['id']),
        'line_items[0][price_data][currency]':'aud',
        'line_items[0][price_data][unit_amount]':str(amount),
        'line_items[0][price_data][product_data][name]':invoice['invoice_number'] or 'Synthetic AgencyOS invoice',
        'line_items[0][quantity]':'1',
    }
    request=Request('https://api.stripe.com/v1/checkout/sessions',data=urlencode(fields).encode(),
                    headers={'Authorization':'Bearer '+key,'Content-Type':'application/x-www-form-urlencoded',
                             'Idempotency-Key':f"agencyos-invoice-{invoice['id']}"},method='POST')
    try:
        with urlopen(request,timeout=timeout) as response:
            result=json.loads(response.read())
    except Exception as exc:
        raise ProviderError('Stripe test checkout could not be created.') from exc
    if not result.get('id','').startswith('cs_test_') or not result.get('url','').startswith('https://checkout.stripe.com/'):
        raise ProviderError('Provider response was not a recognized Stripe test Checkout Session.')
    return dict(provider_id=result['id'],url=result['url'])
