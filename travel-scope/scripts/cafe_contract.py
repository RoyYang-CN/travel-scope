"""Shared domestic/international café collection contract; no name guessing."""
import json
from pathlib import Path


def validate_cafes(payload):
    rules = json.loads((Path(__file__).parent.parent / 'references/cafe-policy.json').read_text(encoding='utf-8'))
    if not isinstance(payload.get('cafes'), list):
        raise ValueError('cafes is required: missing collection is not an empty search result')
    coverage = payload.get('cafe_coverage')
    if not isinstance(coverage, list):
        raise ValueError('cafe_coverage is required for every destination')
    destinations = {row[0] for row in payload.get('destinations', [])}
    seen = set()
    for record in coverage:
        destination = record.get('destination')
        if destination not in destinations or destination in seen:
            raise ValueError('Unknown or duplicate cafe coverage destination')
        seen.add(destination)
        if record.get('status') not in rules['completed_statuses']:
            raise ValueError('Café search is incomplete')
        if not record.get('queries') or not record.get('evidence'):
            raise ValueError('Café search requires queries and evidence, including empty results')
        count = sum(row[0] == destination for row in payload['cafes'])
        if (record['status'] == 'included') != (count > 0):
            raise ValueError('Café coverage contradicts included rows')
        if count == 0 and not record.get('reason'):
            raise ValueError('Empty café result requires a reason')
    if seen != destinations:
        raise ValueError('Missing café search coverage for destinations')
    identities = set()
    names = set()
    decisions = payload.get('cafe_classification', {})
    for kind in ('restaurants', 'cafes'):
        for row in payload.get(kind, []):
            name = row[1]
            decision = decisions.get(name, {})
            if kind == 'cafes':
                if row[0] not in destinations or len(row) < 11:
                    raise ValueError('Invalid café row')
                if decision.get('primary_role') != 'cafe' or not decision.get('evidence'):
                    raise ValueError('Café requires evidence of its primary business role')
            elif decision.get('primary_role') == 'cafe':
                raise ValueError('Verified café remains in restaurants; classify upstream')
            identity = ((row[11] if len(row) > 11 else '') if payload.get('domestic_destination')
                        else payload.get('provider_poi_ids', {}).get(name, '') or payload.get('google_place_ids', {}).get(name, ''))
            if kind == 'cafes' and not identity:
                raise ValueError('Café requires provider POI identity')
            if name in names or (identity and identity in identities):
                raise ValueError('Duplicate restaurant/café POI')
            names.add(name)
            if identity:
                identities.add(identity)

