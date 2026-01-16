import { card } from "./card.ts";
import type { CardType } from "./card.ts";
import { matchElementSnapshot } from "./util.ts";
import imp from "../dist/fixtures/tests.test_importer.test_import_fields.json" with { type: "json" };
import keisei from "../dist/fixtures/tests.test_importer.test_import_keisei.json" with { type: "json" };

const notes = [
    keisei.kanji.字,
    keisei.kanji.歌,
    keisei.kanji.了,
    keisei.kanji.頁,
    keisei.radical.酉,
    keisei.radical.一,
    imp.radical.大,
    imp.radical.口,
    imp.kanji.美,
    imp.kanji.右,
    imp.kanji.入,
    imp.kanji.人,
];

for (const cardType of ["Meaning", "Reading"] satisfies CardType[]) {
    describe(`Keisei elements in ${cardType} cards`, () => {
        for (const note of notes) {
            const char = note["Characters"];
            if (cardType === "Meaning" || note["Card_Type"] !== "Radical") {
                describe(`Character ${char}`, function () {
                    this.retries(4);

                    before(async () => {
                        await card.showFront(cardType, note);
                        await card.showBack();

                        await card.openSection("#section-phonetic-details");
                    });
                    it("Should have the correct visual", async function () {
                        if (note["Card_Type"] === "Radical") {
                            // The framework does not capture these screenshots
                            // correctly, for some reason.
                            this.skip();
                        }
                        await matchElementSnapshot($("#phonetic-semantic-description"), `keisei-explanation-${char}-${cardType}`);
                        if (await $("#phonetic-semantic-container").getSize("height") > 0) {
                            await matchElementSnapshot($("#phonetic-semantic-container"), `keisei-components-${char}-${cardType}`);
                        }
                    });
                });
            }
        }
    });
}
