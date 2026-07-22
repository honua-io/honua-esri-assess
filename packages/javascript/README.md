# @honua/honua-migrate

JavaScript scanning, codemods, content migration, reconciliation, and reports
for moving ArcGIS applications and content to Honua.

Install the package and use the JavaScript-specific command:

```sh
npm install --save-dev @honua/honua-migrate
npx honua-js-migrate scan ./src
npx honua-js-migrate codemod ./src --write --report migration-report.json
```

The JavaScript package supports Node.js 20.19 and newer.

The JavaScript executable is intentionally named `honua-js-migrate`; the
unqualified `honua-migrate` command belongs to the canonical Python CLI.
