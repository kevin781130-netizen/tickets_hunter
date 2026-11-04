// Offline browser harness: runs page scripts against synthetic fixture HTML in
// headless Chromium. No network: every request to the NCL host is fulfilled
// locally. Reads {cases:[...]} from stdin, writes {results:[...]} to stdout.
const { chromium } = require('playwright');

async function main() {
  const input = JSON.parse(await new Promise((resolve) => {
    let data = '';
    // Decode as UTF-8 stream: appending raw Buffers would split multi-byte
    // characters at chunk boundaries and randomly corrupt Chinese labels.
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
  }));
  const browser = await chromium.launch();
  const results = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    for (const testCase of input.cases) {
      const page = await context.newPage();
      await page.route('**/*', (route) => {
        const url = route.request().url();
        if (url.startsWith('https://spms.ncl.edu.tw/') || url.startsWith('https://other.example/')) {
          return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: testCase.html });
        }
        return route.abort();
      });
      const out = { id: testCase.id, steps: [], error: null };
      try {
        await page.goto(testCase.url || 'https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp');
        let previous = null;
        for (const step of testCase.steps) {
          if (step.click_prev_xy) {
            // Only click when the previous step really authorised a pointer click.
            const ok = previous && previous.code === 'READY_FOR_POINTER_CLICK' &&
              Number.isFinite(previous.x) && Number.isFinite(previous.y);
            if (ok) await page.mouse.click(previous.x, previous.y);
            out.steps.push({ clicked: !!ok });
            previous = null;
            continue;
          }
          const value = await page.evaluate(step.js);
          out.steps.push(value);
          previous = value;
        }
      } catch (error) {
        out.error = String(error && error.message || error).slice(0, 300);
      }
      await page.close();
      results.push(out);
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ results }));
}
main().catch((error) => { process.stderr.write(String(error)); process.exit(1); });
