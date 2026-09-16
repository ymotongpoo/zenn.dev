
const ELK = require('elkjs');
let buf = '';
process.stdin.on('data', d => buf += d);
process.stdin.on('end', async () => {
  const elk = new ELK();
  try {
    const res = await elk.layout(JSON.parse(buf));
    process.stdout.write(JSON.stringify(res));
  } catch (e) {
    process.stderr.write(String(e && e.stack || e));
    process.exit(1);
  }
});
