#!/usr/bin/env node
import { glob } from "glob";
import Mocha from "mocha";

const mocha = new Mocha({
    reporter: "allure-mocha",
    reporterOptions: {
        extraReporters: [
            "spec",
            ["mocha-ctrf-json-reporter", {
                outputFile: "mocha.json",
            }],
        ],
        resultsDir: "allure/results",
    },
});

for (const file of await glob("mocha-tests/**/*.test.{m,}{js,ts}")) {
    mocha.addFile(file);
}
await mocha.loadFilesAsync();
mocha.run(failures => process.exit(failures ? 1 : 0));
