const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file:///home/user/backtest/report/strategy_guide.html', { waitUntil: 'load' });
  await p.pdf({ path: '/home/user/backtest/report/Nifty_Intraday_Spread_Strategy_Guide.pdf', format: 'A4', printBackground: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:8px;color:#6b7280;width:100%;text-align:center;font-family:Arial">Nifty Intraday Spread Strategy · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>',
    margin: { top: '16mm', bottom: '18mm', left: '15mm', right: '15mm' } });
  await b.close();
})();
