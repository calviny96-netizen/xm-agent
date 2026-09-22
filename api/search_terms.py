"""Shared OR phrase search for cached and uncached workspace queries."""
import re
from fastapi import HTTPException


def normalize_terms(value):
    values = re.split(r'[,;\n]+', value) if isinstance(value, str) else value
    terms = list(dict.fromkeys(term.strip() for term in values if term.strip()))
    if len(terms) > 20 or any(len(term) > 200 for term in terms):
        raise HTTPException(400, 'Maksimal 20 kata/frasa pencarian, masing-masing 200 karakter.')
    return terms


def search_filter(value):
    terms = normalize_terms(value)
    if not terms:
        return '', []
    patterns = ['%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for term in terms]
    return " AND (d.normalized_text ILIKE ANY(%s) OR coalesce(d.contact_name,'') ILIKE ANY(%s))", [patterns, patterns]
