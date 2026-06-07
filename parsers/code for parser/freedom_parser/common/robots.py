"""Корректная проверка robots.txt по правилу «самого длинного совпадения».

Стандартный urllib.robotparser возвращает первое подходящее правило по порядку
строк. Это ломается на сайтах вида `Disallow: /` + `Allow: /product/`
(как carcity.kz): такой сайт ЯВНО разрешает /product/ и /category/, но наивный
парсер их блокирует. Здесь реализована Google-семантика:

  - среди всех правил (Allow/Disallow), чьи паттерны совпадают с путём,
    выигрывает правило с самым длинным паттерном;
  - при равной длине выигрывает Allow;
  - если ни одно правило не совпало — разрешено.

Поддерживаются wildcard `*` и якорь конца `$`.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit


def _compile(pattern: str) -> re.Pattern:
    """Перевести robots-паттерн (с * и $) в регулярное выражение от начала пути."""
    anchored_end = pattern.endswith("$")
    if anchored_end:
        pattern = pattern[:-1]
    out = ["^"]
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        else:
            out.append(re.escape(ch))
    if anchored_end:
        out.append("$")
    return re.compile("".join(out))


class RobotsRules:
    def __init__(self) -> None:
        # список (длина_паттерна, allow_bool, скомпилированный_regex)
        self._rules: list[tuple[int, bool, re.Pattern]] = []
        self.crawl_delay: float | None = None

    @classmethod
    def parse(cls, text: str, user_agent: str) -> "RobotsRules":
        """Собрать правила для нашего UA (или для '*', если своих нет)."""
        ua_token = user_agent.split("/", 1)[0].lower()
        groups: dict[str, list[tuple[str, str]]] = {}
        delays: dict[str, float] = {}
        current: list[str] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()
            if field == "user-agent":
                current = [value.lower()]
                groups.setdefault(value.lower(), [])
            elif field in ("allow", "disallow") and current:
                for ua in current:
                    groups.setdefault(ua, []).append((field, value))
            elif field == "crawl-delay" and current:
                try:
                    for ua in current:
                        delays[ua] = float(value)
                except ValueError:
                    pass

        # Выбор группы: точное совпадение нашего UA, иначе '*'.
        chosen = None
        for ua in groups:
            if ua and ua in ua_token:
                chosen = ua
                break
        if chosen is None:
            chosen = "*" if "*" in groups else None

        rules = cls()
        if chosen is not None:
            for field, value in groups.get(chosen, []):
                if value == "" and field == "disallow":
                    continue  # пустой Disallow = разрешить всё, не добавляем правило
                rules._rules.append((len(value), field == "allow", _compile(value)))
            rules.crawl_delay = delays.get(chosen)
        return rules

    def allowed(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        path = unquote(path)
        best_len = -1
        best_allow = True
        for length, allow, rx in self._rules:
            if rx.match(path):
                if length > best_len or (length == best_len and allow):
                    best_len = length
                    best_allow = allow
        return best_allow
