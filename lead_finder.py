"""CSV validation and conservative duplicate hints; no network research."""
import csv
import io
import re
from urllib.parse import urlsplit

STATUSES = ('New', 'Contacted', 'Interested', 'Client', 'Not a fit')
FIELDS = ('business_name', 'contact_name', 'email', 'website', 'industry', 'location', 'source', 'notes', 'status')

def validate_lead(values):
    row = {key: str(values.get(key, '') or '').strip() for key in FIELDS}
    row['status'] = row['status'] or 'New'
    errors = []
    for key, value in row.items():
        if len(value) > (4000 if key == 'notes' else 254):
            errors.append(f'{key}: value too long')
        if any(ord(c) < 32 for c in value) and key != 'notes':
            errors.append(f'{key}: control characters are not allowed')
    if not row['business_name']:
        errors.append('Business name is required')
    if row['email'] and not re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', row['email']):
        errors.append('Invalid email')
    if row['website']:
        try:
            url = urlsplit(row['website'])
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or any(c.isspace() for c in row['website']):
                raise ValueError()
            url.port
        except ValueError:
            errors.append('Website must be a valid http:// or https:// URL without credentials')
    if row['status'] not in STATUSES:
        errors.append('Invalid lead status')
    return row, errors

def duplicate_reasons(row, other):
    reasons = []
    norm = lambda value: re.sub(r'\W+', '', (value or '').casefold())
    if norm(row['business_name']) == norm(other['business_name']):
        reasons.append('business name')
    if row['email'] and row['email'].casefold() == (other['email'] or '').casefold():
        reasons.append('email')
    def host(value):
        try:
            return (urlsplit(value or '').hostname or '').casefold().removeprefix('www.')
        except ValueError:
            return ''
    if host(row['website']) and host(row['website']) == host(other['website']):
        reasons.append('website domain')
    return reasons

def parse_csv(data, source, existing):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Save the CSV as UTF-8 and upload it again.') from exc
    reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
    try:
        headers = reader.fieldnames
        if not headers:
            raise ValueError('The CSV is empty.')
        headers = [h.strip().lower().replace(' ', '_') for h in headers]
        if len(set(headers)) != len(headers) or 'business_name' not in headers or any(h not in FIELDS for h in headers):
            raise ValueError('Use unique supported column names, including business_name. Download the sample CSV.')
        reader.fieldnames = headers
        rows, previous = [], []
        for number, values in enumerate(reader, 1):
            if number > 1000:
                raise ValueError('A CSV may contain at most 1,000 leads.')
            malformed = None in values or any(v is None for v in values.values())
            clean, errors = validate_lead(values)
            clean['source'] = clean['source'] or source
            if malformed:
                errors.append('Row has a different number of columns than the header')
            hints = []
            if not errors:
                for other in existing:
                    reasons = duplicate_reasons(clean, other)
                    if reasons:
                        hints.append(f"Existing lead #{other['id']}: {', '.join(reasons)}")
                for previous_number, other in previous:
                    reasons = duplicate_reasons(clean, other)
                    if reasons:
                        hints.append(f"CSV row {previous_number}: {', '.join(reasons)}")
                previous.append((number, clean))
            rows.append(dict(number=number, data=clean, errors=errors, duplicates=hints))
        if not rows:
            raise ValueError('The CSV contains no lead rows.')
        return rows
    except csv.Error as exc:
        raise ValueError('Malformed CSV. Check quoting and delimiters.') from exc
