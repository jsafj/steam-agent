const form = document.querySelector('#chat-form');
const input = document.querySelector('#message');
const send = document.querySelector('#send');
const status = document.querySelector('#status');
const messages = document.querySelector('#messages');
const welcome = document.querySelector('#welcome');
let busy = false;
let requestVersion = 0;
let controller = null;

function restoreInput() {
  busy = false;
  send.disabled = false;
  input.disabled = false;
  status.textContent = '';
  form.setAttribute('aria-busy', 'false');
}

document.querySelector('#home').addEventListener('click', () => {
  // 中断浏览器等待并忽略旧响应；不代表服务器正在运行的 Agent 已停止。
  requestVersion += 1;
  if (controller) controller.abort();
  controller = null;
  messages.replaceChildren();
  welcome.hidden = false;
  input.value = '';
  restoreInput();
  document.querySelector('#home').focus({preventScroll: true});
  window.scrollTo({top: 0, behavior: 'instant'});
});

document.querySelectorAll('[data-question]').forEach(button => {
  button.addEventListener('click', () => {
    if (busy) return;
    input.value = button.dataset.question;
    input.focus();
  });
});

function addMessage(text, role) {
  const item = document.createElement('section');
  item.className = `message ${role}`;
  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = role === 'user' ? '你' : '榜单分析 Agent';
  const body = document.createElement('div');
  body.className = 'body';
  // 模型输出始终作为文本处理，避免执行 HTML 或脚本。
  body.textContent = text;
  item.append(label, body);
  messages.append(item);
  item.scrollIntoView({block: 'end', behavior: 'smooth'});
}

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!busy) form.requestSubmit();
  }
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  const message = input.value.trim();
  if (busy || !message) return;
  busy = true;
  const version = ++requestVersion;
  const requestController = new AbortController();
  controller = requestController;
  send.disabled = true;
  input.disabled = true;
  welcome.hidden = true;
  addMessage(message, 'user');
  input.value = '';
  status.textContent = '正在分析…';
  form.setAttribute('aria-busy', 'true');
  try {
    const response = await fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message}), signal: requestController.signal
    });
    const data = await response.json();
    if (version !== requestVersion) return;
    if (!response.ok || !data.ok || typeof data.answer !== 'string' || !data.answer.trim()) throw new Error('request failed');
    addMessage(data.answer, 'assistant');
  } catch {
    if (version !== requestVersion) return;
    addMessage('本次分析失败，请稍后重试。你可以重新输入或发送这个问题。', 'error');
    input.value = message;
  } finally {
    // 返回首页或开始新请求后，旧请求不得清空新状态或恢复旧输入。
    if (version === requestVersion) {
      controller = null;
      restoreInput();
      input.focus({preventScroll: true});
      messages.lastElementChild?.scrollIntoView({block: 'end', behavior: 'smooth'});
    }
  }
});
