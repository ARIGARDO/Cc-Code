const $ = id => document.getElementById(id);
const messages = $('messages'), input = $('input'), scroll = $('scroll');
let socket, busy = false, currentText = null, currentThinking = null, tools = new Map();
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
function send(data) { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data)); }
function bottom() { scroll.scrollTop = scroll.scrollHeight; }
function resetText() { currentText = null; currentThinking = null; }
function notice(text, error = false) { if (!text) return; messages.append(el('div', 'notice' + (error ? ' error' : ''), text)); resetText(); bottom(); }
function userMessage(text) { $('welcome').hidden = true; const row = el('div', 'message user'); row.append(el('div', 'bubble', text)); messages.append(row); resetText(); bottom(); }
function renderMarkdown(node, text) {
  node.replaceChildren();
  let inCode = false, code = null;
  for (const line of text.split('\n')) {
    if (line.trim().startsWith('```')) { if (inCode) { inCode = false; code = null; } else { inCode = true; code = el('pre', 'code-block'); node.append(code); } continue; }
    if (inCode) { code.append(document.createTextNode(line + '\n')); continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const row = el(heading ? 'h' + (heading[1].length + 2) : 'div', 'md-line');
    const content = heading ? heading[2] : line;
    const pieces = content.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    for (const part of pieces) { if (part.startsWith('`') && part.endsWith('`')) row.append(el('code', 'inline-code', part.slice(1, -1))); else if (part.startsWith('**') && part.endsWith('**')) row.append(el('strong', '', part.slice(2, -2))); else row.append(document.createTextNode(part)); }
    if (!content) row.append(document.createElement('br'));
    node.append(row);
  }
}
function assistantText(text) { $('welcome').hidden = true; if (!currentText) { const row = el('div', 'message assistant'); const head = el('div', 'assistant-head'); const avatar = el('img', 'avatar app-icon'); avatar.src = '/static/cccode-icon.png'; avatar.width = 25; avatar.height = 25; avatar.alt = ''; head.append(avatar, document.createTextNode('CcCode')); currentText = el('div', 'assistant-body'); currentText.dataset.content = ''; row.append(head, currentText); messages.append(row); } currentText.dataset.content += text; renderMarkdown(currentText, currentText.dataset.content); bottom(); }
function thinkingText(text) { $('welcome').hidden = true; if (!currentThinking) { const box = el('details', 'tool'); box.open = true; box.append(el('summary', '', '思考过程')); currentThinking = el('pre'); box.append(currentThinking); messages.append(box); } currentThinking.append(document.createTextNode(text)); bottom(); }
function toolStart(data) { resetText(); $('welcome').hidden = true; const box = el('details', 'tool'); const summary = el('summary', '', '◌  ' + data.tool_name + ' · 执行中'); const detail = el('pre', '', '参数\n' + JSON.stringify(data.arguments, null, 2)); box.append(summary, detail); messages.append(box); tools.set(data.tool_id, {summary, detail, name:data.tool_name}); bottom(); }
function toolEnd(data) { const tool = tools.get(data.tool_id); if (!tool) return; tool.summary.textContent = (data.is_error ? '×  ' : '✓  ') + tool.name + (data.is_error ? ' · 失败' : ' · 已完成'); tool.detail.textContent += '\n\n结果\n' + data.result; }
function interaction(title, description) { const panel = el('div', 'interaction'); panel.append(el('strong', '', title)); if (description) panel.append(el('pre', '', description)); $('interaction').replaceChildren(panel); return panel; }
function permission(data) { const panel = interaction('需要你的许可 · ' + data.tool, JSON.stringify(data.args, null, 2)); for (const [label, value, cls] of [['允许','allow','primary'],['始终允许','allow_always',''],['拒绝','deny','']]) { const b = el('button', cls, label); b.onclick = () => { send({type:'permission', value}); $('interaction').replaceChildren(); }; panel.append(b); } }
function question(data) { const panel = interaction('Agent 需要你的回答'); const fields = []; data.questions.forEach((q, index) => { const label = el('p', '', q.question); panel.append(label); if (q.options && q.options.length) { const select = el('select'); select.multiple = !!q.multi_select; q.options.forEach(option => { const o = el('option', '', option.label + (option.description ? ' — ' + option.description : '')); o.value = option.label; select.append(o); }); panel.append(select); fields.push(() => select.multiple ? [...select.selectedOptions].map(o => o.value).join(', ') : select.value); } else { const field = el('input'); field.setAttribute('aria-label', q.question); panel.append(field); fields.push(() => field.value); } }); const button = el('button', 'primary', '提交回答'); button.onclick = () => { const answers = {}; fields.forEach((get, i) => answers[String(i)] = get()); send({type:'answer', answers}); $('interaction').replaceChildren(); }; panel.append(button); }
function state(value) { busy = value; $('send').disabled = busy || !socket || socket.readyState !== WebSocket.OPEN; $('stop').hidden = !busy; $('mode').disabled = busy; if (!busy) { $('interaction').replaceChildren(); resetText(); } }
function eventMessage(msg) { if (msg.type === 'ready') { $('model').textContent = msg.model; $('cwd').textContent = msg.cwd; $('workspace').textContent = msg.cwd.split('/').filter(Boolean).pop() || '当前项目'; $('mode').value = msg.mode; $('connection').textContent = '已连接'; $('dot').classList.remove('off'); state(false); } else if (msg.type === 'busy') state(msg.busy); else if (msg.type === 'status') $('mode').value = msg.mode; else if (msg.type === 'error') notice(msg.message, true); else if (msg.type === 'notice') notice(msg.text); else if (msg.type === 'text') assistantText(msg.text); else if (msg.type === 'permission') permission(msg); else if (msg.type === 'question') question(msg); else if (msg.type === 'clear') { messages.replaceChildren(); $('welcome').hidden = false; resetText(); } else if (msg.type === 'restore') { messages.replaceChildren(); msg.messages.forEach(m => m.role === 'user' ? userMessage(m.text) : (resetText(), assistantText(m.text))); resetText(); } else if (msg.type === 'agent_event') { const d = msg.data; switch (msg.event) { case 'StreamText': assistantText(d.text); break; case 'ThinkingText': thinkingText(d.text); break; case 'ToolUseEvent': toolStart(d); break; case 'ToolResultEvent': toolEnd(d); break; case 'ErrorEvent': notice(d.message, true); break; case 'RetryEvent': notice('正在重试：' + d.reason); break; case 'CompactNotification': notice(d.message); break; case 'LoopComplete': resetText(); break; } } }
function connect() { socket = new WebSocket(`ws://${location.host}/ws`); socket.onmessage = e => { try { eventMessage(JSON.parse(e.data)); } catch(err) { notice('消息解析失败', true); } }; socket.onclose = () => { $('connection').textContent = '连接已断开'; $('dot').classList.add('off'); state(false); $('send').disabled = true; }; socket.onerror = () => notice('连接失败，请检查 CcCode 服务是否正在运行。', true); }
$('form').onsubmit = e => { e.preventDefault(); const text = input.value.trim(); if (!text || busy || socket.readyState !== WebSocket.OPEN) return; userMessage(text); send({type:'message', text}); state(true); input.value = ''; input.style.height = ''; };
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('form').requestSubmit(); } });
input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 180) + 'px'; });
$('stop').onclick = () => send({type:'stop'}); $('mode').onchange = e => send({type:'mode', value:e.target.value});
$('new-chat').onclick = () => { if (!busy) { send({type:'message', text:'/new'}); } };
document.querySelectorAll('[data-prompt]').forEach(b => b.onclick = () => { input.value = b.dataset.prompt; input.focus(); });
document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('new-chat').click(); } });
connect(); state(false);
