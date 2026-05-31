from __future__ import annotations

from pathlib import Path

from erfairy.domain_terms import enrich_document, load_domain_terms
from erfairy.models import SearchDocument


def test_load_domain_terms_reads_aliases_example():
    terms = load_domain_terms(Path(__file__).parent.parent / "aliases.example.json")

    canonical_names = {entity.canonical for entity in terms.entities}
    assert "雷电将军" in canonical_names
    assert "最新" in terms.news_intent_terms


def test_enrich_document_adds_aliases_and_character_fields():
    terms = load_domain_terms(Path(__file__).parent.parent / "aliases.example.json")
    document = SearchDocument(
        id=1,
        url="local://raiden-news",
        title="原神 雷神 活动资讯",
        content="雷神将在活动剧情中登场。",
        category="news",
    )

    enriched = enrich_document(document, terms)

    assert "雷电将军" in enriched.aliases
    assert "Raiden Shogun" in enriched.aliases
    assert enriched.entity_type == "character"
    assert enriched.game_title == "原神"
    assert enriched.character_name == "雷电将军"


def test_enrich_document_keeps_explicit_parser_fields():
    terms = load_domain_terms(Path(__file__).parent.parent / "aliases.example.json")
    document = SearchDocument(
        id=1,
        url="local://fgo",
        title="明日方舟 联动新闻",
        content="方舟相关资讯。",
        entity_type="news",
        game_title="FGO",
        character_name="玛修",
    )

    enriched = enrich_document(document, terms)

    assert enriched.entity_type == "news"
    assert enriched.game_title == "FGO"
    assert enriched.character_name == "玛修"


def test_enrich_document_does_not_match_single_character_alias_as_substring():
    terms = load_domain_terms(Path(__file__).parent.parent / "aliases.example.json")
    document = SearchDocument(
        id=1,
        url="local://your-name",
        title="你的名字 新海诚动画电影",
        content="这是一部动画电影，不是原神角色资料。",
        tags=["动画电影", "新海诚"],
        aliases=["你的名字"],
    )

    enriched = enrich_document(document, terms)

    assert "雷电将军" not in enriched.aliases
    assert enriched.game_title == ""
    assert enriched.character_name == ""
