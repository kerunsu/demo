(() => {
  'use strict';

  const state = { emotions: [], config: { enabled: false, rules: [] } };
  const byId = (id) => document.getElementById(id);

  async function jsonRequest(url, options = {}) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.success === false) {
      throw new Error(body.error || `HTTP ${response.status}`);
    }
    return body;
  }

  function effectiveCharCount(text) {
    return String(text || '').replace(/\s/g, '').length;
  }

  function readRules() {
    return Array.from(document.querySelectorAll('.dialogue-expression-rule')).map((row) => ({
      maxChars: Number(row.querySelector('[data-field="maxChars"]').value),
      emotion: row.querySelector('[data-field="emotion"]').value,
    }));
  }

  function optionLabel(name) {
    return String(name || '').replace(/\.mp4$/i, '').replaceAll('_', ' ');
  }

  function addRuleRow(rule = {}) {
    const container = byId('dialogue-expression-rules');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'dialogue-expression-rule';

    const maxLabel = document.createElement('label');
    maxLabel.textContent = '回复字数上限';
    const maxInput = document.createElement('input');
    maxInput.type = 'number';
    maxInput.min = '1';
    maxInput.max = '1000';
    maxInput.step = '1';
    maxInput.dataset.field = 'maxChars';
    maxInput.value = String(rule.maxChars || '');
    maxLabel.appendChild(maxInput);

    const emotionLabel = document.createElement('label');
    emotionLabel.textContent = '说话视频表情（MP4）';
    const select = document.createElement('select');
    select.dataset.field = 'emotion';
    state.emotions.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = optionLabel(name);
      select.appendChild(option);
    });
    select.value = rule.emotion || state.emotions[0] || '';
    emotionLabel.appendChild(select);

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'cc-btn danger small';
    remove.textContent = '删除';
    remove.addEventListener('click', () => {
      row.remove();
      updatePreview();
    });
    row.append(maxLabel, emotionLabel, remove);
    row.addEventListener('input', updatePreview);
    row.addEventListener('change', updatePreview);
    container.appendChild(row);
  }

  function render() {
    byId('dialogue-expression-enabled').checked = Boolean(state.config.enabled);
    const container = byId('dialogue-expression-rules');
    container.innerHTML = '';
    (state.config.rules || []).forEach(addRuleRow);
    updatePreview();
  }

  function updatePreview() {
    const target = byId('dialogue-expression-test-result');
    if (!target) return;
    const text = byId('dialogue-expression-test-text')?.value || '';
    const count = effectiveCharCount(text);
    const rules = readRules()
      .filter((rule) => Number.isInteger(rule.maxChars) && rule.maxChars > 0 && rule.emotion)
      .sort((a, b) => a.maxChars - b.maxChars);
    if (!count) {
      target.textContent = '输入文字后显示匹配结果';
      return;
    }
    if (!byId('dialogue-expression-enabled').checked) {
      target.textContent = `有效字数 ${count}；当前未启用，不触发表情匹配`;
      return;
    }
    if (!rules.length) {
      target.textContent = `有效字数 ${count}；尚未配置可用档位`;
      return;
    }
    const selected = rules.find((rule) => count <= rule.maxChars) || rules[rules.length - 1];
    target.textContent = `有效字数 ${count}；匹配 ${selected.emotion}（档位上限 ${selected.maxChars} 字）`;
  }

  async function save() {
    const button = byId('btn-save-dialogue-expression-rules');
    const status = byId('dialogue-expression-status');
    button.disabled = true;
    status.textContent = '正在保存...';
    try {
      const body = await jsonRequest('/api/robot/emotions/dialogue-reply-rules', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: byId('dialogue-expression-enabled').checked,
          rules: readRules(),
        }),
      });
      state.config = body.config;
      render();
      status.textContent = '已保存，下一次大模型回复立即生效';
    } catch (error) {
      status.textContent = `保存失败：${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  async function init() {
    const root = byId('dialogue-expression-card');
    if (!root) return;
    try {
      const [emotionBody, ruleBody] = await Promise.all([
        jsonRequest('/api/robot/emotions'),
        jsonRequest('/api/robot/emotions/dialogue-reply-rules'),
      ]);
      state.emotions = (emotionBody.emotions || []).filter((name) => /\.mp4$/i.test(name));
      state.config = ruleBody.config || state.config;
      render();
      if (!state.emotions.length) {
        byId('dialogue-expression-status').textContent = '表情库中没有可用 MP4，请先上传表情';
      }
    } catch (error) {
      byId('dialogue-expression-status').textContent = `加载失败：${error.message}`;
    }
    byId('btn-add-dialogue-expression-rule').addEventListener('click', () => {
      addRuleRow({ maxChars: '', emotion: state.emotions[0] || '' });
      updatePreview();
    });
    byId('btn-save-dialogue-expression-rules').addEventListener('click', save);
    byId('dialogue-expression-enabled').addEventListener('change', updatePreview);
    byId('dialogue-expression-test-text').addEventListener('input', updatePreview);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
