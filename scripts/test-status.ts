#!/usr/bin/env node
import * as fs from "fs/promises";

import { mergeReports, organizeTestsBySuite } from "ctrf";
import type { Report, Summary, Test, TestStatus, TreeNode } from "ctrf";
import { glob } from "glob";

import { findTestLine, relname } from "./util.ts";

const REPO = process.env.GITHUB_REPOSITORY ?? "kmaglione/ankiwanikanisync";
const REF = process.env.GITHUB_REF ?? "refs/heads/master";
const REF_NAME = process.env.GITHUB_REF_NAME ?? "master";
const GITHUB_URL = process.env.GITHUB_SERVER_URL ?? "https://github.com";

const BASE_URL = `${GITHUB_URL}/${REPO}/blob/${REF_NAME}`;
const ICON_BASE = `https://raw.githubusercontent.com/${REPO}/${REF}/assets/icons`;

const ICONS = {
    test: "📝",
    pass: "✅",
    fail: "❌",
    skip: "⏭️",
    time: "⏱️",
    other: "❓",
};

const icons = {
    pass: "✔",
    fail: "✖",
    skip: "⏭",
    time: "⏲",
    other: "？",
};

function statusIcon(status: TestStatus): string {
    switch (status) {
    case "passed":
        return ICONS.pass;
    case "failed":
        return ICONS.fail;
    case "skipped":
        return ICONS.skip;
    default:
        return ICONS.other;
    }
}

const output: string[] = [];
function emit(str: string): void {
    output.push(str);
}

const reports: Report[] = [];

for (const fn of await glob("ctrf/*.json")) {
    const contents = await fs.readFile(fn, { encoding: "utf-8" });
    reports.push(JSON.parse(contents) as Report);
}

for (const { results } of reports) {
    const tool = results.tool.name;
    for (const test of results.tests) {
        if (tool === "webdriverio") {
            test.suite = [tool, relname(test.filePath), ...test.suite];
        } else {
            test.suite = [tool, ...(test.suite || [])];
        }
        if (test.line == null) {
            test.line = await findTestLine(test);
        }
    }
}

const report = mergeReports(reports);
const tree = organizeTestsBySuite(report.results.tests, { includeSummary: true });

function duration(msec: number) {
    const result: (string | number)[] = [icons.time, " <em>"];
    const secs = msec / 1000;
    if (secs > 60) {
        result.push(Math.floor(secs / 60), ":", Math.round(secs % 60));
    } else {
        result.push(secs, "s");
    }
    result.push("</em>");
    return result.join("");
}

function summary(sum: Summary): string {
    return [
        icons.pass, sum.passed,
        icons.fail, sum.failed,
        icons.skip, sum.skipped,
        duration(sum.duration),
    ].join(" ");
}

function testPath(test: Test): string {
    if ("file_path" in test) {
        return relname(test.file_path as string);
    }
    return relname(test.filePath);
}

const CODE = "```";

function testLine(test: Test): string {
    if (test.line != null) {
        return `#L${test.line}`;
    }
    return `#:~:text=${encodeURIComponent(test.name)}`;
}

function emitTest(test: Test) {
    if (test.status === "failed") {
        emit("<details open><summary>");
    }

    emit(`${statusIcon(test.status)} <a href="${BASE_URL}/${testPath(test)}${testLine(test)}">${test.name}</a> ${duration(test.duration)}\n`);

    if (test.status !== "passed") {
        emit("</summary>\n");
        emit("<blockquote>");
        emit(`${test.message}<br>\n`);
        if (test.trace) {
            emit(`\n${CODE}\n${test.trace.trimEnd()}\n${CODE}\n\n`);
        }
        emit("</blockquote>\n");
        emit("</details>\n");
    } else {
        emit("<br>\n");
    }
}

function emitTests(tests: Test[]) {
    for (const test of tests) {
        emitTest(test);
    }
}

function emitSuite(node: TreeNode, parent?: TreeNode) {
    let attr = "";
    if (node.status === "failed") {
        attr += " open";
    }

    let name = node.name;
    if (parent && name.startsWith(parent.name + ".")) {
        name = name.substring(parent.name.length + 1);
    }

    let icon = "";
    if (!parent) {
        icon = `<img src="${ICON_BASE}/${node.name}.svg" height="16"> `;
    }

    emit(`<details${attr}>\n`);
    emit(`<summary>${statusIcon(node.status)} ${icon}${name} ${summary(node.summary)}</summary>\n`);

    emit("<blockquote>\n");
    for (const suite of node.suites) {
        emitSuite(suite, node);
    }

    emitTests(node.tests);

    emit("</blockquote>\n");
    emit("</details>\n");
}

for (const suite of tree.roots) {
    emitSuite(suite);
}

console.log(output.join(""));
