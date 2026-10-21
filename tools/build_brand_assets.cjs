// Render the original Smart-X Congo vector, without resampling the screenshot.
// SHARP_MODULE may point to an existing sharp installation; no network is used.
const fs = require('node:fs/promises');
const path = require('node:path');
const sharp = require(process.env.SHARP_MODULE || 'sharp');
const root = path.resolve(__dirname, '..');

(async () => {
  const svg = await fs.readFile(path.join(root, 'static/icons/sentinelle.svg'), 'utf8');
  const maskable = svg.replace('rx="30"', 'rx="0"').replace('<g transform=', '<g transform="translate(17.6 17.6) scale(.78)"><g transform=').replace('</g>', '</g></g>');
  const output = [];
  async function render(name, size, source = svg, opaque = false) {
    const target = path.join(root, name);
    await fs.mkdir(path.dirname(target), {recursive: true});
    let rendered = sharp(Buffer.from(source)).resize(size, size);
    if (opaque) rendered = rendered.flatten({background: '#23484c'}).removeAlpha();
    await rendered.png().toFile(target);
    output.push(name);
  }
  for (const size of [192, 512]) {
    await render(`static/icons/sentinelle-${size}.png`, size);
    await render(`static/icons/sentinelle-maskable-${size}.png`, size, maskable);
    await render(`mobile/web/icons/Icon-${size}.png`, size);
    await render(`mobile/web/icons/Icon-maskable-${size}.png`, size, maskable);
  }
  await render('static/icons/apple-touch-icon.png', 180);
  await render('static/icons/favicon-32.png', 32);
  await render('mobile/web/favicon.png', 32);
  await render('mobile/assets/branding/sentinelle.png', 512);
  for (const [density, size] of Object.entries({mdpi:48, hdpi:72, xhdpi:96, xxhdpi:144, xxxhdpi:192})) {
    await render(`mobile/android/app/src/main/res/mipmap-${density}/ic_launcher.png`, size);
  }
  const ios = 'mobile/ios/Runner/Assets.xcassets';
  const contents = JSON.parse(await fs.readFile(path.join(root, ios, 'AppIcon.appiconset/Contents.json')));
  const done = new Set();
  for (const item of contents.images) {
    if (!item.filename || done.has(item.filename)) continue;
    done.add(item.filename);
    await render(`${ios}/AppIcon.appiconset/${item.filename}`, Math.round(parseFloat(item.size) * parseFloat(item.scale)), svg.replace('rx="30"', 'rx="0"'), true);
  }
  for (const [suffix, size] of [['',96], ['@2x',192], ['@3x',288]]) {
    await render(`${ios}/LaunchImage.imageset/LaunchImage${suffix}.png`, size);
  }
  await fs.mkdir(path.join(root, 'tmp'), {recursive: true});
  await fs.writeFile(path.join(root, 'tmp/brand-rendered-files.json'), JSON.stringify(output, null, 2));
  console.log(`Rendered ${output.length} brand assets from the shared vector.`);
})();
