import { defineConfig } from "allure";

/** @import { AwesomePluginOptions } from "@allurereport/plugin-awesome" */

export default defineConfig({
    name: "Test Report",
    historyPath: "allure/history.jsonl",
    output: "allure/report",
    plugins: {
        "awesome-suite": {
            import: "@allurereport/plugin-awesome",
            /** @type {AwesomePluginOptions} */
            options: {
                reportName: "Suite View",
                groupBy: ["framework", "parentSuite", "suite", "subSuite"],
            },
        },
        "awesome-package": {
            import: "@allurereport/plugin-awesome",
            /** @type {AwesomePluginOptions} */
            options: {
                reportName: "Package View",
                groupBy: ["framework", "package", "parentSuite", "suite", "subSuite"],
            },
        },
    },
});
