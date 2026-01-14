import { expect } from "expect";
import { describe, it } from "mocha";

import { assert, assertNever, chunked, deepFreeze, escapeHTML, likelyTypo, split, zip } from "../ankiwanikanisync/data/files/_wk3_util.ts";

describe("_wk3_util.ts", () => {
    describe("assert()", () => {
        it("Should throw with the correct message on failure", () => {
            expect(() => assert(false, "msg")).toThrow(new Error("msg"));
        });

        it("Should throw on failure when no message provided", () => {
            expect(() => assert(false)).toThrow(new Error());
        });

        it("Should not throw on success", () => {
            assert(true);
        });
    });

    describe("assertNever()", () => {
        it("Should throw the correct message when passed", () => {
            expect(() => assertNever("msg")).toThrow(new Error("msg"));
        });

        it("Should throw when no message passed", () => {
            expect(() => assertNever()).toThrow(new Error());
        });
    });

    describe("split()", () => {
        it("Should drop surrounding white space when no pattern passed", () => {
            expect(split("  foo  bar  ")).toEqual(["foo", "bar"]);
        });

        it("Should return an empty list when an empty string is passed", () => {
            expect(split("")).toEqual([]);
        });

        it("Should not strip empty fields when a pattern is passed", () => {
            expect(split("  foo  bar  ", /\s+/g)).toEqual(["", "foo", "bar", ""]);
        });
    });

    describe("chunked()", () => {
        it("Should correctly split an array", () => {
            expect(Array.from(chunked([1, 2, 3, 4], 2))).toEqual([[1, 2], [3, 4]]);
        });
    });

    describe("zip()", () => {
        it("Should correctly zip two arrays", () => {
            expect(Array.from(zip([1, 2], [3, 4]))).toEqual([[1, 3], [2, 4]]);
        });

        it("Should correctly zip three arrays", () => {
            expect(Array.from(zip([1, 2], [3, 4], [5, 6]))).toEqual([[1, 3, 5], [2, 4, 6]]);
        });
    });

    describe("escapeHTML()", () => {
        it("Should correctly escape HTML", () => {
            expect(escapeHTML(`<a href="&amp;"></a>`)).toEqual(`&lt;a href="&amp;amp;"&gt;&lt;/a&gt;`);
        });
    });

    describe("likelyTypo()", () => {
        it("Should should return true for exact matches", () => {
            const str = "abcdefghjklmnop";
            for (let i = 0; i < str.length; i++) {
                const substr = str.substring(0, i);
                expect(likelyTypo(substr, substr)).toBe(true);
            }
        });

        it("Should only accept exact matches for 0-length strings", () => {
            expect(likelyTypo("", "a")).toBe(false);
        });

        it("Should only accept exact matches for 1-length strings", () => {
            expect(likelyTypo("a", "ab")).toBe(false);
        });

        it("Should accept 1 edit for 2-length strings", () => {
            expect(likelyTypo("ab", "aa")).toBe(true);
            expect(likelyTypo("ab", "ba")).toBe(false);
        });

        it("Should accept 1 edit for 3-length strings", () => {
            expect(likelyTypo("aab", "aaa")).toBe(true);
            expect(likelyTypo("aab", "aba")).toBe(false);
        });

        it("Should accept 2 edits for 4-length strings", () => {
            expect(likelyTypo("aaaa", "aabb")).toBe(true);
            expect(likelyTypo("aaaa", "abb")).toBe(false);
        });
    });

    describe("deepFreeze()", () => {
        it("Should return the same object", () => {
            const obj = {
                a: { b: ["c"] },
            };
            expect(deepFreeze(obj)).toBe(obj);
        });

        it("Should make objects deep readonly", () => {
            const obj = {
                a: { b: ["c"] },
            };
            deepFreeze(obj);
            expect(Object.getOwnPropertyDescriptor(obj.a.b, 0).writable).toBe(false);
        });
    });
});
