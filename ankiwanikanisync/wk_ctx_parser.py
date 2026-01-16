from __future__ import annotations

from collections import OrderedDict
from html.parser import HTMLParser
from typing import NamedTuple

type Attrs = list[tuple[str, str | None]]


class Collo(NamedTuple):
    ja: str
    en: str


class WKContextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_context = 0
        self.await_pattern: str | None = None
        self.await_collo: str | None = None
        self.await_collo_text: str | None = None
        self.cur_ja: str | None = None
        self.cur_en: str | None = None

        self.patterns = OrderedDict[str, str]()
        self.collos = dict[str, list[Collo]]()

    def get_attr(self, attrs: Attrs, attr: str) -> str | None:
        for a in attrs:
            if a[0] == attr:
                return a[1]
        return None

    def handle_starttag(self, tag: str, attrs: Attrs) -> None:
        classes = (self.get_attr(attrs, "class") or "").split()
        if tag == "section" and (
            self.in_context or "subject-section--context" in classes
        ):
            self.in_context += 1
            return
        if not self.in_context:
            return

        if "subject-collocations__pattern-name" in classes:
            self.await_pattern = self.get_attr(attrs, "aria-controls")
        elif "subject-collocations__pattern-collocation" in classes:
            self.await_collo = self.get_attr(attrs, "id")
        elif self.await_collo and "wk-text" in classes:
            self.await_collo_text = self.get_attr(attrs, "lang") or "en"

    def handle_endtag(self, tag: str) -> None:
        if self.in_context and tag == "section":
            self.in_context -= 1

    def handle_data(self, data: str) -> None:
        if self.await_pattern:
            self.patterns[self.await_pattern] = data
            self.collos[self.await_pattern] = []
            self.await_pattern = None
        elif self.await_collo and self.await_collo_text:
            if self.await_collo_text == "en":
                self.cur_en = data
            else:
                self.cur_ja = data
            if self.cur_en and self.cur_ja:
                self.collos[self.await_collo].append(Collo(self.cur_ja, self.cur_en))
                self.cur_ja = None
                self.cur_en = None
            self.await_collo_text = None
