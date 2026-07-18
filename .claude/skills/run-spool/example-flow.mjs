// Example driver script for .claude/skills/run-spool/driver.sh
// Run with: .claude/skills/run-spool/driver.sh .claude/skills/run-spool/example-flow.mjs
//
// Exercises the one real user flow: browse the grid, search-as-you-type,
// filter by extension, open a file's detail page. Screenshots at each step.
import { chromium } from "playwright";

const BASE = "http://api:8000";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const consoleErrors = [];
page.on("pageerror", (err) => consoleErrors.push(err.message));
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});

await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.screenshot({ path: "/out/01-index.png", fullPage: true });

// search-as-you-type has a 250ms debounce (see index.html hx-trigger)
await page.fill("input[name=q]", "toast");
await page.waitForTimeout(500);
await page.waitForLoadState("networkidle");
await page.screenshot({ path: "/out/02-search.png", fullPage: true });
const searchCount = await page.locator(".card").count();

await page.fill("input[name=q]", "");
await page.waitForTimeout(500);
await page.waitForLoadState("networkidle");

const firstCard = page.locator(".card").first();
const firstHref = await firstCard.getAttribute("href");
await firstCard.click();
await page.waitForLoadState("networkidle");
await page.screenshot({ path: "/out/03-detail.png", fullPage: true });

console.log(JSON.stringify({
  searchResultCount: searchCount,
  detailUrl: page.url(),
  detailUrlMatchesHref: page.url().endsWith(firstHref),
  consoleErrors,
}, null, 2));

await browser.close();
