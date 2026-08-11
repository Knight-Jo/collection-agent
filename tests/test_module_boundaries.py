"""Public API compatibility tests for refactored module boundaries."""

import intel_agent.document_extract as document_extract
import intel_agent.fetch as fetch
import intel_agent.search as search
import intel_agent.search_queries as search_queries


def test_search_reexports_query_helpers():
    assert search.GENERIC_TERMS is search_queries.GENERIC_TERMS
    assert search.STOP_WORDS is search_queries.STOP_WORDS
    assert search.tokenize_query is search_queries.tokenize_query
    assert search.is_broad_query is search_queries.is_broad_query
    assert search.query_similarity is search_queries.query_similarity
    assert search.is_semantic_duplicate is search_queries.is_semantic_duplicate
    assert (
        search.authoritative_variants is search_queries.authoritative_variants
    )
    assert search.industry_terms is search_queries.industry_terms
    assert search.extract_keywords is search_queries.extract_keywords
    assert search.build_query_variants is search_queries.build_query_variants


def test_fetch_reexports_document_extractors():
    assert fetch.decode_body is document_extract.decode_body
    assert fetch.publication_date is document_extract.publication_date
    assert fetch.extract_html is document_extract.extract_html
    assert (
        fetch.extract_outbound_links is document_extract.extract_outbound_links
    )
    assert fetch.extract_pdf_text is document_extract.extract_pdf_text
    assert fetch.extract_docx_text is document_extract.extract_docx_text
