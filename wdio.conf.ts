import * as fs from "fs/promises";
import path from "node:path";

import type { VisualServiceOptions } from "@wdio/visual-service";

import { card } from "./wdio-tests/card.ts";
import server from "./wdio-tests/server.ts";

declare global {
    interface Window {
        __coverage__?: object;
    }
}

const baseline_extra = [];
if (process.env.AWKS_ENV) {
    baseline_extra.push(process.env.AWKS_ENV);
}

export const config: WebdriverIO.Config = {
    runner: "local",
    tsConfigPath: "./tsconfig.json",

    specs: [
        "./wdio-tests/**/*.test.ts",
    ],
    exclude: [
    ],
    maxInstances: 10,
    autoXvfb: true,
    capabilities: [{
        browserName: "chrome",
        "goog:chromeOptions": {
            args: [
                "--disable-dev-shm-usage",
                // FIXME: This causes some tests to screenshot the wrong
                // portion of the page.
                // "--disable-infobars",
                "--no-sandbox",
                "--window-size=800,800",
            ],
        },
    }],

    logLevel: "info",
    maskingPatterns: String(/BIDI.*?\{.{160}(.*)\}/),

    // Default timeout for all waitFor* commands.
    waitforTimeout: 10000,
    //
    // Default timeout in milliseconds for request
    // if browser driver or grid doesn't send response
    connectionRetryTimeout: 120000,
    //
    // Default request retries count
    connectionRetryCount: 3,

    services: [
        [
            "visual",
            {
                baselineFolder: path.join(import.meta.dirname, "wdio-tests", "baseline", ...baseline_extra),
                compareOptions: {
                    createJsonReportFiles: true,
                },
                createJsonReportFiles: true,
                screenshotPath: path.join(import.meta.dirname, "tmp", "screenshots"),
                savePerInstance: true,
            } satisfies VisualServiceOptions,
        ],
    ],

    framework: "mocha",

    reporters: [
        "spec",
        ["allure", { outputDir: "allure/results" }],
        ["ctrf-json", { outputDir: "./ctrf" }],
    ],

    mochaOpts: {
        ui: "bdd",
        timeout: 60000,
    },

    /**
     * Gets executed just before initialising the webdriver session and test framework. It allows you
     * to manipulate configurations depending on the capability or spec.
     */
    beforeSession: async function (config, _capabilities, _specs, _cid) {
        await server.start();
        config.baseUrl = server.rootURL;
    },

    /**
     * Gets executed right after terminating the webdriver session.
     */
    afterSession: function (_config, _capabilities, _specs) {
        server.stop();
    },

    /**
     * Gets executed before test execution begins. At this point you can access to all global
     * variables like `browser`. It is the perfect place to define custom commands.
     */
    before: async function (_capabilities, _specs: string[], browser: WebdriverIO.Browser) {
        await browser.sessionSubscribe({ events: ["log.entryAdded"] });
        browser.on("log.entryAdded", entry => {
            console[entry.level](`[browser log]: ${entry.text}`);
        });

        await browser.setWindowSize(800, 800);
        await browser.url("index.html");
        await card.init();
    },

    /**
     * Gets executed after all tests are done. You still have access to all global variables from
     * the test.
     */
    after: async function (_result: number, _capabilities, _specs: string[]) {
        const coverage = await browser.execute(() => window.__coverage__);

        const coverageDir = path.resolve(import.meta.dirname, "coverage");
        await fs.mkdir(coverageDir, { recursive: true });

        const fn = path.join(coverageDir, `coverage-${Math.floor(Date.now() / 2000)}.json`);
        console.log("writeFile", fn, typeof coverage, typeof JSON.stringify(coverage));
        await fs.writeFile(fn, JSON.stringify(coverage));
    },
};
