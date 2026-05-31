"""Shared game-title metadata for wiki-style sources."""

from __future__ import annotations

from dataclasses import dataclass, field

from .parser import clean_text


@dataclass(frozen=True, slots=True)
class WikiGameProfile:
    alias: str
    game_title: str
    aliases: list[str] = field(default_factory=list)

    @property
    def tags(self) -> list[str]:
        tags = [self.alias, self.game_title, *self.aliases]
        return _dedupe([tag for tag in tags if tag])


KNOWN_WIKI_GAMES = {
    "ys": WikiGameProfile(alias="ys", game_title="原神", aliases=["Genshin Impact"]),
    "ysgl": WikiGameProfile(alias="ysgl", game_title="原神", aliases=["Genshin Impact"]),
    "sr": WikiGameProfile(alias="sr", game_title="崩坏：星穹铁道", aliases=["星穹铁道", "崩铁", "Honkai: Star Rail"]),
    "bh3": WikiGameProfile(alias="bh3", game_title="崩坏3", aliases=["崩坏三", "Honkai Impact 3rd"]),
    "blhx": WikiGameProfile(alias="blhx", game_title="碧蓝航线", aliases=["Azur Lane"]),
    "ba": WikiGameProfile(alias="ba", game_title="蔚蓝档案", aliases=["Blue Archive", "碧蓝档案"]),
    "nikke": WikiGameProfile(alias="nikke", game_title="NIKKE", aliases=["胜利女神：NIKKE"]),
}


def wiki_game_profile(alias: str, title: str = "", aliases: list[str] | None = None) -> WikiGameProfile:
    normalized_alias = clean_text(alias).strip("/")
    known = KNOWN_WIKI_GAMES.get(normalized_alias.lower())
    if known:
        return known
    game_title = _clean_game_title(title) or normalized_alias
    return WikiGameProfile(alias=normalized_alias, game_title=game_title, aliases=_dedupe(aliases or []))


def wiki_game_profile_from_config(alias: str, config: dict | None = None) -> WikiGameProfile:
    config = config or {}
    game_title = clean_text(str(config.get("wiki_game_title") or ""))
    aliases = [clean_text(str(item)) for item in config.get("wiki_game_aliases") or []]
    if game_title:
        return WikiGameProfile(alias=alias, game_title=game_title, aliases=_dedupe(aliases))
    return wiki_game_profile(alias, aliases=aliases)


def wiki_game_config(alias: str, title: str = "") -> dict:
    profile = wiki_game_profile(alias, title)
    return {
        "wiki_game_title": profile.game_title,
        "wiki_game_aliases": profile.aliases,
    }


def _clean_game_title(value: str) -> str:
    title = clean_text(value)
    for prefix in ("GameKee", "Biligame", "BWIKI", "WIKI"):
        title = title.replace(prefix, "")
    for suffix in ("官方Wiki", "官方 WIKI", "Wiki", "WIKI", "wiki"):
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return clean_text(title.strip(" -_|·:："))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean_text(str(value))
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
