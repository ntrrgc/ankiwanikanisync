import { $, browser } from "@wdio/globals";
import { Key } from "webdriverio";

import { assert } from "../ankiwanikanisync/data/files/_wk3_util.ts";
import tmpl from "../dist/fixtures/templates.json" with { type: "json" };
import { step } from "./util.ts";

export type Fields = Record<string, string | number | object | null>;

export type CardType = "Meaning" | "Reading";
export type NoteType = "radical" | "kanji" | "vocabulary" | "kana_vocabulary";

enum CardSide {
    Front,
    Back,
}

interface AnswerStatus {
    value: string;
    submitted: string | null;
    shook: boolean;
}

const TYPEANS_STYLE = "font-size: 20px; font-family: Arial";

const q = (str: string) => `"${str}"`;

function xpathQuote(str: string): string {
    if (!str.includes('"')) {
        return q(str);
    }

    const res: string[] = [];
    for (const [i, substr] of str.split('"').entries()) {
        if (i > 0) {
            res.push(`'"'`);
        }
        res.push(q(substr));
    }
    return `concat(${res.join(", ")})`;
}

export class Card {
    readonly TYPEANS = `<input type="text" id="typeans"
                       onkeypress="_typeAnsPress(event);"
                       style="${TYPEANS_STYLE}">`;

    #typedAns(val: string): string {
        return `<div id="input">
            <div style="${TYPEANS_STYLE}">
                <code id="typeans">${val}</code>
            </div>
        </div>`;
    }

    readonly PLAY_IMAGE = `<svg class="playImage" viewBox="0 0 64 64" version="1.1">
        <circle cx="32" cy="32" r="29"></circle>
        <path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z"></path>
    </svg>`;

    #soundLink(n: number): string {
        const qa = this.side === CardSide.Front ? "q" : "a";
        return `<a class="replay-button soundLink" href="#" onclick="pycmd('play:${qa}:${n}'); return false;" draggable="false">
            ${this.PLAY_IMAGE}
        </a>`;
    }

    answerField: string | null;

    side: CardSide = CardSide.Front;
    cardType: CardType;
    fields: Fields | null = null;

    interpolate(text: string, fields: Fields, answer?: string | null) {
        text = text.replace(/\{\{([#^])(\w+)\}\}(.*?)\{\{\/\2\}\}/sg, (...m: string[]) => {
            const fieldName = m[2];
            const pos = m[1] === "#";
            if (!!fields[fieldName] === pos) {
                return m[3];
            }
            return "";
        });

        return text.replace(/\{\{(?:(\w+):)?(\w+)\}\}/g, (...m: string[]) => {
            const val = fields[m[2]];
            if (m[1] === "type") {
                this.answerField = m[2];
                if (this.side === CardSide.Front) {
                    return this.TYPEANS;
                }
                if (answer != null) {
                    const class_ = answer === val ? "typeGood" : "typeBad";
                    return this.#typedAns(`<span class="${class_}">${answer}</span>`);
                }
                return this.#typedAns(val as string);
            }
            if (typeof val === "object") {
                return JSON.stringify(val);
            }
            let i = 0;
            return String(val).replace(/\[sound:.*?\]/g, () => this.#soundLink(++i));
        });
    }

    async #load(html: string, fields: Fields, answer?: string | null) {
        html = this.interpolate(html, fields, answer);

        const side = this.side === CardSide.Back ? "Back" : "Front";
        const event = `WK3${side}SetupComplete`;

        await browser.execute(async (c, e) => {
            const promise = new Promise(resolve => {
                document.body.addEventListener(e, resolve, { once: true });
            });

            const frag = document.createRange().createContextualFragment(c);

            const card = document.querySelector("#qa");
            card.textContent = "";
            card.appendChild(frag);

            await promise;

            await document.fonts.ready;
        }, html, event);

        await browser.scroll(0, 0);
    }

    async init() {
        await browser.execute(css => {
            document.querySelector(".card").insertAdjacentHTML("beforebegin", `<style>${css}</style>`);
        }, tmpl["css"]);
    }

    async getTypedAns(): Promise<string> {
        assert(this.side === CardSide.Front);
        assert(this.answerField != null);
        return $("#typeans").getValue();
    }

    async checkAnswer(): Promise<AnswerStatus> {
        assert(this.side === CardSide.Front);
        assert(this.answerField != null);

        return browser.execute(async () => {
            const input = document.querySelector<HTMLInputElement>("#typeans");

            if (input.classList.contains("shake")) {
                await new Promise(resolve => {
                    input.addEventListener("animationend", resolve, { once: true });
                });
            }

            const res = {
                value: input.value,
                submitted: input.dataset.submitted,
                shook: input.dataset.shook === "true",
            };
            delete input.dataset.submitted;
            delete input.dataset.shook;
            return res;
        });
    }

    @step("Type Answer")
    async typeAnswer(val: string): Promise<AnswerStatus> {
        assert(this.side === CardSide.Front);
        assert(this.answerField != null);

        const input = $("#typeans");
        await input.setValue("");
        await input.click();
        await browser.keys([...val, Key.Enter]);

        return this.checkAnswer();
    }

    async setNightMode(enable: boolean): Promise<void> {
        await browser.execute(enable => {
            document.body.classList[enable ? "add" : "remove"]("nightMode");
        }, enable);
        await browser.emulate("colorScheme", enable ? "dark" : "light");
    }

    async setMobile(enable: boolean): Promise<void> {
        await browser.execute(enable => {
            document.body.classList[enable ? "add" : "remove"]("mobile");
        }, enable);
    }

    async getHeadings(): Promise<string[]> {
        assert(this.side === CardSide.Back);

        return browser.execute(() => {
            return Array.from(document.querySelectorAll("summary.heading"))
                .filter(h => h.checkVisibility())
                .map(h => h.textContent.trim());
        });
    }

    @step("Open Sections")
    async openSections(sel: string) {
        await browser.execute(sel => {
            for (const elem of document.querySelectorAll(sel)) {
                elem.setAttribute("open", "");
            }
        }, sel);
    }

    @step("Open Section")
    async openSection(sel: string) {
        await browser.execute(sel => {
            const elem = document.querySelector(sel);
            elem.setAttribute("open", "");
            elem.scrollIntoView();
        }, sel);
    }

    @step("Open Named Section")
    async openNamedSection(name: string) {
        await this.openSection(`//summary[normalize-space() = ${xpathQuote(name)}]/ancestor::details[1]`);
    }

    @step("Show Card Front")
    async showFront(cardType: CardType, fields: Fields) {
        this.answerField = null;
        this.side = CardSide.Front;
        this.cardType = cardType;
        this.fields = {
            ...fields,
            Card: cardType,
        };

        await this.#load(tmpl.cards[cardType]["qfmt"], this.fields);
    }

    @step("Show Card Back")
    async showBack() {
        assert(this.side === CardSide.Front);
        assert(this.fields);

        let answer = null;
        if (this.answerField) {
            answer = await this.getTypedAns();
        }

        this.side = CardSide.Back;

        const tmpls = tmpl.cards[this.cardType];
        const fields: Fields = {
            ...this.fields,
            FrontSide: this.interpolate(tmpls["qfmt"], this.fields, answer),
        };

        await this.#load(tmpls["afmt"], fields);
    }
}

export const card = new Card();
