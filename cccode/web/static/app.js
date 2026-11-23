const $ = id => document.getElementById(id);
const messages = $('messages'), input = $('input'), scroll = $('scroll');
let socket, busy = false, currentText = null, currentThinking = null, activity = null, tools = new Map(), currentSession = '';
function resetTurn() { resetText(); activity = null; tools.clear(); }
function ensureActivity() { if (!activity) { const box = el('details', 'activity'); const summary = el('summary', 'activity-summary', '思考与操作'); const body = el('div', 'activity-body'); box.append(summary, body); if (currentText) messages.insertBefore(box, currentText.parentElement); else messages.append(box); activity = {box, body}; } return activity; }
function moveTextToActivity() { if (!currentText) return; const body = ensureActivity().body; const row = currentText.parentElement; const progress = el('div', 'activity-text'); progress.textContent = currentText.dataset.content; body.append(progress); row.remove(); currentText = null; }
function renderSessions(data) { currentSession = data.current; const nav = $('sessions'); nav.replaceChildren(); data.sessions.forEach(session => { const button = el('button', session.id === currentSession ? 'active' : '', session.title); button.type = 'button'; button.disabled = busy; button.title = session.title; button.onclick = () => { if (!busy && session.id !== currentSession) send({type:'resume', session_id:session.id}); }; nav.append(button); if (session.id === currentSession) $('header-title').textContent = session.title; }); }
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
function send(data) { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data)); }
function bottom() { scroll.scrollTop = scroll.scrollHeight; }
function resetText() { currentText = null; currentThinking = null; }
function notice(text, error = false) { if (!text) return; messages.append(el('div', 'notice' + (error ? ' error' : ''), text)); resetText(); bottom(); }
function userMessage(text) { $('welcome').hidden = true; const row = el('div', 'message user'); row.append(el('div', 'bubble', text)); messages.append(row); resetTurn(); bottom(); }
function renderMarkdown(node, text) {
  node.replaceChildren();
  const lines = text.split('\n');
  const inline = (target, content) => {
    const pieces = content.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    for (const part of pieces) {
      if (part.startsWith('`') && part.endsWith('`')) target.append(el('code', 'inline-code', part.slice(1, -1)));
      else if (part.startsWith('**') && part.endsWith('**')) target.append(el('strong', '', part.slice(2, -2)));
      else target.append(document.createTextNode(part));
    }
  };
  const cells = line => line.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith('```')) {
      const code = el('pre', 'code-block');
      while (++i < lines.length && !lines[i].trim().startsWith('```')) code.append(document.createTextNode(lines[i] + '\n'));
      node.append(code); continue;
    }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i + 1])) {
      const wrapper = el('div', 'table-wrap'), table = el('table', 'markdown-table'), head = el('thead'), tr = el('tr');
      cells(line).forEach(value => { const cell = el('th'); inline(cell, value); tr.append(cell); }); head.append(tr); table.append(head);
      const body = el('tbody'); i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { const row = el('tr'); cells(lines[i]).forEach(value => { const cell = el('td'); inline(cell, value); row.append(cell); }); body.append(row); i++; }
      i--; table.append(body); wrapper.append(table); node.append(wrapper); continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const row = el(heading ? 'h' + (heading[1].length + 2) : 'div', 'md-line');
    const content = heading ? heading[2] : line;
    inline(row, content);
    if (!content) row.append(document.createElement('br'));
    node.append(row);
  }
}
function assistantText(text) { currentThinking = null; $('welcome').hidden = true; if (!currentText) { const row = el('div', 'message assistant'); const head = el('div', 'assistant-head'); const avatar = el('img', 'avatar app-icon'); avatar.src = '/static/cccode-icon.png'; avatar.width = 25; avatar.height = 25; avatar.alt = ''; head.append(avatar, document.createTextNode('CcCode')); currentText = el('div', 'assistant-body'); currentText.dataset.content = ''; row.append(head, currentText); messages.append(row); } currentText.dataset.content += text; renderMarkdown(currentText, currentText.dataset.content); bottom(); }
function thinkingText(text) { $('welcome').hidden = true; moveTextToActivity(); if (!currentThinking) { currentThinking = el('div', 'activity-thinking'); ensureActivity().body.append(currentThinking); } currentThinking.append(document.createTextNode(text)); bottom(); }
function toolStart(data) { $('welcome').hidden = true; moveTextToActivity(); currentThinking = null; const box = el('details', 'activity-tool'); const summary = el('summary', '', '◌  ' + data.tool_name + ' · 执行中'); const detail = el('pre', '', '参数\n' + JSON.stringify(data.arguments, null, 2)); box.append(summary, detail); ensureActivity().body.append(box); tools.set(data.tool_id, {summary, detail, name:data.tool_name}); activity.box.querySelector('.activity-summary').textContent = '思考与操作 · ' + data.tool_name + ' 执行中'; bottom(); }
function toolEnd(data) { const tool = tools.get(data.tool_id); if (!tool) return; tool.summary.textContent = (data.is_error ? '×  ' : '✓  ') + tool.name + (data.is_error ? ' · 失败' : ' · 已完成'); tool.detail.textContent += '\n\n结果\n' + data.result; if (activity) activity.box.querySelector('.activity-summary').textContent = '思考与操作'; }
function interaction(title, description) { const panel = el('div', 'interaction'); panel.append(el('strong', '', title)); if (description) panel.append(el('pre', '', description)); $('interaction').replaceChildren(panel); return panel; }
function permission(data) { const panel = interaction('需要你的许可 · ' + data.tool, JSON.stringify(data.args, null, 2)); for (const [label, value, cls] of [['允许','allow','primary'],['始终允许','allow_always',''],['拒绝','deny','']]) { const b = el('button', cls, label); b.onclick = () => { send({type:'permission', value}); $('interaction').replaceChildren(); }; panel.append(b); } }
function question(data) { const panel = interaction('Agent 需要你的回答'); const fields = []; data.questions.forEach((q, index) => { const label = el('p', '', q.question); panel.append(label); if (q.options && q.options.length) { const select = el('select'); select.multiple = !!q.multi_select; q.options.forEach(option => { const o = el('option', '', option.label + (option.description ? ' — ' + option.description : '')); o.value = option.label; select.append(o); }); panel.append(select); fields.push(() => select.multiple ? [...select.selectedOptions].map(o => o.value).join(', ') : select.value); } else { const field = el('input'); field.setAttribute('aria-label', q.question); panel.append(field); fields.push(() => field.value); } }); const button = el('button', 'primary', '提交回答'); button.onclick = () => { const answers = {}; fields.forEach((get, i) => answers[String(i)] = get()); send({type:'answer', answers}); $('interaction').replaceChildren(); }; panel.append(button); }
function state(value) { busy = value; const sendButton = $('send'); sendButton.disabled = !socket || socket.readyState !== WebSocket.OPEN; sendButton.type = busy ? 'button' : 'submit'; sendButton.textContent = busy ? '■' : '↑'; sendButton.setAttribute('aria-label', busy ? '停止运行' : '发送消息'); sendButton.title = busy ? '停止运行' : '发送消息'; sendButton.classList.toggle('is-stopping', busy); sendButton.classList.toggle('has-input', !busy && !!input.value.trim() && !sendButton.disabled); $('mode-trigger').disabled = busy || !socket || socket.readyState !== WebSocket.OPEN; if (busy) closeModeMenu(); if (!busy) { $('interaction').replaceChildren(); resetText(); } }
function eventMessage(msg) { if (msg.type === 'ready') { $('model').textContent = msg.model; $('cwd').textContent = msg.cwd; $('workspace').textContent = msg.cwd.split('/').filter(Boolean).pop() || '当前项目'; setMode(msg.mode); $('connection').textContent = '已连接'; $('dot').classList.remove('off'); state(false); } else if (msg.type === 'completions') renderCompletions(msg); else if (msg.type === 'sessions') renderSessions(msg); else if (msg.type === 'busy') { state(msg.busy); document.querySelectorAll('#sessions button').forEach(button => button.disabled = msg.busy); } else if (msg.type === 'status') setMode(msg.mode); else if (msg.type === 'error') notice(msg.message, true); else if (msg.type === 'notice') notice(msg.text); else if (msg.type === 'text') assistantText(msg.text); else if (msg.type === 'permission') permission(msg); else if (msg.type === 'question') question(msg); else if (msg.type === 'clear') { messages.replaceChildren(); $('welcome').hidden = false; resetTurn(); } else if (msg.type === 'restore') { messages.replaceChildren(); $('welcome').hidden = msg.messages.length > 0; resetTurn(); msg.messages.forEach(m => { resetText(); if (m.role === 'user' && m.text) userMessage(m.text); (m.thinking || []).forEach(thinkingText); if (m.role === 'assistant' && m.text) assistantText(m.text); (m.tool_uses || []).forEach(t => toolStart({tool_id:t.id, tool_name:t.name, arguments:t.arguments})); (m.tool_results || []).forEach(t => toolEnd({tool_id:t.tool_use_id, result:t.content, is_error:t.is_error})); }); resetText(); } else if (msg.type === 'agent_event') { const d = msg.data; switch (msg.event) { case 'StreamText': assistantText(d.text); break; case 'ThinkingText': thinkingText(d.text); break; case 'ToolUseEvent': toolStart(d); break; case 'ToolResultEvent': toolEnd(d); break; case 'ErrorEvent': notice(d.message, true); break; case 'RetryEvent': notice('正在重试：' + d.reason); break; case 'CompactNotification': notice(d.message); break; case 'LoopComplete': resetText(); break; } } }
function connect() { socket = new WebSocket(`ws://${location.host}/ws`); socket.onmessage = e => { try { eventMessage(JSON.parse(e.data)); } catch(err) { notice('消息解析失败', true); } }; socket.onclose = () => { $('connection').textContent = '连接已断开'; $('dot').classList.add('off'); state(false); $('send').disabled = true; }; socket.onerror = () => notice('连接失败，请检查 CcCode 服务是否正在运行。', true); }
$('form').onsubmit = e => { e.preventDefault(); const text = input.value.trim(); hideCompletions(); if (!text || busy || socket.readyState !== WebSocket.OPEN) return; userMessage(text); send({type:'message', text}); state(true); input.value = ''; input.style.height = ''; state(true); };
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('form').requestSubmit(); } });
input.addEventListener('input', () => { $('send').classList.toggle('has-input', !busy && !!input.value.trim() && !$('send').disabled); input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 180) + 'px'; });
$('send').addEventListener('click', () => { if (busy) send({type:'stop'}); });
const completionBox = $('completions');
let completionIndex = 0;
function hideCompletions() { completionBox.hidden = true; completionBox.replaceChildren(); completionIndex = 0; }
function selectCompletion(button) { input.value = button.dataset.value + ' '; $('send').classList.toggle('has-input', !busy && !$('send').disabled); hideCompletions(); input.focus(); }
function renderCompletions(msg) {
  if (msg.query !== input.value || busy || !input.value.startsWith('/')) return;
  completionBox.replaceChildren(); completionIndex = 0;
  for (const [group, title] of [['command', '命令'], ['skill', '技能']]) {
    const entries = msg.entries.filter(entry => entry.group === group);
    if (!entries.length) continue;
    completionBox.append(el('div', 'completion-heading', title));
    for (const entry of entries) {
      const button = el('button', 'completion-option'); button.type = 'button'; button.dataset.value = entry.value; button.setAttribute('role', 'option');
      const icon = el('span', 'completion-icon', group === 'skill' ? '◇' : '›');
      button.append(icon, el('strong', '', entry.value), el('span', 'completion-description', entry.description));
      if (group === 'skill') button.append(el('span', 'completion-source', ({project:'项目', user:'个人', builtin:'内置'})[entry.source] || '技能'));
      button.addEventListener('click', () => selectCompletion(button)); completionBox.append(button);
    }
  }
  const options = completionBox.querySelectorAll('.completion-option');
  if (options.length) { options[0].classList.add('active'); options[0].setAttribute('aria-selected', 'true'); }
  completionBox.hidden = !options.length;
}
input.addEventListener('input', () => { if (!busy && input.value.startsWith('/') && !input.value.includes(' ')) send({type:'complete', text:input.value}); else hideCompletions(); });
input.addEventListener('keydown', e => {
  if (completionBox.hidden || e.isComposing) return;
  const options = [...completionBox.querySelectorAll('.completion-option')];
  if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); hideCompletions(); }
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopImmediatePropagation(); completionIndex = (completionIndex + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length; options.forEach((option, i) => { option.classList.toggle('active', i === completionIndex); option.setAttribute('aria-selected', String(i === completionIndex)); }); options[completionIndex].scrollIntoView({block:'nearest'}); }
  else if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) { e.preventDefault(); e.stopImmediatePropagation(); selectCompletion(options[completionIndex]); }
}, true);
document.addEventListener('click', e => { if (!completionBox.contains(e.target) && e.target !== input) hideCompletions(); });
const modeMenu = $('mode-menu'), modeTrigger = $('mode-trigger');
function closeModeMenu() { modeMenu.hidden = true; modeTrigger.setAttribute('aria-expanded', 'false'); }
function setMode(value) { const option = modeMenu.querySelector(`[data-mode="${value}"]`); if (!option) return; $('mode-label').textContent = option.querySelector('strong').textContent; modeMenu.querySelectorAll('[data-mode]').forEach(item => item.setAttribute('aria-checked', String(item === option))); }
modeTrigger.addEventListener('click', () => { const open = modeMenu.hidden; modeMenu.hidden = !open; modeTrigger.setAttribute('aria-expanded', String(open)); });
modeMenu.addEventListener('click', event => { const option = event.target.closest('[data-mode]'); if (!option) return; send({type:'mode', value:option.dataset.mode}); closeModeMenu(); modeTrigger.focus(); });
document.addEventListener('click', event => { if (!$('mode-picker').contains(event.target)) closeModeMenu(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modeMenu.hidden) { closeModeMenu(); modeTrigger.focus(); } });
$('new-chat').onclick = () => { if (!busy) { send({type:'message', text:'/new'}); } };
document.querySelectorAll('[data-prompt]').forEach(b => b.onclick = () => { input.value = b.dataset.prompt; $('send').classList.toggle('has-input', !busy && !$('send').disabled); input.focus(); });
document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('new-chat').click(); } });
connect(); state(false);

$('workspace-button').onclick = () => { if (busy) return; const path = prompt('输入项目文件夹的完整路径', $('cwd').textContent); if (path && path.trim()) send({type:'workspace', path:path.trim()}); };
