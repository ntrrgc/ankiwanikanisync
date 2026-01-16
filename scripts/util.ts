import * as fs from "fs/promises";

import type { Test } from "ctrf";

export function* reExec(re: RegExp, str: string): Generator<RegExpExecArray> {
    re.lastIndex = 0;

    let result;
    while ((result = re.exec(str))) {
        yield result;
    }
}

export function countLines(str: string, endIndex: number = Infinity): number {
    let i = 1;
    for (const match of reExec(/\n/g, str)) {
        if (match.index >= endIndex) {
            break;
        }
        i++;
    }
    return i;
}

const cwd = `${process.cwd()}/`;

export function relname(path: string): string {
    if (path.startsWith(cwd)) {
        return path.slice(cwd.length);
    }
    return path;
}

function reQuote(str: string): string {
    return str.replace(/[(){}[\]*/?.+\\]/g, "\\$&");
}

const fileCache: Record<string, string> = {};

async function findEndLine(file: string, res: RegExp[]): Promise<number> {
    if (!Object.hasOwn(fileCache, file)) {
        try {
            fileCache[file] = await fs.readFile(file, { encoding: "utf-8" });
        } catch (_) {
            return null;
        }
    }
    const contents = fileCache[file];

    for (const re of res) {
        re.lastIndex = 0;
        const res = re.exec(contents);
        if (res) {
            return countLines(contents, res.index + res[0].length);
        }
    }
    return null;
}

export async function findPyTestLine(test: Test): Promise<number> {
    return findEndLine(test.filePath, [
        new RegExp(String.raw`\bdef ${reQuote(test.name)}\b`),
    ]);
}

export async function findMochaTestLine(test: Test): Promise<number> {
    const suites = test.suite.slice(1);
    if (suites[0] === relname(test.filePath)) {
        suites.splice(0, 1);
    }

    return findEndLine(test.filePath, [
        new RegExp(suites.concat(test.name).map(reQuote).join(".*?")),
        new RegExp(reQuote(test.name)),
    ]);
}

export async function findTestLine(test: Test): Promise<number> {
    if (test.filePath.endsWith(".py")) {
        return findPyTestLine(test);
    }
    if (/\.m?[jt]s$/.test(test.filePath)) {
        return findMochaTestLine(test);
    }
    return null;
}
