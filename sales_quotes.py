"""AUD quote arithmetic and owner-attested acceptance. Never issues invoices or charges."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from phase3_store import WorkflowError, stamp
from sales_store import dumps, digest, log


def money_input(value):
    try:
        amount=Decimal(value)
        if not amount.is_finite() or amount<0 or amount>Decimal('1000000') or amount!=amount.quantize(Decimal('.01')):
            raise ValueError()
        return int(amount*100)
    except (InvalidOperation,ValueError,TypeError):
        raise WorkflowError('Enter an AUD amount from 0 to 1,000,000 with at most two decimal places.') from None


def calculate(packages,gst_mode,requirements,source,proposal):
    if gst_mode not in ('not_registered','registered_10'):
        raise WorkflowError('Explicitly configure GST registration/treatment before generating quotes.')
    lines=[]
    totals={cycle:dict(subtotal_cents=0,gst_cents=0,total_cents=0) for cycle in ('one-off','monthly')}
    for package in packages:
        qty=package.get('quantity',1)
        if type(qty) is not int or not 1<=qty<=100 or type(package['price_cents']) is not int or package['price_cents']<0 or package['cycle'] not in totals:
            raise WorkflowError('Invalid package quantity, price or billing period.')
        subtotal=package['price_cents']*qty
        tax=int((Decimal(subtotal)/10).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if gst_mode=='registered_10' else 0
        lines.append(dict(package_id=package['id'],package_version=package['version'],description=package['name'],quantity=qty,
                          unit_cents=package['price_cents'],subtotal_cents=subtotal,gst_cents=tax,total_cents=subtotal+tax,
                          cycle=package['cycle'],scope=package['scope'],exclusions=package['exclusions']))
        total=totals[package['cycle']]
        for key,value in (('subtotal_cents',subtotal),('gst_cents',tax),('total_cents',subtotal+tax)):
            total[key]+=value
    return dict(currency='AUD',gst_mode=gst_mode,pricing='Package prices exclude GST where registered; GST rounded per line, half up.',
                items=lines,totals=totals,requirements=requirements,requirements_source=source,proposal=proposal,
                limitation='Draft quote, not an invoice, payment record or customer agreement. Monthly totals are recurring and not added to one-off totals.')


def render_quote(content,version):
    lines=[f'Draft website quote — version {version}','Currency: AUD','GST treatment: '+content['gst_mode'],'']
    for item in content['items']:
        lines += [f'{item["quantity"]} × {item["description"]} ({item["cycle"]}): AUD {item["total_cents"]/100:.2f}',
                  f'GST component: AUD {item["gst_cents"]/100:.2f}', 'Scope: '+item['scope'],'Exclusions: '+item['exclusions'],'']
    for cycle,total in content['totals'].items():
        lines += [f'{cycle} total: AUD {total["total_cents"]/100:.2f} (GST AUD {total["gst_cents"]/100:.2f})']
    lines += ['', 'Requirements: '+content['requirements'],'',
              'One-off and monthly amounts are separate. Subject to your review and acceptance; no payment has been taken.']
    return '\n'.join(lines)


def brief_view(conn,record):
    """Enrich legacy v1 briefs on read without rewriting saved customer evidence."""
    result=dict(record)
    brief=json.loads(record['brief_json'])
    if 'acceptance' not in brief:
        row=conn.execute('SELECT * FROM p5_acceptances WHERE id=?',(record['acceptance_id'],)).fetchone()
        if not row or row['quote_hash']!=brief['quote_hash'] or row['quote_id']!=brief['quote_id']:
            raise WorkflowError('Project brief acceptance linkage is inconsistent; owner review required.')
        brief['stored_schema_version']=brief['schema_version']
        brief['schema_version']=2
        brief['acceptance']=dict(row)
        result['brief_json']=dumps(brief)
    return result


def accept(conn,flow,quote,customer,evidence,evidence_source,expected_hash):
    if conn.execute('SELECT 1 FROM p5_acceptances a JOIN p5_quotes q ON q.id=a.quote_id WHERE q.flow_id=?',(flow['id'],)).fetchone():
        raise WorkflowError('This opportunity already has accepted scope and a project. New scope needs a new opportunity.')
    latest=conn.execute('SELECT MAX(version) FROM p5_quotes WHERE flow_id=?',(flow['id'],)).fetchone()[0]
    if quote['version']!=latest or quote['content_hash']!=expected_hash or quote['status']!='Approved':
        raise WorkflowError('Only the current owner-approved exact quote version can have acceptance recorded.')
    if any(not isinstance(v,str) or not v.strip() or len(v)>4000 for v in (customer,evidence,evidence_source)):
        raise WorkflowError('Provide customer identity, actual acceptance evidence and its source. AI cannot supply acceptance.')
    if conn.execute('SELECT 1 FROM p5_acceptances WHERE quote_id=?',(quote['id'],)).fetchone():
        raise WorkflowError('Acceptance already recorded; no duplicate project will be created.')
    acceptance_id=conn.execute('''INSERT INTO p5_acceptances(quote_id,quote_hash,customer_name,evidence,evidence_source,recorded_at)
      VALUES(?,?,?,?,?,?)''',(quote['id'],quote['content_hash'],customer.strip(),evidence.strip(),evidence_source.strip(),stamp())).lastrowid
    snapshot=json.loads(flow['snapshot_json'])
    accepted=json.loads(quote['content_json'])
    project=conn.execute('INSERT INTO projects(client_name,project_name,status,notes,created_at) VALUES(?,?,?,?,?)',
                         (snapshot['lead']['business_name'],'Website project from Phase 5 quote #'+str(quote['id']),'Planning',
                          'Owner-attested customer acceptance #'+str(acceptance_id)+'. See Phase 5 brief; not independently verified.',stamp())).lastrowid
    acceptance=dict(conn.execute('SELECT * FROM p5_acceptances WHERE id=?',(acceptance_id,)).fetchone())
    brief=dict(schema_version=2,flow_id=flow['id'],lead_id=flow['lead_id'],customer_name=customer,
               requirements=accepted['requirements'],requirements_source=accepted['requirements_source'],branding_references=accepted.get('branding',''),
               quote_id=quote['id'],quote_version=quote['version'],quote_hash=quote['content_hash'],quote=json.loads(quote['content_json']),
               acceptance_id=acceptance_id,acceptance=acceptance,acceptance_provenance='Owner-attested; not independently verified',project_id=project,
               website_generation_authorised=False,publication_authorised=False)
    conn.execute('INSERT INTO p5_project_briefs(acceptance_id,project_id,brief_json) VALUES(?,?,?)',(acceptance_id,project,dumps(brief)))
    conn.execute("UPDATE p5_quotes SET status='Owner-attested acceptance' WHERE id=?",(quote['id'],))
    conn.execute("UPDATE p5_flows SET state='Project brief ready' WHERE id=?",(flow['id'],))
    # Legacy quote stays Draft/owner-managed: never treat its editable status as evidence.
    log(conn,flow['user_id'],'Owner attested customer acceptance for quote #'+str(quote['id'])+'; created project brief once. No payment or independent verification.',flow['id'])
    return project
