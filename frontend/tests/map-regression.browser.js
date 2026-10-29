// Run against an indexed local app with an owned Playwright CLI session:
// playwright-cli --session=map-check run-code "$(cat frontend/tests/map-regression.browser.js)"
// Uses the recipient's real API data; does not ingest or modify any records.
async (page) => {
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const frame = () => page.evaluate(() => new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const mapResponse = () => page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/map" && response.ok());
  await page.goto(new URL("/#map", page.url()).href);
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#map-count").textContent.includes("passages"));
  await frame();
  const first = await (await page.request.get(new URL("/api/map?limit=5000", page.url()).href)).json();
  check(first.points.length > 0, "This integration check requires real indexed passages.");

  // Fixed-size pan/zoom must not clear/reallocate the canvas backing store.
  await page.evaluate(() => {
    window.mapSizeWrites = 0;
    for (const key of ["width", "height"]) {
      const descriptor = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, key);
      Object.defineProperty(HTMLCanvasElement.prototype, key, {
        ...descriptor,
        set(value) {
          if (this.id === "map") window.mapSizeWrites++;
          descriptor.set.call(this, value);
        },
      });
    }
  });
  for (let i = 0; i < 6; i++) {
    await page.locator("#zoom-in").click();
    await page.locator("#zoom-out").click();
  }
  await frame();
  check(await page.evaluate(() => window.mapSizeWrites) === 0, "Zoom reallocated an unchanged canvas.");
  await page.locator("#fit").click();
  await frame();

  // A fitted view must expand to include every appended page without requiring
  // an extra Fit click. The full bitmap should match an explicit final Fit.
  let pages = 1;
  while (await page.locator("#more-points").isVisible()) {
    check(pages++ < 100, "Map pagination did not terminate.");
    const response = mapResponse();
    await page.locator("#more-points").click();
    await response;
    await frame();
  }
  const loadedCount = await page.locator("#map-count").textContent();
  check(loadedCount.startsWith(first.total_points.toLocaleString("en-US")), "Map did not load the complete eligible result set.");
  const fitted = await page.locator("#map").evaluate((canvas) => canvas.toDataURL());
  await page.locator("#fit").click();
  await frame();
  check(fitted === await page.locator("#map").evaluate((canvas) => canvas.toDataURL()), "Appended points were not included in the fitted bounds.");

  // Loading another page must also respect a viewport the user has moved.
  if (first.next_cursor) {
    await page.reload();
    await page.waitForFunction(() => document.querySelector("#map-count").textContent.includes("passages"));
    await frame();
    await page.evaluate(() => {
      const ctx = document.querySelector("#map").getContext("2d");
      const fill = ctx.fillRect, arc = ctx.arc;
      ctx.fillRect = function (...args) { window.mapArcs = []; return fill.apply(this, args); };
      ctx.arc = function (x, y, ...args) { window.mapArcs.push([x, y]); return arc.call(this, x, y, ...args); };
    });
    await page.locator("#zoom-in").click();
    await frame();
    const before = await page.evaluate(() => window.mapArcs[0]);
    const response = mapResponse();
    await page.locator("#more-points").click();
    await response;
    await frame();
    const after = await page.evaluate(() => window.mapArcs[0]);
    check(before && JSON.stringify(before) === JSON.stringify(after), "Pagination moved the user's zoomed viewport.");
  }

  // A narrow source panel must stay within the viewport and let the user reach
  // its branch action; this used to overflow beyond the screen.
  await page.setViewportSize({ width: 460, height: 780 });
  await page.locator("#toggle-list").click();
  await page.locator("#point-list button").nth(Math.min(12, first.points.length - 1)).click();
  const title = await page.locator("#source-title").textContent();
  const geometry = await page.locator("#source-dialog").evaluate((dialog) => {
    const rect = dialog.getBoundingClientRect();
    return { top: rect.top, bottom: rect.bottom, viewport: innerHeight };
  });
  check(geometry.top >= 0 && geometry.bottom <= geometry.viewport, "Source panel extends outside the mobile viewport.");
  const scoped = mapResponse();
  await page.locator("#source-scope").click();
  const scopedData = await (await scoped).json();
  check(await page.locator("#scope-button").textContent() === title, "A cited branch is mislabeled All sources.");
  const cleared = mapResponse();
  await page.locator("#clear-scope").click();
  await cleared;
  check(await page.locator("#scope-button").textContent() === "All sources", "Clear did not restore the full collection.");
  return { pages, loadedCount, branch: title, scopedPoints: scopedData.total_points, canvasReallocationsDuringZoom: 0, mobilePanelWithinViewport: true };
}
