import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Marked } from '/Users/mihailkrahmalnik/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/marked/lib/marked.esm.js';
const root = path.dirname(fileURLToPath(import.meta.url));
const allowed = new Set(['index.md', 'notes.md', 'work-plan.md']);
const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const slug = s => s.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, '').trim().replace(/\s+/g, '-');
function read(name) {
  const target = path.join(root, name);
  if (fs.lstatSync(target).isSymbolicLink() || fs.realpathSync(target) !== target || fs.realpathSync(root) !== root) throw Error('Invalid path');
  const fd = fs.openSync(target, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try { if (!fs.fstatSync(fd).isFile()) throw Error('Not a file'); return fs.readFileSync(fd, 'utf8'); } finally { fs.closeSync(fd); }
}
function render(name, rules, chain = []) {
  const visited = [...chain, name];
  const prefix = chain.length ? `embedded-${visited.join('-').replaceAll('.', '-')}-` : '';
  const sections = [];
  const md = new Marked({gfm:true, renderer:{
    html({text}) { return escape(text); },
    heading({tokens, depth, text}) {
      const singleLink = tokens.length === 1 && tokens[0].type === 'link' ? tokens[0] : null;
      if (singleLink) text = singleLink.text;
      while (sections.length && sections.at(-1).depth >= depth) sections.pop();
      sections.push({depth, navigation: (rules.markdownLinks.navigationSections || []).includes(text.trim())});
      if (singleLink && allowed.has(singleLink.href)) {
        const heading = `<h${depth} id="${escape(prefix + slug(text))}"><a href="${escape(singleLink.href)}">${this.parser.parseInline(singleLink.tokens)}</a></h${depth}>`;
        if (sections.some(section => section.navigation) || visited.includes(singleLink.href) || visited.length >= rules.markdownLinks.maxDepth) return heading;
        return `<div class="md-link heading-link">${heading}<details class="embedded"${rules.markdownLinks.initiallyOpen ? ' open' : ''}><summary aria-label="Раскрыть или свернуть документ"> </summary><div class="document">${render(singleLink.href, rules, visited)}</div></details></div>`;
      }
      return `<h${depth} id="${escape(prefix + slug(text))}">${this.parser.parseInline(tokens)}</h${depth}>`; },
    paragraph({tokens}) { const text = this.parser.parseInline(tokens); return text.includes('<details') ? `<div class="paragraph">${text}</div>` : `<p>${text}</p>`; },
    link({href, tokens}) {
      const label = this.parser.parseInline(tokens);
      if (!href) return label;
      if (/^#[\p{L}\p{N}_-]+$/u.test(href)) return `<a href="#${escape(prefix + href.slice(1))}">${label}</a>`;
      const [file, anchor] = href.split('#');
      if (!allowed.has(file) || (anchor && !/^[\p{L}\p{N}_-]+$/u.test(anchor))) return label;
      const link = `<a href="${escape(href)}">${label}</a>`;
      if (sections.some(section => section.navigation) || rules.markdownLinks.mode !== 'inline-disclosure' || visited.includes(file) || visited.length >= rules.markdownLinks.maxDepth) return link;
      return `<div class="md-link">${link}<details class="embedded"${rules.markdownLinks.initiallyOpen ? ' open' : ''}><summary aria-label="Раскрыть или свернуть документ"> </summary><div class="document">${render(file, rules, visited)}</div></details></div>`;
    },
    image({text}) { return escape(text); }
  }});
  let source = read(name);
  if (chain.length && rules.markdownLinks.hideNavigationWhenEmbedded) {
    const lines = source.split('\n');
    let hiddenDepth = null;
    let fenced = false;
    source = lines.filter(line => {
      if (/^\s*```/.test(line)) fenced = !fenced;
      const heading = !fenced && /^(#{1,6})\s+(.+?)\s*$/.exec(line);
      if (heading) {
        const depth = heading[1].length;
        if (hiddenDepth !== null && depth <= hiddenDepth) hiddenDepth = null;
        if ((rules.markdownLinks.navigationSections || []).includes(heading[2])) hiddenDepth = depth;
      }
      return hiddenDepth === null;
    }).join('\n');
  }
  return md.parse(source);
}
const server = http.createServer((req,res) => {
  res.setHeader('Cache-Control','no-store');
  res.setHeader('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  res.setHeader('X-Content-Type-Options','nosniff');
  if (req.method !== 'GET') { res.writeHead(405); res.end(); return; }
  const name = req.url === '/' ? 'index.md' : req.url?.slice(1);
  if (!allowed.has(name)) { res.writeHead(404); res.end('Not found'); return; }
  try {
    const rules = JSON.parse(read('viewer-rules.json'));
    const css = Object.entries(rules.headings).map(([tag,value]) => {
      if (!/^h[1-6]$/.test(tag) || !/^#[0-9a-f]{6}$/i.test(value.color) || !Number.isFinite(value.sizeEm) || value.sizeEm <= 0 || value.sizeEm > 5) throw Error('Invalid heading setting');
      return `${tag}{color:${value.color};font-size:${value.sizeEm}em}`;
    }).join('');
    const body = render(name,rules);
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
    res.end(`<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Локальный Markdown</title><style>body{font:18px/1.6 system-ui,sans-serif;max-width:850px;margin:48px auto;padding:0 24px;color:#243447;background:#fafaf8}h1,h2,h3{line-height:1.25}a{color:#086f78}table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #becdc7;padding:12px;text-align:left}th{background:#e7efea}nav{font-size:14px;color:#65746e;border-bottom:1px solid #ccd8d0;padding-bottom:12px}.md-link{position:relative;padding-left:24px;margin:6px 0}.heading-link{margin:1.3em 0}.heading-link>h1,.heading-link>h2,.heading-link>h3{margin:0}.heading-link>h2 a{color:inherit}.embedded{margin:0}.embedded summary{position:absolute;left:0;top:0;cursor:pointer;color:#287344;width:20px}.embedded summary a{font-weight:400}.embedded summary::marker{color:#287344}.document{margin:12px 0 16px 6px;padding:4px 18px;border-left:3px solid #dce8df;background:#fff}.document h1{font-size:1.3em}.document h2{font-size:1.1em}.paragraph{margin:1em 0}${css}</style><nav>Локальный эксперимент · Markdown → HTML</nav><main>${body}</main></html>`);
  } catch(e) { console.error(e.message); res.writeHead(500); res.end('Unable to render document'); }
});
server.listen(Number(process.env.MARKDOWN_PREVIEW_PORT || 0),'127.0.0.1',()=>console.log(`http://127.0.0.1:${server.address().port}/index.md PID=${process.pid}`));
